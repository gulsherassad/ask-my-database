/* ============================================================
   Querybird frontend logic
   Talks to the FastAPI backend:
     GET  /api/databases  -> { databases: ["financial", ...] }
     POST /api/query      -> { sql, columns, rows, row_count, elapsed_ms, error? }
   Degrades gracefully to a baked demo if the backend isn't running,
   so the page still looks alive when opened as a static file.
   ============================================================ */

const els = {
  db: document.getElementById("db-select"),
  question: document.getElementById("question"),
  chips: document.getElementById("chips"),
  run: document.getElementById("run"),
  machine: document.getElementById("machine"),
  sql: document.getElementById("sql"),
  copy: document.getElementById("copy-sql"),
  resultFrame: document.getElementById("result-frame"),
  resultMeta: document.getElementById("result-meta"),
  emptyState: document.getElementById("empty-state"),
  repoLink: document.getElementById("repo-link"),
};

// Point this at your repo once it's public.
els.repoLink.setAttribute("href", "https://github.com/gulsherassad");

// Example questions per database — clickable starters so a demo is never a blank box.
const EXAMPLES = {
  financial: [
    "How many accounts were opened in 1995?",
    "What is the average loan amount?",
  ],
  debit_card_specializing: [
    "What is the ratio of customers who pay in EUR versus CZK?",
    "How many customers are in the LAM segment?",
  ],
  formula_1: [
    "Which driver has the most race wins?",
    "How many races were held in 2010?",
  ],
  california_schools: [
    "How many schools are in Los Angeles county?",
    "What is the highest average math SAT score?",
  ],
  superhero: [
    "How many superheroes have blue eyes?",
    "Which publisher has the most superheroes?",
  ],
  card_games: ["How many cards are legal in commander format?"],
  european_football_2: ["How many teams are in the database?"],
  student_club: ["How many members are in the student club?"],
  toxicology: ["How many molecules are labeled as carcinogenic?"],
  thrombosis_prediction: ["How many patients are female?"],
  codebase_community: ["How many posts have a score above 100?"],
};

const FALLBACK_DBS = Object.keys(EXAMPLES);

/* ---------- SQL syntax highlighting ---------- */
const KEYWORDS = new Set(("select from where group by order having limit distinct " +
  "inner left right outer join on as and or not in is null like between " +
  "count sum avg min max cast asc desc union all case when then else end " +
  "exists having offset").split(" "));
const FUNCS = new Set("count sum avg min max cast substr strftime round abs coalesce iif length".split(" "));

function escapeHtml(s) {
  return s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function highlightSql(sql) {
  // Tokenize: strings, numbers, words, punctuation. Escape as we build.
  const tokenRe = /('(?:[^']|'')*')|(\b\d+\.?\d*\b)|([A-Za-z_][A-Za-z0-9_]*)|([(),.*=<>!/+\-]+)/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = tokenRe.exec(sql)) !== null) {
    out += escapeHtml(sql.slice(last, m.index));
    last = tokenRe.lastIndex;
    if (m[1]) {
      out += `<span class="tok-str">${escapeHtml(m[1])}</span>`;
    } else if (m[2]) {
      out += `<span class="tok-num">${escapeHtml(m[2])}</span>`;
    } else if (m[3]) {
      const lower = m[3].toLowerCase();
      const cls = KEYWORDS.has(lower) ? "tok-kw" : (FUNCS.has(lower) ? "tok-fn" : "");
      out += cls ? `<span class="${cls}">${escapeHtml(m[3])}</span>` : escapeHtml(m[3]);
    } else if (m[4]) {
      out += `<span class="tok-punc">${escapeHtml(m[4])}</span>`;
    }
  }
  out += escapeHtml(sql.slice(last));
  return out;
}

/* ---------- rendering ---------- */
function renderExamples(dbId) {
  const list = EXAMPLES[dbId] || [];
  els.chips.innerHTML = "";
  list.forEach(q => {
    const b = document.createElement("button");
    b.className = "chip";
    b.type = "button";
    b.textContent = q;
    b.addEventListener("click", () => { els.question.value = q; els.question.focus(); });
    els.chips.appendChild(b);
  });
}

function isNumeric(v) {
  return typeof v === "number" || (typeof v === "string" && v !== "" && !isNaN(v));
}

function renderResult(data) {
  const { columns = [], rows = [], row_count, elapsed_ms } = data;
  els.resultMeta.textContent =
    `${row_count ?? rows.length} row${(row_count ?? rows.length) === 1 ? "" : "s"}` +
    (elapsed_ms != null ? ` · ${elapsed_ms} ms` : "");

  if (!rows.length) {
    els.resultFrame.innerHTML = `<div class="empty">Query ran and returned no rows.</div>`;
    return;
  }

  const thead = `<tr>${columns.map(c => `<th>${escapeHtml(String(c))}</th>`).join("")}</tr>`;
  const body = rows.map(r => {
    const cells = columns.map((_, i) => {
      const v = r[i];
      const cls = isNumeric(v) ? ' class="num"' : "";
      return `<td${cls}>${escapeHtml(v === null ? "NULL" : String(v))}</td>`;
    }).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  els.resultFrame.innerHTML =
    `<table class="grid"><thead>${thead}</thead><tbody>${body}</tbody></table>`;
  els.resultFrame.classList.add("reveal");
}

function showSql(sql) {
  els.sql.innerHTML = `<code>${highlightSql(sql)}</code>`;
  els.copy.hidden = false;
  els.sql.parentElement.classList.add("reveal");
}

function showError(message) {
  els.resultFrame.innerHTML =
    `<div class="error"><strong>Couldn't run that.</strong> ${escapeHtml(message)}</div>`;
}

/* ---------- run a query ---------- */
async function runQuery() {
  const question = els.question.value.trim();
  const database = els.db.value;
  if (!question) { els.question.focus(); return; }

  els.run.disabled = true;
  els.machine.classList.add("is-loading");
  els.copy.hidden = true;
  els.resultMeta.textContent = "";
  els.resultFrame.innerHTML = `<div class="empty">Running…</div>`;

  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, database }),
    });
    const data = await res.json();
    els.machine.classList.remove("is-loading");

    if (data.sql) showSql(data.sql);

    if (data.error) {
      showError(data.error);
    } else {
      renderResult(data);
    }
  } catch (err) {
    els.machine.classList.remove("is-loading");
    // Backend not reachable — show a clear message, not a broken page.
    els.sql.innerHTML = `<code class="sql-placeholder">— backend not connected</code>`;
    showError("The backend isn't running. Start it with: uvicorn server:app --reload");
  } finally {
    els.run.disabled = false;
  }
}

/* ---------- init ---------- */
async function loadDatabases() {
  let dbs = FALLBACK_DBS;
  try {
    const res = await fetch("/api/databases");
    const data = await res.json();
    if (data && Array.isArray(data.databases) && data.databases.length) {
      dbs = data.databases;
    }
  } catch (_) { /* use fallback list */ }

  els.db.innerHTML = "";
  dbs.forEach(d => {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d.replace(/_/g, " ");
    els.db.appendChild(opt);
  });
  renderExamples(els.db.value);
}

els.db.addEventListener("change", () => renderExamples(els.db.value));
els.run.addEventListener("click", runQuery);
els.question.addEventListener("keydown", (e) => {
  // Cmd/Ctrl+Enter or plain Enter (without shift) submits.
  if ((e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); runQuery(); }
});
els.copy.addEventListener("click", async () => {
  const text = els.sql.textContent;
  try { await navigator.clipboard.writeText(text); els.copy.textContent = "copied"; }
  catch (_) { els.copy.textContent = "copy failed"; }
  setTimeout(() => (els.copy.textContent = "copy"), 1400);
});

loadDatabases();
