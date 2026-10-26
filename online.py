"""Study Sloth Online: upload notes, get a summary, notes by topic, flashcards, quiz and viva questions.
Nothing is stored on disk. Start:  python -m uvicorn online:app --port 8000
Model: local Ollama by default; set OLLAMA_HOST=https://ollama.com and OLLAMA_API_KEY for Ollama Cloud."""
import os, io, time, uuid, threading, collections
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.llm import chat_json
from app.pdf_ocr import extract_pdf_pages

MAX_PAGES = int(os.environ.get("SLOTH_MAX_PAGES", 30))
MAX_CHARS = 120_000
PER_IP_HOUR = int(os.environ.get("SLOTH_PER_IP_HOUR", 6))      # uploads per visitor per hour
PER_DAY = int(os.environ.get("SLOTH_PER_DAY", 200))             # uploads per day in total, protects your quota
SYS = "You are a careful study assistant. Use ONLY the material given. If something is unclear, say so instead of guessing."
POINTS = ('These are pages from a student\'s notes. Extract every teaching point. Keep every named item (tools, terms, formulas, steps) and do not skip or merge items. '
          'Return JSON: {"points":[{"topic":"short section name","heading":"short","text":"1-2 sentences","ref":"page such as p.3, or the part label"}]}\n\n')
CARDS = ('From these notes make study material. Return JSON: {"flashcards":[{"q":"","a":""}] (8), "quiz":[{"q":"","options":["","","",""],"answer":0}] (5, answer is the option index), "viva":[{"q":"","a":""}] (5)}\n\n')

app = FastAPI(title="Study Sloth Online")
pool = ThreadPoolExecutor(max_workers=2)
JOBS, HITS, DAY, lock = {}, collections.defaultdict(list), [0, time.time()], threading.Lock()

def allow(ip):
    now = time.time()
    with lock:
        if now - DAY[1] > 86400: DAY[0], DAY[1] = 0, now
        HITS[ip] = [t for t in HITS[ip] if now - t < 3600]
        if len(HITS[ip]) >= PER_IP_HOUR or DAY[0] >= PER_DAY: return False
        HITS[ip].append(now); DAY[0] += 1
        for k in [k for k, v in JOBS.items() if now - v["t"] > 3600]: JOBS.pop(k, None)   # forget old results
        return True

def pieces_of(raw, name, text):
    """Return text chunks, or PDF bytes for OCR in the background worker."""
    if not text.strip() and name.lower().endswith(".pdf"):
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(raw)); n = len(rd.pages)
        return raw, n
    body = (text.strip() or raw.decode("utf-8", "ignore"))[:MAX_CHARS]
    return [(f"part {i + 1}", body[k:k + 3000]) for i, k in enumerate(range(0, len(body), 3000))], 0

def blocks_of(pieces, size=3500):
    cur, n = [], 0
    for label, t in pieces:
        if not t: continue
        if n + len(t) > size and cur: yield "\n".join(cur); cur, n = [], 0
        cur.append(f"[{label}]\n{t}"); n += len(t)
    if cur: yield "\n".join(cur)

def strs(xs, keys):
    return [{k: str(x.get(k, "")) for k in keys} for x in xs if isinstance(x, dict) and x.get(keys[0])]

def work(jid, pieces, pages, name):
    j = JOBS[jid]
    try:
        if name.lower().endswith(".pdf"):
            def report_ocr(completed, total, page):
                j.update(
                    progress=0.05 + 0.2 * completed / total,
                    message=f"Reading scanned PDF page {page} with OCR",
                )
            pdf_pages, pages, _ = extract_pdf_pages(
                pieces, max_pages=MAX_PAGES, progress=report_ocr
            )
            pieces = [(f"p.{number}", text) for number, text in pdf_pages]
        bl = list(blocks_of(pieces)); pts = []
        for i, b in enumerate(bl):
            j.update(progress=0.1 + 0.6 * i / max(len(bl), 1), message=f"Reading part {i + 1} of {len(bl)}")
            pts += strs(chat_json(POINTS + b, system=SYS).get("points", []), ["text", "topic", "heading", "ref"])
        if not pts: raise RuntimeError("No readable text was found in this file.")
        notes = "\n".join(f"{p['topic']}: {p['text']}" for p in pts)[:6000]
        j.update(progress=0.75, message="Writing the summary")
        s = chat_json('Summarise these notes as 5 to 7 short bullet strings. Return JSON: {"summary":["..."]}\n\n' + notes, system=SYS).get("summary", [])
        j.update(progress=0.88, message="Making flashcards and questions")
        c = chat_json(CARDS + notes, system=SYS)
        quiz = [{"q": str(x["q"]), "options": [str(o) for o in x.get("options", [])], "answer": x.get("answer", 0)}
                for x in c.get("quiz", []) if isinstance(x, dict) and x.get("q")]
        j.update(status="done", progress=1, message="Done", result={
            "name": name, "summary": [str(x) for x in s], "points": pts, "quiz": quiz,
            "flashcards": strs(c.get("flashcards", []), ["q", "a"]), "viva": strs(c.get("viva", []), ["q", "a"]),
            "note": f"Only the first {MAX_PAGES} of {pages} pages were used." if pages > MAX_PAGES else ""})
    except Exception as e:
        j.update(status="error", message=f"{type(e).__name__}: {e}"[:300])

@app.post("/api/study")
async def study(request: Request, file: UploadFile = File(None), text: str = Form("")):
    raw = await file.read() if file and file.filename else b""
    if not raw and not text.strip(): return JSONResponse({"detail": "Choose a PDF or paste some text first."}, 400)
    if len(raw) > 10_000_000: return JSONResponse({"detail": "File too large (10 MB limit)."}, 400)
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?"))
    if not allow(ip): return JSONResponse({"detail": "Limit reached for now (a few uploads per hour). Please try again later."}, 429)
    name = file.filename if file and file.filename else "Pasted text"
    try: pieces, pages = pieces_of(raw, name, text)
    except Exception: return JSONResponse({"detail": "Could not read that file. Try a text-based PDF or .txt."}, 400)
    jid = uuid.uuid4().hex
    JOBS[jid] = {"status": "running", "progress": 0.05, "message": "Starting", "result": None, "t": time.time()}
    pool.submit(work, jid, pieces, pages, name)
    return {"id": jid}

@app.get("/api/study/{jid}")
def result(jid: str):
    j = JOBS.get(jid)
    if not j: return JSONResponse({"detail": "Result expired. Please upload again."}, 404)
    return {k: j[k] for k in ("status", "progress", "message", "result")}

app.mount("/", StaticFiles(directory="online", html=True), name="site")
