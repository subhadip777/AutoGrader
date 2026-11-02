"""similarity_flag: compare the submission with the other submissions of the same assignment.

Both programs are reduced to token streams in which comments, layout, #include lines and
identifier/literal spelling are ignored (renaming variables does not hide a copy). Similarity is
the Jaccard index of their k-token shingles. A value at or above flag_threshold raises a flag for
the instructor to review. It never proves copying and never lowers the grade: the score stays 1.0
and the report says the grade is provisional until the instructor has looked.
Teachers can add known solutions (online, LLM-written) as .c files in Problem/corpus/.
Params: flag_threshold (0.85), k (6), min_tokens (40).
"""
import re

from grading.analyzers.common import params, result
from grading.types import OK

KEYWORDS = set("""auto break case char const continue default do double else enum extern float for goto if
inline int long register restrict return short signed sizeof static struct switch typedef union unsigned
void volatile while _Bool bool""".split())
TOKEN = re.compile(r"""
    (?P<str>"(?:\\.|[^"\\])*") | (?P<chr>'(?:\\.|[^'\\])*') |
    (?P<num>\b\d[\w.]*\b) | (?P<id>[A-Za-z_]\w*) |
    (?P<op>->|\+\+|--|<<=?|>>=?|[<>!=]=|&&|\|\||[-+*/%&|^]=|[{}()\[\];,.?:~!<>=+\-*/%&|^])
""", re.X)


def tokens(source: str) -> list[str]:
    src = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"^\s*#[^\n]*", "", src, flags=re.M)
    out = []
    for m in TOKEN.finditer(src):
        kind = m.lastgroup
        if kind == "id":
            out.append(m.group() if m.group() in KEYWORDS else "ID")
        elif kind in ("str", "chr", "num"):
            out.append(kind.upper())
        else:
            out.append(m.group())
    return out


def shingles(toks: list[str], k: int) -> set[tuple]:
    return {tuple(toks[i:i + k]) for i in range(len(toks) - k + 1)} if len(toks) >= k else {tuple(toks)}


def similarity(a: str, b: str, k: int = 6) -> float:
    sa, sb = shingles(tokens(a), k), shingles(tokens(b), k)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def analyze(ctx, metric):
    p = params(metric)
    threshold = float(p.get("flag_threshold", 0.85))
    k = int(p.get("k", 6))
    min_tokens = int(p.get("min_tokens", 40))
    own = tokens(ctx.sub.source)
    corpus = ctx.sub.corpus
    scores = sorted(
        ({"label": c["label"], "kind": c.get("kind", "submission"), "similarity": round(similarity(ctx.sub.source, c["source"], k), 4)}
         for c in corpus),
        key=lambda x: (-x["similarity"], x["label"]))
    best = scores[0]["similarity"] if scores else 0.0
    too_short = len(own) < min_tokens
    flagged = bool(scores) and best >= threshold and not too_short
    if not scores:
        feedback = "No other submissions to compare with yet."
    elif flagged:
        feedback = (f"Very similar to another program (similarity {best:.2f}, threshold {threshold:.2f}). "
                    "This is flagged for the instructor to review; it is not a finding of copying.")
    elif too_short and best >= threshold:
        feedback = (f"Highest similarity {best:.2f}, but the program is too short ({len(own)} tokens) "
                    "for similarity to mean anything, so it is not flagged.")
    else:
        feedback = f"Highest similarity {best:.2f} against {len(scores)} other program(s); below the {threshold:.2f} threshold."
    # Students see only numbers; who they resemble is teacher-only information.
    return result(
        metric, status=OK, score=1.0, feedback=feedback,
        evidence={"max_similarity": best, "flag_threshold": threshold, "flagged": flagged,
                  "compared_with": len(scores), "tokens": len(own), "method": f"Jaccard of {k}-token shingles",
                  "note": "A flag only asks for human review; it never changes the score."},
        private={"matches": scores[:10]},
    )
