const form = document.getElementById("assignment-form");
const messageEl = document.getElementById("form-message");
const tilesEl = document.getElementById("tiles");
const statementEl = document.getElementById("statement");

// ---------- API helper ----------
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

// ---------- helpers ----------
function validatePolicy(policy) {
  if (!policy || !Array.isArray(policy.metrics) || policy.metrics.length === 0) {
    return "Policy must contain a non-empty \"metrics\" array.";
  }
  let total = 0;
  for (const m of policy.metrics) {
    if (!m.name || !m.analyzer) {
      return "Every metric needs a \"name\" and an \"analyzer\".";
    }
    if (typeof m.weight !== "number" || m.weight < 0 || m.weight > 1) {
      return `Metric "${m.name}" needs a weight between 0 and 1.`;
    }
    total += m.weight;
  }
  if (Math.abs(total - 1) > 0.001) {
    return `Weights must sum to 1.00 (currently ${total.toFixed(2)}).`;
  }
  return null;
}

function showMessage(text) {
  messageEl.textContent = text;
}

// ---------- rendering ----------
function renderTiles(list) {
  tilesEl.replaceChildren();

  if (list.length === 0) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "No assignments yet.";
    tilesEl.appendChild(p);
    return;
  }

  for (const a of list) {
    const tile = document.createElement("div");
    tile.className = "tile " + (a.status === "published" ? "published" : "draft");

    const title = document.createElement("h3");
    title.textContent = a.title;

    const id = document.createElement("p");
    id.className = "meta";
    id.append("ID: ");
    const idCode = document.createElement("span");
    idCode.className = "id";
    idCode.textContent = a.id;
    id.appendChild(idCode);

    const tests = document.createElement("p");
    tests.className = "meta";
    tests.textContent = `${a.num_tests} test cases requested`;

    const created = document.createElement("p");
    created.className = "meta";
    created.textContent = "Created " + new Date(a.created_at).toLocaleString();

    const status = document.createElement("p");
    status.className = "status";
    status.textContent = a.status === "published" ? "PUBLISHED" : "DRAFT";

    tile.append(title, id, tests, created, status);

      if (a.status === "draft") {
      const note = document.createElement("p");
      note.className = "meta";
      note.textContent = a.tests_accepted ? "Test cases accepted" : "Test cases not validated yet";
      tile.appendChild(note);

      const actions = document.createElement("div");
      actions.className = "tile-actions";

      const validateBtn = document.createElement("button");
      validateBtn.type = "button";
      validateBtn.className = "secondary";
      validateBtn.textContent = "Validate test cases";
      validateBtn.addEventListener("click", () => {
        window.open(`/review.html?id=${encodeURIComponent(a.id)}`, "_blank");
      });

      const publishBtn = document.createElement("button");
      publishBtn.type = "button";
      publishBtn.textContent = "Publish";
      publishBtn.disabled = !a.tests_accepted;
      publishBtn.title = a.tests_accepted ? "" : "Validate and accept the test cases first";
      publishBtn.addEventListener("click", async () => {
        try {
          await api(`/api/assignments/${a.id}/publish`, { method: "POST" });
          await refreshTiles();
        } catch (err) {
          showMessage(err.message);
        }
      });

      actions.append(validateBtn, publishBtn);
      tile.appendChild(actions);
    }

    tilesEl.appendChild(tile);
  }
}

async function refreshTiles() {
  try {
    renderTiles(await api("/api/assignments"));
  } catch (err) {
    showMessage("Could not load assignments: " + err.message);
  }
}

// ---------- events ----------
document.getElementById("statement-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (file) statementEl.value = await file.text();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  showMessage("");

  const title = document.getElementById("title").value.trim();
  const statement = statementEl.value.trim();
  const policyFile = document.getElementById("policy-file").files[0];
  const numTests = parseInt(document.getElementById("num-tests").value, 10);

  if (!title) return showMessage("Please enter a title.");
  if (!statement) return showMessage("Please provide a problem statement.");
  if (!policyFile) return showMessage("Please upload the grading policy (.json).");
  if (!Number.isInteger(numTests) || numTests < 5 || numTests > 100) {
    return showMessage("Number of test cases must be between 5 and 100.");
  }

  let policy;
  try {
    policy = JSON.parse(await policyFile.text());
  } catch {
    return showMessage("The policy file is not valid JSON.");
  }
  const policyError = validatePolicy(policy);
  if (policyError) return showMessage(policyError);

  try {
    await api("/api/assignments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, statement, policy, num_tests: numTests }),
    });
    form.reset();
    await refreshTiles();
  } catch (err) {
    showMessage("Could not create assignment: " + err.message);
  }
});

refreshTiles();
window.addEventListener("focus", refreshTiles);