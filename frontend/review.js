const aid = new URLSearchParams(location.search).get("id");

const headingEl = document.getElementById("heading");
const statusEl = document.getElementById("status");
const regenBtn = document.getElementById("regen");
const acceptBtn = document.getElementById("accept");
const tbody = document.querySelector("#tests tbody");

let pollTimer = null;
let testCount = 0;
let locked = false; // true when the assignment is already published

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

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function updateButtons(busy) {
  regenBtn.disabled = busy || locked;
  acceptBtn.disabled = busy || locked || testCount === 0;
}

function cell(text, mono) {
  const td = document.createElement("td");
  if (mono) {
    const pre = document.createElement("pre");
    pre.textContent = text;
    td.appendChild(pre);
  } else {
    td.textContent = text;
  }
  return td;
}

function renderTests(tests) {
  tbody.replaceChildren();
  testCount = tests.length;
  for (const t of tests) {
    const tr = document.createElement("tr");
    tr.append(
      cell(t.id, false),
      cell(t.input, true),
      cell(t.expected_output, true),
      cell(t.category, false),
      cell(t.explanation, false)
    );
    tbody.appendChild(tr);
  }
}

async function showResult(meta, tests) {
  tests = tests || (await api(`/api/assignments/${aid}/tests`));
  renderTests(tests);
  const gen = meta.generation || {};
  if (gen.state === "failed") {
    setStatus("Generation failed: " + gen.message, true);
  } else {
    setStatus(`${tests.length} test cases. ${gen.message || ""}`.trim());
  }
  if (locked) setStatus("This assignment is published, so its test cases are read-only.");
  updateButtons(false);
}

function startPolling() {
  updateButtons(true);
  setStatus("Generating test cases... this can take a minute or two.");
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const meta = await api(`/api/assignments/${aid}`);
      if (meta.generation && meta.generation.state === "running") return;
      clearInterval(pollTimer);
      await showResult(meta);
    } catch (err) {
      clearInterval(pollTimer);
      setStatus("Lost contact with the server: " + err.message, true);
      updateButtons(false);
    }
  }, 2000);
}

async function generate() {
  renderTests([]);
  updateButtons(true);
  try {
    await api(`/api/assignments/${aid}/generate-tests`, { method: "POST" });
  } catch (err) {
    // "already running" just means another window started it: keep polling
    if (!/already running/.test(err.message)) {
      setStatus(err.message, true);
      updateButtons(false);
      return;
    }
  }
  startPolling();
}

async function init() {
  if (!aid) {
    setStatus("No assignment id in the address.", true);
    updateButtons(true);
    return;
  }
  try {
    const meta = await api(`/api/assignments/${aid}`);
    headingEl.textContent = `Validate test cases: ${meta.title} (${meta.id})`;
    locked = meta.status !== "draft";
    const gen = meta.generation || {};

    if (gen.state === "running") {
      startPolling();
      return;
    }
    const tests = await api(`/api/assignments/${aid}/tests`);
    if (tests.length === 0 && !gen.state && !locked) {
      await generate(); // first visit: generate automatically
      return;
    }
    await showResult(meta, tests);
  } catch (err) {
    setStatus(err.message, true);
    updateButtons(true);
  }
}

regenBtn.addEventListener("click", generate);

acceptBtn.addEventListener("click", async () => {
  updateButtons(true);
  try {
    await api(`/api/assignments/${aid}/accept-tests`, { method: "POST" });
  } catch (err) {
    setStatus(err.message, true);
    updateButtons(false);
    return;
  }
  // Close this window if the main page opened it; otherwise go back to the main page.
  if (window.opener && !window.opener.closed) {
    window.close();
    setTimeout(() => { location.href = "/"; }, 300);
  } else {
    location.href = "/";
  }
});

init();