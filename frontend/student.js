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

  if (st.message) {
    statusTile.appendChild(el("p", st.state === "failed" ? "meta error" : "meta", st.message));
  }
  if (st.state === "done") {
    const link = el("a", "button-link", "Download report");
    link.href = `/api/student/assignments/${encodeURIComponent(sub.aid)}/submissions/${encodeURIComponent(sub.roll)}/report`;
    link.setAttribute("download", "");
    statusTile.appendChild(link);
  }
}

window.addEventListener("focus", loadAssignments);
loadAssignments();