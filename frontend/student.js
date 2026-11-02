const MAX_BYTES = 100000;
const STEPS = [
  ["running", "Running"],
  ["grading", "Grading"],
  ["reporting", "Creating the report"],
];
const ORDER = ["queued", "running", "grading", "reporting", "done"];

const tilesEl = document.getElementById("tiles");
const submitSection = document.getElementById("submit-section");
const formTitle = document.getElementById("form-title");
const form = document.getElementById("submit-form");
const aidInput = document.getElementById("aid");
const nameInput = document.getElementById("name");
const rollInput = document.getElementById("roll");
const fileInput = document.getElementById("file");
const formMessage = document.getElementById("form-message");
const submitBtn = document.getElementById("submit-btn");
const statementBtn = document.getElementById("view-statement");
const statementBox = document.getElementById("statement-box");
const statusSection = document.getElementById("status-section");
const statusTile = document.getElementById("status-tile");
const checkBtn = document.getElementById("check-btn");
const resultSection = document.getElementById("result-section");
const resultTitle = document.getElementById("result-title");
const resultBody = document.getElementById("result-body");
const historySection = document.getElementById("history-section");
const historyBody = document.querySelector("#history tbody");

let selected = null;   // {id, title}
let current = null;    // submission being tracked
let pollTimer = null;

// ---------- helpers ----------
async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = Array.isArray(body.detail)
        ? body.detail.map((d) => d.msg).join("; ")
        : body.detail || detail;
    } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ---------- assignment tiles ----------
function renderTiles(list) {
  tilesEl.replaceChildren();
  if (list.length === 0) {
    tilesEl.appendChild(el("p", "empty", "No active assignments right now."));
    return;
  }
  for (const a of list) {
    const tile = el("div", "tile clickable" + (selected && selected.id === a.id ? " selected" : ""));
    tile.tabIndex = 0;
    tile.setAttribute("role", "button");

    const idLine = el("p", "meta", "ID: ");
    idLine.appendChild(el("span", "id", a.id));
    tile.append(el("h3", null, a.title), idLine, el("p", "status", "ACTIVE"));

    tile.addEventListener("click", () => selectAssignment(a, tile));
    tile.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectAssignment(a, tile);
      }
    });
    tilesEl.appendChild(tile);
  }
}

async function loadAssignments() {
  try {
    renderTiles(await api("/api/student/assignments"));
  } catch (err) {
    tilesEl.replaceChildren(el("p", "empty", "Could not load assignments: " + err.message));
  }
}

function selectAssignment(a, tile) {
  selected = a;
  stopTracking();
  document.querySelectorAll(".tile.selected").forEach((t) => t.classList.remove("selected"));
  tile.classList.add("selected");

  aidInput.value = a.id;
  formTitle.textContent = `Submit your solution: ${a.title}`;
  formMessage.textContent = "";
  statementBox.hidden = true;
  statementBox.textContent = "";
  statementBtn.textContent = "View problem statement";
  statusSection.hidden = true;
  resultSection.hidden = true;
  historySection.hidden = true;
  submitSection.hidden = false;
  submitSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------- problem statement ----------
statementBtn.addEventListener("click", async () => {
  if (!selected) return;
  if (!statementBox.hidden) {
    statementBox.hidden = true;
    statementBtn.textContent = "View problem statement";
    return;
  }
  const id = selected.id;
  statementBtn.disabled = true;
  try {
    const data = await api(`/api/student/assignments/${encodeURIComponent(id)}`);
    if (!selected || selected.id !== id) return;
    statementBox.textContent = data.statement;
    statementBox.hidden = false;
    statementBtn.textContent = "Hide problem statement";
  } catch (err) {
    formMessage.textContent = "Could not load the statement: " + err.message;
  } finally {
    statementBtn.disabled = false;
  }
});

// ---------- submit ----------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formMessage.textContent = "";
  if (!selected) return;

  const name = nameInput.value.trim();
  const roll = rollInput.value.trim();
  const file = fileInput.files[0];

  if (!name) return (formMessage.textContent = "Please enter your name.");
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(roll)) {
    return (formMessage.textContent = "Roll number may contain only letters, digits, '-' and '_' (max 32).");
  }
  if (!file) return (formMessage.textContent = "Please choose your .c file.");
  if (!file.name.toLowerCase().endsWith(".c")) return (formMessage.textContent = "The file must be a .c file.");
  if (file.size === 0 || file.size > MAX_BYTES) {
    return (formMessage.textContent = "The file must not be empty or larger than 100 KB.");
  }

  const body = new FormData();
  body.append("name", name);
  body.append("roll_number", roll);
  body.append("file", file);

  submitBtn.disabled = true;
  try {
    const res = await api(`/api/student/assignments/${encodeURIComponent(selected.id)}/submissions`, {
      method: "POST",
      body,
    });
    fileInput.value = "";
    startTracking(selected.id, res.roll_number, res.attempt);
  } catch (err) {
    formMessage.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
  }
});

// ---------- status tile ----------
function stopTracking() {
  clearInterval(pollTimer);
  pollTimer = null;
  current = null;
}

function startTracking(aid, roll, attempt) {
  stopTracking();
  const me = { aid, roll, attempt, misses: 0 };
  current = me;
  statusSection.hidden = false;
  resultSection.hidden = true;
  renderStatus(me, { state: "queued", message: "Submission received" });
  statusSection.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const tick = async () => {
    try {
      const st = await api(
        `/api/student/assignments/${encodeURIComponent(me.aid)}/submissions/${encodeURIComponent(me.roll)}/status`
      );
      if (current !== me) return;
      me.misses = 0;
      renderStatus(me, st);
      if (st.state === "done" || st.state === "failed") stopTracking();
    } catch (err) {
      if (current !== me) return;
      if (++me.misses >= 5) {
        renderStatus(me, { state: "failed", message: "Lost contact with the server: " + err.message });
        stopTracking();
      }
    }
  };
  pollTimer = setInterval(tick, 1000);
  tick();
}

function renderStatus(sub, st) {
  statusTile.replaceChildren();
  statusTile.append(
    el("h3", null, `Assignment ${sub.aid}`),
    el("p", "meta", `Roll number ${sub.roll} \u00b7 attempt ${sub.attempt}`)
  );

  const idx = ORDER.indexOf(st.state);
  const list = el("ol", "steps");
  for (const [key, label] of STEPS) {
    const li = el("li", null, label);
    if (st.state !== "failed") {
      const stepIdx = ORDER.indexOf(key);
      if (idx > stepIdx) li.className = "done";
      else if (idx === stepIdx) li.className = "active";
    }
    list.appendChild(li);
  }
  statusTile.appendChild(list);

  if (st.steps && st.state !== "done" && st.state !== "failed") {
    const bar = el("div", "progress");
    const fill = el("div", "progress-fill");
    fill.style.width = `${Math.round((100 * (st.step || 0)) / st.steps)}%`;
    bar.appendChild(fill);
    statusTile.appendChild(bar);
  }
  if (st.message) {
    statusTile.appendChild(el("p", st.state === "failed" ? "meta error" : "meta", st.message));
  }
  if (st.state === "done") {
    const base = `/api/student/assignments/${encodeURIComponent(sub.aid)}/submissions/${encodeURIComponent(sub.roll)}`;
    const links = el("div", "tile-actions");
    for (const [fmt, label] of [["txt", "Download report (.txt)"], ["json", "Download report (.json)"]]) {
      const link = el("a", "button-link", label);
      link.href = `${base}/report?format=${fmt}`;
      link.setAttribute("download", "");
      links.appendChild(link);
    }
    statusTile.appendChild(links);
    showResult(sub);
  }
  if (st.state === "done" || st.state === "failed") loadHistory(sub);
}

// ---------- results ----------
const STATUS_LABEL = { ok: "", partial: "partial", skipped: "skipped", unavailable: "not measured", error: "error" };

function preBlock(label, text) {
  const wrap = el("div", "evidence-row");
  wrap.appendChild(el("span", "evidence-label", label));
  const pre = el("pre", null, text === null || text === undefined ? "" : (text || "(empty)"));
  wrap.appendChild(pre);
  return wrap;
}

function failureCard(f, title) {
  const card = el("div", "failure");
  card.appendChild(el("h4", null, title));
  card.appendChild(preBlock("Input", f.input));
  if (f.expected !== null && f.expected !== undefined) card.appendChild(preBlock("Expected", f.expected));
  card.appendChild(preBlock("Got", f.actual));
  card.appendChild(el("p", "meta", "Why: " + f.explanation));
  return card;
}

async function showResult(sub) {
  let rep;
  try {
    rep = await api(`/api/student/assignments/${encodeURIComponent(sub.aid)}/submissions/${encodeURIComponent(sub.roll)}/result`);
  } catch {
    resultSection.hidden = false;
    resultTitle.textContent = "Your grade";
    resultBody.replaceChildren(el("p", "meta",
      "This submission was stored before grading was available, so it has no grade. Submit again or ask your instructor to regrade it."));
    return;
  }
  if (current && current !== sub) return;
  resultSection.hidden = false;
  resultTitle.textContent = `Your grade: ${rep.grade.toFixed(1)} / ${rep.max_grade}` + (rep.provisional ? " (provisional)" : "");
  resultBody.replaceChildren();

  const notes = [];
  if (rep.first_pass.suspected_infinite_loop) notes.push("Your program did not finish on the first test (suspected infinite loop), so the tests that run it were skipped.");
  if (!rep.first_pass.compiled) notes.push("Your program does not compile, so it could not be run.");
  if (rep.flags.includes("originality_review")) notes.push("Your program is very similar to another submission. The instructor will take a look; this is not a finding of copying and did not change your score.");
  if (rep.incomplete_metrics.length) notes.push(`Not measured (counts as 0 until regraded): ${rep.incomplete_metrics.join(", ")}.`);
  for (const n of notes) resultBody.appendChild(el("p", "notice", n));
  if (!rep.first_pass.compiled && rep.first_pass.compiler_output) resultBody.appendChild(preBlock("Compiler", rep.first_pass.compiler_output));

  const table = el("table", "metrics");
  const head = el("tr");
  for (const h of ["Metric", "Weight", "Score", "Verdict"]) head.appendChild(el("th", null, h));
  table.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const m of rep.metrics) {
    const tr = el("tr", m.status === "ok" ? null : "metric-" + m.status);
    const w = m.weight * 100;
    tr.append(
      el("td", null, m.name),
      el("td", null, `${w.toFixed(0)}%`),
      el("td", null, m.score === null ? "-" : `${(m.score * w).toFixed(1)} / ${w.toFixed(0)}`),
      el("td", null, (STATUS_LABEL[m.status] ? `[${STATUS_LABEL[m.status]}] ` : "") + m.feedback)
    );
    body.appendChild(tr);
  }
  table.appendChild(body);
  const wrap = el("div", "table-wrap");
  wrap.appendChild(table);
  resultBody.appendChild(wrap);

  if (rep.failed_tests.length) {
    resultBody.appendChild(el("h3", null, "Where you failed"));
    for (const f of rep.failed_tests) resultBody.appendChild(failureCard(f, `Test ${f.id} (${f.status.replace("_", " ")})`));
  }
  if (rep.counter_tests.length) {
    resultBody.appendChild(el("h3", null, "Edge cases and counter-tests that fail"));
    for (const f of rep.counter_tests) resultBody.appendChild(failureCard(f, `${f.theme}: ${f.reason}`));
  }
  if (rep.suggestions.length) {
    resultBody.appendChild(el("h3", null, "Suggestions"));
    const ul = el("ul");
    for (const s of rep.suggestions) ul.appendChild(el("li", null, s));
    resultBody.appendChild(ul);
  }
}

async function loadHistory(sub) {
  try {
    const rows = await api(`/api/student/assignments/${encodeURIComponent(sub.aid)}/submissions/${encodeURIComponent(sub.roll)}/history`);
    historyBody.replaceChildren();
    for (const h of rows.slice().reverse()) {
      const tr = el("tr");
      tr.append(
        el("td", null, String(h.attempt) + (h.current ? " (latest)" : "")),
        el("td", null, h.submitted_at ? new Date(h.submitted_at).toLocaleString() : ""),
        el("td", null, h.state || ""),
        el("td", null, typeof h.grade === "number" ? h.grade.toFixed(1) : "-")
      );
      historyBody.appendChild(tr);
    }
    historySection.hidden = rows.length === 0;
  } catch {
    historySection.hidden = true;
  }
}

// ---------- check an earlier submission ----------
checkBtn.addEventListener("click", async () => {
  formMessage.textContent = "";
  if (!selected) return;
  const roll = rollInput.value.trim();
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(roll)) return (formMessage.textContent = "Enter your roll number first.");
  try {
    const st = await api(`/api/student/assignments/${encodeURIComponent(selected.id)}/submissions/${encodeURIComponent(roll)}/status`);
    startTracking(selected.id, roll.toUpperCase(), st.attempt);
  } catch {
    formMessage.textContent = "No submission found for this roll number.";
  }
});

window.addEventListener("focus", loadAssignments);
loadAssignments();