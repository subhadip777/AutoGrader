const aid = new URLSearchParams(location.search).get("id");
const ACTIVE = ["queued", "running", "grading", "reporting"];

const headingEl = document.getElementById("heading");
const statusEl = document.getElementById("status");
const tbody = document.querySelector("#subs tbody");
const detail = document.getElementById("detail");
const detailTitle = document.getElementById("detail-title");
const detailNotes = document.getElementById("detail-notes");
const reportText = document.getElementById("report-text");
const matchesBody = document.querySelector("#matches tbody");
const attemptsBody = document.querySelector("#attempts tbody");
const sourceEl = document.getElementById("source");
const regradeBtn = document.getElementById("regrade");
const dlTxt = document.getElementById("dl-txt");
const dlJson = document.getElementById("dl-json");

let selectedRoll = null;
let pollTimer = null;

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detailMsg = res.statusText;
    try {
      const body = await res.json();
      detailMsg = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail || detailMsg;
    } catch { /* keep statusText */ }
    throw new Error(detailMsg);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function gradeText(s) {
  if (typeof s.grade !== "number") return "-";
  return s.grade.toFixed(1) + (s.provisional ? " (provisional)" : "");
}

function renderList(rows) {
  tbody.replaceChildren();
  if (rows.length === 0) {
    const tr = el("tr");
    const td = el("td", "empty", "No submissions yet.");
    td.colSpan = 6;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const s of rows) {
    const tr = el("tr", "clickable" + (s.roll_number === selectedRoll ? " selected" : ""));
    tr.append(
      el("td", null, s.roll_number),
      el("td", null, s.name),
      el("td", null, String(s.attempt)),
      el("td", null, s.state + (s.state === "failed" && s.message ? `: ${s.message}` : "")),
      el("td", "grade-pill", gradeText(s)),
      el("td", null, (s.flags || []).join(", "))
    );
    tr.addEventListener("click", () => showDetail(s.roll_number));
    tbody.appendChild(tr);
  }
}

async function refresh() {
  try {
    const rows = await api(`/api/assignments/${encodeURIComponent(aid)}/submissions`);
    renderList(rows);
    const active = rows.filter((r) => ACTIVE.includes(r.state)).length;
    statusEl.textContent = `${rows.length} student(s)` + (active ? `, ${active} being graded` : "");
    clearTimeout(pollTimer);
    if (active) pollTimer = setTimeout(async () => {
      await refresh();
      if (selectedRoll) showDetail(selectedRoll, true);
    }, 3000);
  } catch (err) {
    statusEl.textContent = "Could not load submissions: " + err.message;
    statusEl.classList.add("error");
  }
}

async function showDetail(roll, quiet) {
  selectedRoll = roll;
  document.querySelectorAll("#subs tr.selected").forEach((t) => t.classList.remove("selected"));
  const base = `/api/assignments/${encodeURIComponent(aid)}/submissions/${encodeURIComponent(roll)}`;
  let d;
  try {
    d = await api(base);
  } catch (err) {
    if (!quiet) statusEl.textContent = err.message;
    return;
  }
  detail.hidden = false;
  const st = d.status;
  detailTitle.textContent = `${roll}: ${st.state}` + (typeof st.grade === "number" ? `, ${st.grade.toFixed(1)} / 100` : "");
  regradeBtn.disabled = ACTIVE.includes(st.state);
  const hasReport = Boolean(d.report);
  dlTxt.hidden = dlJson.hidden = !hasReport;
  dlTxt.href = `${base}/report?format=txt`;
  dlJson.href = `${base}/report?format=json`;

  detailNotes.replaceChildren();
  if (st.message) detailNotes.appendChild(el("p", "meta", st.message));
  if (d.report && d.report.flags.includes("originality_review")) {
    detailNotes.appendChild(el("p", "notice", "Similarity flag: compare the matches below by hand. A flag is not proof of copying."));
  }
  if (d.report && !d.report.complete) {
    detailNotes.appendChild(el("p", "notice",
      `Incomplete grade: ${[...d.report.incomplete_metrics, ...d.report.partial_metrics].join(", ")} could not be fully measured. Fix the tools and press Regrade.`));
  }
  if (hasReport) {
    reportText.textContent = await api(`${base}/report?format=txt`);
  } else {
    reportText.textContent = st.state === "done"
      ? "This submission was stored before grading existed. Press Regrade to grade it."
      : "No report yet.";
  }

  matchesBody.replaceChildren();
  const matches = ((d.review && d.review.originality) || []).flatMap((o) => o.matches || []);
  for (const m of matches) {
    const tr = el("tr");
    tr.append(el("td", null, m.label), el("td", null, m.kind), el("td", null, m.similarity.toFixed(2)));
    matchesBody.appendChild(tr);
  }
  if (!matches.length) {
    const tr = el("tr");
    const td = el("td", "empty", "No comparisons.");
    td.colSpan = 3;
    tr.appendChild(td);
    matchesBody.appendChild(tr);
  }

  attemptsBody.replaceChildren();
  for (const h of d.history.slice().reverse()) {
    const tr = el("tr");
    tr.append(
      el("td", null, String(h.attempt) + (h.current ? " (current)" : "")),
      el("td", null, h.submitted_at ? new Date(h.submitted_at).toLocaleString() : ""),
      el("td", null, h.state || ""),
      el("td", null, gradeText(h)),
      el("td", null, (h.sha256 || "").slice(0, 16))
    );
    attemptsBody.appendChild(tr);
  }
  sourceEl.textContent = d.source;
  document.querySelectorAll("#subs tr").forEach((t) => {
    if (t.firstChild && t.firstChild.textContent === roll) t.classList.add("selected");
  });
}

regradeBtn.addEventListener("click", async () => {
  if (!selectedRoll) return;
  regradeBtn.disabled = true;
  try {
    await api(`/api/assignments/${encodeURIComponent(aid)}/submissions/${encodeURIComponent(selectedRoll)}/regrade`, { method: "POST" });
    await refresh();
    await showDetail(selectedRoll);
  } catch (err) {
    statusEl.textContent = err.message;
    regradeBtn.disabled = false;
  }
});

async function init() {
  if (!aid) {
    statusEl.textContent = "No assignment id in the address.";
    return;
  }
  try {
    const meta = await api(`/api/assignments/${encodeURIComponent(aid)}`);
    headingEl.textContent = `Submissions: ${meta.title} (${meta.id})`;
  } catch (err) {
    statusEl.textContent = err.message;
    return;
  }
  await refresh();
}

init();
