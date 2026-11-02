"""Assignment-specific input formats, so generated inputs are valid for the problem at hand.

A teacher can describe the input in rules.json:

    "input_spec": {
      "lines": [
        [{"name": "n", "type": "int", "min": 1, "max": 100000}],
        [{"name": "values", "type": "int_list", "length": "n", "min": -1000, "max": 1000}]
      ],
      "size_field": "n"
    }

Field types: "int" (min, max) and "int_list" (length = an earlier int field or a number; min, max).
"size_field" names the int that controls the input size (used by the complexity estimator);
"scale_fields" can instead name ints whose *value* is the size (e.g. "print the primes up to N").

Without an input_spec the format is inferred from the accepted tests when every token is an
integer: either a fixed number of integers per line, or a count followed by that many values.
Anything else (strings, mixed formats) cannot be generated, and the analyzers say so.
"""
import random
import re

INT_MIN, INT_MAX = -(2 ** 31), 2 ** 31 - 1
INT_RE = re.compile(r"^[+-]?\d+$")
TYPES = {"int", "int_list"}
MAX_LIST = 1_000_000


class SpecError(ValueError):
    pass


# ------------------------------------------------------------------ validation
def validate(spec: dict) -> None:
    if not isinstance(spec, dict) or not isinstance(spec.get("lines"), list) or not spec["lines"]:
        raise SpecError("input_spec needs a non-empty 'lines' list")
    ints: set[str] = set()
    names: set[str] = set()
    for line in spec["lines"]:
        if not isinstance(line, list) or not line:
            raise SpecError("each input_spec line must be a non-empty list of fields")
        for f in line:
            if not isinstance(f, dict) or not re.match(r"^[A-Za-z_]\w{0,31}$", str(f.get("name", ""))):
                raise SpecError("every input_spec field needs a simple 'name'")
            if f["name"] in names:
                raise SpecError(f"duplicate input_spec field {f['name']!r}")
            if f.get("type") not in TYPES:
                raise SpecError(f"field {f['name']!r}: type must be one of {sorted(TYPES)}")
            lo, hi = f.get("min", INT_MIN), f.get("max", INT_MAX)
            if not all(isinstance(v, (int, float)) for v in (lo, hi)) or lo > hi:
                raise SpecError(f"field {f['name']!r}: min/max must be numbers with min <= max")
            if f["type"] == "int_list":
                ln = f.get("length")
                if isinstance(ln, str):
                    if ln not in ints:
                        raise SpecError(f"field {f['name']!r}: length must name an earlier int field")
                elif not (isinstance(ln, int) and 0 <= ln <= MAX_LIST):
                    raise SpecError(f"field {f['name']!r}: length must be a field name or a number")
            else:
                ints.add(f["name"])
            names.add(f["name"])
    sf = spec.get("size_field")
    if sf is not None and sf not in ints:
        raise SpecError("size_field must name an int field")
    for name in spec.get("scale_fields") or []:
        if name not in ints:
            raise SpecError("scale_fields must name int fields")


def fields(spec: dict) -> list[dict]:
    return [f for line in spec["lines"] for f in line]


def field(spec: dict, name: str) -> dict:
    return next(f for f in fields(spec) if f["name"] == name)


# ------------------------------------------------------------------- inference
def _tokens(text: str) -> list[list[str]]:
    lines = (text or "").replace("\r\n", "\n").strip("\n").split("\n")
    return [ln.split() for ln in lines]


def infer(tests: list[dict]) -> dict | None:
    """Guess an input_spec from accepted tests whose inputs contain only integers."""
    parsed = [_tokens(t.get("input", "")) for t in tests]
    if not parsed or any(not any(p) for p in parsed):
        return None
    flat = [tok for p in parsed for line in p for tok in line]
    if not flat or not all(INT_RE.match(tok) for tok in flat):
        return None
    shapes = {tuple(len(line) for line in p) for p in parsed}

    counted = all(
        int(toks[0]) >= 0 and len(toks) - 1 == int(toks[0])
        for toks in ([tok for line in p for tok in line] for p in parsed)
    )
    counts = [int(p[0][0]) for p in parsed]
    if counted and len(parsed) >= 2 and max(counts) > 1:
        values = [int(tok) for p in parsed for tok in [t for line in p for t in line][1:]]
        two_lines = sum(1 for p in parsed if len(p) >= 2 and len(p[0]) == 1) >= len(parsed) / 2
        n_field = {"name": "n", "type": "int", "min": min(counts), "max": max(counts)}
        list_field = {"name": "values", "type": "int_list", "length": "n",
                      "min": min(values, default=0), "max": max(values, default=0)}
        lines = [[n_field], [list_field]] if two_lines else [[n_field, list_field]]
        return {"lines": lines, "size_field": "n", "inferred": True,
                "note": "inferred from the accepted tests: a count n followed by n integers"}

    # Fixed layout: the shape most tests share (LLM-written tests sometimes contain an odd one out).
    counts_by_shape: dict[tuple, int] = {}
    for p in parsed:
        shape = tuple(len(line) for line in p)
        counts_by_shape[shape] = counts_by_shape.get(shape, 0) + 1
    shape, hits = max(counts_by_shape.items(), key=lambda kv: (kv[1], -len(kv[0])))
    if hits / len(parsed) < 0.6:
        return None
    same = [p for p in parsed if tuple(len(line) for line in p) == shape]
    lines = []
    for li, width in enumerate(shape):
        line = []
        for ti in range(width):
            vals = [int(p[li][ti]) for p in same]
            line.append({"name": f"v{li + 1}_{ti + 1}", "type": "int", "min": min(vals), "max": max(vals)})
        lines.append(line)
    note = f"inferred from the accepted tests: {sum(shape)} integer(s) in a fixed layout"
    if hits < len(parsed):
        note += f" ({len(parsed) - hits} test(s) with a different layout were ignored)"
    spec = {"lines": lines, "inferred": True, "note": note}
    spec["scale_fields"] = [f["name"] for f in fields(spec)]
    return spec


def allows_negative(spec: dict) -> bool:
    return any(f.get("min", INT_MIN) < 0 for f in fields(spec))


# ------------------------------------------------------------------- rendering
def render(spec: dict, values: dict) -> str:
    out = []
    for line in spec["lines"]:
        toks = []
        for f in line:
            v = values[f["name"]]
            toks.extend(str(x) for x in v) if isinstance(v, list) else toks.append(str(v))
        out.append(" ".join(toks))
    return "\n".join(out) + "\n"


def _clamp(f: dict, v: int) -> int:
    return int(max(f.get("min", INT_MIN), min(f.get("max", INT_MAX), v)))


def _length(spec: dict, f: dict, values: dict) -> int:
    ln = f["length"]
    return int(values[ln]) if isinstance(ln, str) else int(ln)


def build(spec: dict, rng: random.Random, overrides: dict | None = None, value_fn=None) -> dict:
    """Assign every field a value: overrides first, then value_fn(field, rng), then random in range."""
    overrides = overrides or {}
    values: dict = {}
    for f in fields(spec):
        if f["name"] in overrides:
            values[f["name"]] = overrides[f["name"]]
            continue
        lo, hi = int(f.get("min", INT_MIN)), int(f.get("max", INT_MAX))

        def one():
            v = value_fn(f, rng) if value_fn else None
            return _clamp(f, v) if v is not None else rng.randint(lo, hi)
        if f["type"] == "int":
            values[f["name"]] = one()
        else:
            values[f["name"]] = [one() for _ in range(max(0, _length(spec, f, values)))]
    return values


# --------------------------------------------------------------- edge themes
THEMES = {
    "negatives": "negative values",
    "zero": "zero values",
    "int_overflow": "values at the limits of a 32-bit int, where int arithmetic overflows",
    "boundary": "the smallest and largest allowed values",
    "duplicates": "repeated values",
    "empty": "an empty input (size 0)",
    "single": "a single element",
    "sorted": "values already in sorted order",
    "reverse_sorted": "values in descending order",
    "large": "the largest input size",
}
ALIASES = {"negative": "negatives", "overflow": "int_overflow", "min_max": "boundary", "limits": "boundary",
           "large_input": "large", "one_element": "single", "duplicate": "duplicates", "empty_input": "empty"}


def theme_name(raw: str) -> str:
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(key, key)


def edge_inputs(spec: dict, theme: str, rng: random.Random, max_list: int = 100_000) -> tuple[list[tuple[str, str]], str]:
    """Inputs for one theme: ([(input, reason)], note). An empty list means not applicable."""
    theme = theme_name(theme)
    ints = [f for f in fields(spec) if f["type"] == "int"]
    lists = [f for f in fields(spec) if f["type"] == "int_list"]
    size = spec.get("size_field")
    data_ints = [f for f in ints if f["name"] != size and not any(l.get("length") == f["name"] for l in lists)]
    cases: list[tuple[dict, str]] = []

    def small_n(n):
        return {size: _clamp(field(spec, size), n)} if size else {}

    if theme not in THEMES:
        return [], f"theme '{theme}' is not supported by the edge-case generator"
    if theme == "negatives":
        if not allows_negative(spec):
            return [], "not applicable: the input range has no negative values"
        neg = lambda f, r: -r.randint(1, max(1, min(1000, -int(f.get("min", -1)))))
        cases.append((build(spec, rng, small_n(5), neg), "all values negative"))
        if len(data_ints) >= 2:
            ov = {data_ints[0]["name"]: _clamp(data_ints[0], -7)}
            cases.append((build(spec, rng, ov, lambda f, r: r.randint(1, 50)), "a negative value mixed with positive ones"))
    elif theme == "zero":
        if any(f.get("min", 0) > 0 or f.get("max", 0) < 0 for f in data_ints + lists):
            return [], "not applicable: zero is outside the input range"
        cases.append((build(spec, rng, small_n(4), lambda f, r: 0), "all values zero"))
        if len(data_ints) >= 2:
            cases.append((build(spec, rng, {data_ints[0]["name"]: 0}, lambda f, r: r.randint(1, 50)), "one value zero"))
    elif theme == "int_overflow":
        # Deliberately at the C int limits, beyond what the statement may allow: the rules asked for it.
        hi = lambda f, r: INT_MAX
        lo = lambda f, r: INT_MIN
        top = {f["name"]: INT_MAX for f in data_ints}
        top.update({f["name"]: [INT_MAX] * 3 for f in lists})
        bottom = {f["name"]: INT_MIN for f in data_ints}
        bottom.update({f["name"]: [INT_MIN] * 3 for f in lists})
        if size:
            top[size] = bottom[size] = 3
        if data_ints and len(data_ints) >= 2:
            one = dict(top)
            one[data_ints[-1]["name"]] = 1
            cases.append((build(spec, rng, one, hi), "INT_MAX plus a positive value overflows a 32-bit int"))
            neg = dict(bottom)
            neg[data_ints[-1]["name"]] = -1
            cases.append((build(spec, rng, neg, lo), "INT_MIN minus a value overflows a 32-bit int"))
        elif data_ints or lists:
            cases.append((build(spec, rng, top, hi), "values at INT_MAX: sums or products overflow a 32-bit int"))
            cases.append((build(spec, rng, bottom, lo), "values at INT_MIN: negation or differences overflow"))
        else:
            return [], "not applicable: the input has no data values"
    elif theme == "boundary":
        mn = lambda f, r: int(f.get("min", INT_MIN))
        mx = lambda f, r: int(f.get("max", INT_MAX))
        cases.append((build(spec, rng, small_n(3), mn), "every value at its smallest allowed value"))
        cases.append((build(spec, rng, small_n(3), mx), "every value at its largest allowed value"))
    elif theme in ("duplicates", "sorted", "reverse_sorted", "single", "empty", "large"):
        if not lists:
            return [], f"not applicable: '{theme}' needs a list input"
        f = lists[0]
        sf = field(spec, size) if size else None
        if theme == "empty":
            if not sf or sf.get("min", 0) > 0:
                return [], "not applicable: the input size cannot be 0"
            cases.append((build(spec, rng, {size: 0}), THEMES[theme]))
        elif theme == "single":
            if sf and sf.get("min", 1) > 1:
                return [], "not applicable: the input size must be at least 2"
            cases.append((build(spec, rng, small_n(1)), THEMES[theme]))
        elif theme == "large":
            n = min(int(sf.get("max", 1000)) if sf else 1000, max_list)
            cases.append((build(spec, rng, {size: n} if size else {}), f"the largest input size (n = {n})"))
        else:
            n = _clamp(sf, 8) if sf else 8
            base = build(spec, rng, {size: n} if size else {})
            vals = base[f["name"]]
            if theme == "duplicates":
                base[f["name"]] = [vals[0]] * len(vals) if vals else vals
                cases.append((base, "every value the same"))
                mixed = build(spec, rng, {size: n} if size else {})
                mv = mixed[f["name"]]
                mixed[f["name"]] = [mv[i % 3] for i in range(len(mv))]
                cases.append((mixed, "a few values repeated many times"))
            elif theme == "sorted":
                base[f["name"]] = sorted(vals)
                cases.append((base, THEMES[theme]))
            else:
                base[f["name"]] = sorted(vals, reverse=True)
                cases.append((base, THEMES[theme]))
    return [(render(spec, v), why) for v, why in cases], ""


def random_inputs(spec: dict, count: int, rng: random.Random, max_size: int = 20) -> list[str]:
    """Small random inputs biased towards boundary values, for differential testing."""
    size = spec.get("size_field")
    out = []
    for i in range(count):
        overrides = {}
        if size:
            sf = field(spec, size)
            overrides[size] = rng.randint(int(sf.get("min", 0)), int(min(sf.get("max", max_size), max_size)))

        def pick(f, r):
            lo, hi = int(f.get("min", INT_MIN)), int(f.get("max", INT_MAX))
            roll = r.random()
            if roll < 0.15:
                return lo
            if roll < 0.3:
                return hi
            if roll < 0.4 and lo <= 0 <= hi:
                return 0
            return r.randint(lo, hi)
        out.append(render(spec, build(spec, rng, overrides, pick)))
    return out


# ------------------------------------------------------------------- scaling
def scaling_mode(spec: dict, params: dict) -> tuple[str, list[str]] | None:
    """How to make an input of size n: ("length", [size_field]) or ("value", [fields]) or None."""
    if spec.get("size_field"):
        return "length", [spec["size_field"]]
    names = params.get("scale_fields") or spec.get("scale_fields")
    if names:
        return "value", list(names)
    return None


def size_bounds(spec: dict, mode: tuple[str, list[str]]) -> tuple[int, int]:
    fs = [field(spec, n) for n in mode[1]]
    lo = max(int(f.get("min", 0)) for f in fs)
    hi = min(int(f.get("max", MAX_LIST)) for f in fs)
    if mode[0] == "length":
        hi = min(hi, MAX_LIST)
    return max(lo, 0), hi


def scaled_input(spec: dict, mode: tuple[str, list[str]], n: int, seed: int) -> str:
    rng = random.Random(seed * 1_000_003 + n)
    return render(spec, build(spec, rng, {name: n for name in mode[1]}))
