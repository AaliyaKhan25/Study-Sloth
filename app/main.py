import os, json, uuid, html, shutil, io
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import FileResponse, HTMLResponse
from . import db, pipeline as pl

app = FastAPI(title="Study Sloth"); db.init()
db.x("update jobs set status='error',message='Interrupted by app restart' where status in ('queued','running')")
UP = "data/uploads"; os.makedirs(UP, exist_ok=True)
pool = ThreadPoolExecutor(max_workers=1)   # one heavy job at a time on a laptop

def save(f: UploadFile):
    path = os.path.join(UP, f"{uuid.uuid4().hex}_{os.path.basename(f.filename)}")
    with open(path, "wb") as o: shutil.copyfileobj(f.file, o)
    return path

def submit(kind, ref, fn, *a):
    jid = db.x("insert into jobs(kind,ref_id,status,progress,message) values(?,?,'queued',0,'Waiting')", (kind, ref))
    def run():
        p = lambda v, m="": db.x("update jobs set status='running',progress=?,message=? where id=?", (v, m, jid))
        try: fn(*a, p); db.x("update jobs set status='done',progress=1,message='Done' where id=?", (jid,))
        except Exception as e: db.x("update jobs set status='error',message=? where id=?", (f"{type(e).__name__}: {e}"[:300], jid))
    pool.submit(run)

def one(sql, args):
    r = db.q(sql, args)
    if not r: raise HTTPException(404)
    return r[0]

@app.get("/")
def home(): return FileResponse("app/static/index.html")

@app.get("/logo.png")
def logo(): return FileResponse("app/static/study-sloth-logo.png", media_type="image/png")

@app.get("/api/subjects")
def subjects(): return db.q("select id,name from subjects order by id desc")

@app.post("/api/subjects")
def new_subject(name: str = Form(...)): return {"id": db.x("insert into subjects(name) values(?)", (name,))}

@app.get("/api/subjects/{sid}")
def subject(sid: int):
    s = one("select * from subjects where id=?", (sid,)); s["units"] = json.loads(s["units"])
    return {"subject": s,
            "lectures": db.q("select id,title,length(transcript) as t from lectures where subject_id=?", (sid,)),
            "pdf_notes": db.q("select n.id,n.title,n.source_name,length(n.notes) as note_chars,coalesce((select j.status from jobs j where j.kind='pdf_notes' and j.ref_id=n.id order by j.id desc limit 1),'done') as status from pdf_notes n where n.subject_id=? order by n.id desc", (sid,)),
            "labs": db.q("select id,title,reviewed from labs where subject_id=?", (sid,)),
            "cards": db.q("select * from cards where subject_id=? order by id", (sid,))}

@app.post("/api/subjects/{sid}/syllabus")
def syllabus(sid: int, text: str = Form(""), file: UploadFile = File(None)):
    if file and file.filename:
        raw = file.file.read()
        if file.filename.lower().endswith(".pdf"):
            from pypdf import PdfReader
            text = "\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(raw)).pages)
        else: text = raw.decode("utf-8", "ignore")
    if not text.strip(): raise HTTPException(400, "Paste the syllabus or upload a .txt/.pdf")
    submit("syllabus", sid, pl.syllabus_job, sid, text); return {"ok": 1}

@app.post("/api/subjects/{sid}/pdf-notes")
def pdf_notes(sid: int, file: UploadFile = File(...), title: str = Form("")):
    one("select id from subjects where id=?", (sid,))
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a PDF to make notes")
    path = save(file)
    note_title = title.strip() or os.path.splitext(os.path.basename(file.filename))[0]
    doc_id = db.x("insert into pdf_notes(subject_id,title,source_name,source_path) values(?,?,?,?)",
                  (sid, note_title, os.path.basename(file.filename), path))
    submit("pdf_notes", doc_id, pl.pdf_notes_job, doc_id, path)
    return {"id": doc_id}

@app.get("/api/pdf-notes/{doc_id}")
def pdf_note_get(doc_id: int):
    return one("select id,title,source_name,notes from pdf_notes where id=?", (doc_id,))

@app.post("/api/subjects/{sid}/lectures")
def lecture(sid: int, title: str = Form(...), file: UploadFile = File(...)):
    lid = db.x("insert into lectures(subject_id,title) values(?,?)", (sid, title))
    path = save(file)
    submit("lecture", lid, pl.pdf_job if path.lower().endswith(".pdf") else pl.lecture_job, lid, path); return {"id": lid}

@app.get("/api/lectures/{lid}")
def lecture_get(lid: int):
    lec = one("select * from lectures where id=?", (lid,))
    return {"title": lec["title"], "notes": pl.notes_view(lec, pl.units_of(lec["subject_id"])), "transcript": lec["transcript"]}

@app.post("/api/lectures/{lid}/board")
def board(lid: int, file: UploadFile = File(...)):
    submit("board", lid, pl.board_job, lid, save(file)); return {"ok": 1}

@app.post("/api/subjects/{sid}/labs")
def lab(sid: int, title: str = Form(...), code: str = Form(...), output: str = Form(""), file: UploadFile = File(None)):
    img = save(file) if file and file.filename else None
    if not output.strip() and not img: raise HTTPException(400, "Add the real output of your run (text or screenshot)")
    lid = db.x("insert into labs(subject_id,title,code,output) values(?,?,?,?)", (sid, title, code, output))
    submit("lab", lid, pl.lab_job, lid, img); return {"id": lid}

@app.get("/api/labs/{lid}")
def lab_get(lid: int):
    l = one("select * from labs where id=?", (lid,)); l["record"] = json.loads(l["record"]); return l

@app.post("/api/labs/{lid}/review")
def review(lid: int, b: dict = Body(...)):
    if not b.get("confirmed"): raise HTTPException(400, "Confirm the output is from your own run first")
    db.x("update labs set record=?, code=?, output=?, reviewed=1 where id=?", (json.dumps(b["record"]), b["code"], b["output"], lid))
    return {"ok": 1}

@app.get("/labs/{lid}/print", response_class=HTMLResponse)
def lab_print(lid: int):
    l = one("select * from labs where id=?", (lid,))
    if not l["reviewed"]: raise HTTPException(409, "Review the record before exporting")
    r = json.loads(l["record"]); e = html.escape
    steps = "".join(f"<li>{e(s)}</li>" for s in r["procedure"].splitlines() if s.strip())
    return f"""<!doctype html><meta charset=utf-8><title>{e(l['title'])}</title>
<style>body{{font:14px/1.6 Georgia,serif;max-width:760px;margin:2rem auto;padding:0 1rem}}h1{{font-size:1.4rem}}h2{{font-size:1.05rem;margin-top:1.6rem;border-bottom:1px solid #999}}
pre{{background:#f4f4f4;padding:.7rem;white-space:pre-wrap;font-size:12px}}p{{white-space:pre-wrap}}button{{margin-bottom:1rem}}@media print{{button{{display:none}}}}</style>
<button onclick="print()">Print / Save as PDF</button><h1>{e(l['title'])}</h1>
<h2>Aim</h2><p>{e(r['aim'])}</p><h2>Theory</h2><p>{e(r['theory'])}</p><h2>Procedure</h2><ol>{steps}</ol>
<h2>Code</h2><pre>{e(l['code'])}</pre><h2>Output</h2><pre>{e(l['output'])}</pre><h2>Conclusion</h2><p>{e(r['conclusion'])}</p>"""

@app.get("/api/jobs")
def jobs(): return db.q("select * from jobs order by id desc limit 8")
