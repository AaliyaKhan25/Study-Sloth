/* Study Sloth online demo: answers the app's /api calls with sample data, so the real UI works in a browser with no server.
   Nothing is uploaded or processed here. */
(function () {
  const realFetch = window.fetch.bind(window), realOpen = window.open.bind(window);
  const units = [
    { name: "Unit 1: ER model and keys", topics: ["Entities", "Primary keys", "Foreign keys"] },
    { name: "Unit 2: Relational algebra and SQL", topics: ["Joins", "Subqueries", "Aggregates"] },
    { name: "Unit 3: Normalization", topics: ["1NF", "2NF", "3NF", "BCNF"] }];
  const DB = {
    subjects: [{ id: 1, name: "DBMS (sample)" }],
    lectures: [{ id: 1, title: "Joins and subqueries", t: 1 }],
    pdf: [{ id: 1, title: "Python ecosystem notes", source_name: "python-ecosystem.pdf", note_chars: 900, status: "done" }],
    labs: [{ id: 1, title: "Experiment 4: LEFT JOIN on two tables", reviewed: 0 }],
    cards: [
      { id: 1, kind: "flash", q: "What does INNER JOIN return?", a: "Only the rows that have matching values in both tables." },
      { id: 2, kind: "flash", q: "What does LEFT JOIN add compared with INNER JOIN?", a: "Every row of the left table, with NULLs where the right table has no match." },
      { id: 3, kind: "flash", q: "When is a table in 2NF?", a: "When it is in 1NF and no non-key column depends on only part of the primary key." },
      { id: 4, kind: "quiz", q: "Which join keeps unmatched rows from the left table?", a: "", extra: JSON.stringify({ options: ["INNER JOIN", "LEFT JOIN", "CROSS JOIN", "SELF JOIN"], answer: 1 }) },
      { id: 5, kind: "viva", q: "Why did this query use a LEFT JOIN?", a: "Because we wanted every student in the result, including students who are not enrolled in any course yet.", lab_id: 1 },
      { id: 6, kind: "viva", q: "What is the difference between WHERE and HAVING?", a: "WHERE filters rows before grouping; HAVING filters groups after aggregation." }],
    lec: { title: "Joins and subqueries", transcript: "(sample)", notes: [
      { unit: units[1].name, points: [
        { heading: "INNER JOIN", ts: "02:10", text: "Returns only rows with a match in both tables; unmatched rows are dropped." },
        { heading: "LEFT JOIN", ts: "05:40", text: "Keeps every row of the left table and fills the right side with NULL when there is no match." },
        { heading: "Subquery in WHERE", ts: "11:05", text: "A nested SELECT whose result is used as a condition in the outer query." }],
        board: [{ title: "Join types", markdown: "INNER JOIN: A ∩ B\nLEFT JOIN: A + (A ∩ B)\n[diagram: two overlapping circles, left one shaded]" }] },
      { unit: units[2].name, points: [{ heading: "Why normalize", ts: "18:30", text: "To reduce redundancy and avoid update anomalies." }], board: [] }] },
    pdfNotes: "## Web development [p.1]\n- Django: full-stack framework, batteries included\n- Flask: lightweight microframework\n- FastAPI: async, automatic API docs\n\n## Data science [p.1]\n- NumPy: arrays and linear algebra\n- Pandas: dataframes, CSV and Excel\n- Matplotlib / Seaborn / Plotly: plotting\n\n## Machine learning [p.2]\n- scikit-learn: core machine learning\n- PyTorch / TensorFlow: deep learning\n- Transformers: BERT/GPT-style models\n\n(Sample notes. The real app writes these from your own PDF, a few pages at a time.)",
    lab: { id: 1, title: "Experiment 4: LEFT JOIN on two tables",
      code: "SELECT s.name, c.title\nFROM students s\nLEFT JOIN enrollments e ON s.id = e.student_id\nLEFT JOIN courses c ON c.id = e.course_id;",
      output: "name   | title\n-------+--------\nAsha   | DBMS\nRavi   | Networks\nMeera  | NULL",
      output_note: "Sample data for the demo. In the real app this is the output you paste or photograph from your own run.",
      reviewed: 0,
      record: { aim: "To retrieve all students together with their courses using LEFT JOIN.",
        theory: "A LEFT JOIN returns every row of the left table and the matching rows of the right table; unmatched right-hand columns are NULL (from lecture 'Joins and subqueries' @ 05:40).",
        procedure: "Create the students, enrollments and courses tables\nInsert sample rows\nRun the LEFT JOIN query\nObserve the rows returned",
        conclusion: "The output lists every student; Meera has no course, so her title is NULL.",
        sources: ["Joins and subqueries @ 05:40"] } } };
  const J = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const off = () => J({ detail: "Uploads are turned off in this online demo. Run Study Sloth on your laptop to process your own files." }, 400);
  window.fetch = async function (url, opts = {}) {
    if (typeof url !== "string" || !url.startsWith("/api")) return realFetch(url, opts);
    const p = url.slice(4).split("?")[0], post = (opts.method || "GET").toUpperCase() === "POST";
    let m;
    if (p === "/jobs") return J([]);
    if (p === "/subjects" && !post) return J([...DB.subjects].reverse());
    if (p === "/subjects" && post) {
      const name = String(opts.body.get("name") || "").trim() || "New subject";
      const s = { id: DB.subjects.length + 1, name }; DB.subjects.push(s); return J({ id: s.id });
    }
    if ((m = p.match(/^\/subjects\/(\d+)$/))) {
      const id = +m[1], s = DB.subjects.find(x => x.id === id); if (!s) return J({ detail: "Not found" }, 404);
      const sample = id === 1;
      return J({ subject: { id, name: s.name, syllabus: "", units: sample ? units : [] },
        lectures: sample ? DB.lectures : [], pdf_notes: sample ? DB.pdf : [], labs: sample ? DB.labs : [], cards: sample ? DB.cards : [] });
    }
    if (post && /^\/(subjects\/\d+\/(syllabus|lectures|pdf-notes|labs)|lectures\/\d+\/board)$/.test(p)) return off();
    if (/^\/lectures\/\d+$/.test(p)) return J(DB.lec);
    if (/^\/pdf-notes\/\d+$/.test(p)) return J({ notes: DB.pdfNotes });
    if (/^\/labs\/\d+$/.test(p)) return J(DB.lab);
    if (/^\/labs\/\d+\/review$/.test(p) && post) {
      const b = JSON.parse(opts.body); if (!b.confirmed) return J({ detail: "Confirm the output is from your own run first" }, 400);
      DB.lab.record = b.record; DB.lab.code = b.code; DB.lab.output = b.output; DB.lab.reviewed = 1; DB.labs[0].reviewed = 1; return J({ ok: 1 });
    }
    return J({ detail: "Not available in the demo" }, 404);
  };
  window.open = function (u, ...r) {
    if (/^\/labs\/\d+\/print/.test(u || "")) {
      const e = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])), L = DB.lab, R = L.record;
      const steps = R.procedure.split("\n").filter(Boolean).map(s => "<li>" + e(s) + "</li>").join("");
      const html = `<!doctype html><meta charset=utf-8><title>${e(L.title)}</title><style>body{font:14px/1.6 Georgia,serif;max-width:760px;margin:2rem auto;padding:0 1rem}h2{border-bottom:1px solid #999;font-size:1.05rem;margin-top:1.5rem}pre{background:#f4f4f4;padding:.7rem;white-space:pre-wrap}p{white-space:pre-wrap}@media print{button{display:none}}</style><button onclick="print()">Print / Save as PDF</button><p><i>Sample record from the online demo.</i></p><h1>${e(L.title)}</h1><h2>Aim</h2><p>${e(R.aim)}</p><h2>Theory</h2><p>${e(R.theory)}</p><h2>Procedure</h2><ol>${steps}</ol><h2>Code</h2><pre>${e(L.code)}</pre><h2>Output</h2><pre>${e(L.output)}</pre><h2>Conclusion</h2><p>${e(R.conclusion)}</p>`;
      return realOpen(URL.createObjectURL(new Blob([html], { type: "text/html" })), ...r);
    }
    return realOpen(u, ...r);
  };
  window.addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.setAttribute("role", "note");
    b.style.cssText = "position:fixed;right:14px;bottom:14px;z-index:30;max-width:min(92vw,430px);padding:10px 14px;border-radius:14px;background:#203e32;color:#f8f6ec;font:13px/1.45 system-ui,sans-serif;box-shadow:0 10px 28px rgba(0,0,0,.25)";
    b.innerHTML = 'Online demo with <b>sample data</b>. Uploads are off. The real app runs on your laptop with local open models. <a style="color:#edc763" href="about.html">About</a> · <a style="color:#edc763" href="https://github.com/AaliyaKhan25/Study-Sloth">GitHub</a>';
    document.body.appendChild(b);
  });
  window.addEventListener("load", () => setTimeout(() => { const s = document.querySelector(".subject-btn"); if (s) s.click(); }, 400));
})();