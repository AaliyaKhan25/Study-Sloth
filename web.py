"""Hosted entry point: your real UI and API, with a private workspace per visitor, usage limits and honest labels.
Start:  python -m uvicorn web:app --host 0.0.0.0 --port $PORT      (no password needed)"""
import os, re, uuid, time, shutil, sqlite3, threading, collections, contextvars
import concurrent.futures as cf

os.environ.setdefault("SLOTH_DB", "data/hosted/template.db")      # keeps hosted data apart from your own notes

# Background jobs must run inside the visitor's workspace, so copy the context into worker threads.
_orig_submit = cf.ThreadPoolExecutor.submit
def _submit(self, fn, *a, **k):
    return _orig_submit(self, contextvars.copy_context().run, fn, *a, **k)
cf.ThreadPoolExecutor.submit = _submit

from fastapi import Request
from fastapi.responses import Response, JSONResponse
from app import db
from app.main import app

WS = contextvars.ContextVar("ws", default="")
TEMPLATE = os.path.abspath(db.DB)
WSDIR = os.path.join(os.path.dirname(TEMPLATE), "workspaces"); os.makedirs(WSDIR, exist_ok=True)
lock = threading.Lock()

def _conn():
    ws = WS.get()
    path = os.path.join(WSDIR, ws + ".db") if ws else TEMPLATE
    if ws and not os.path.exists(path):
        with lock:
            if not os.path.exists(path): shutil.copyfile(TEMPLATE, path)   # a new visitor starts with an empty copy
    c = sqlite3.connect(path, check_same_thread=False); c.row_factory = sqlite3.Row
    return c
db.conn = _conn

PER_HOUR = int(os.environ.get("SLOTH_UPLOADS_PER_HOUR", 8))     # per visitor
PER_DAY = int(os.environ.get("SLOTH_UPLOADS_PER_DAY", 250))     # in total, protects your model quota
HITS, DAY = collections.defaultdict(list), [0, time.time()]
UPLOAD = re.compile(r"^/api/(subjects/\d+/(syllabus|lectures|pdf-notes|labs)|lectures/\d+/board)$")

def allowed(ip):
    now = time.time()
    with lock:
        if now - DAY[1] > 86400: DAY[0], DAY[1] = 0, now
        HITS[ip] = [t for t in HITS[ip] if now - t < 3600]
        if len(HITS[ip]) >= PER_HOUR or DAY[0] >= PER_DAY: return False
        HITS[ip].append(now); DAY[0] += 1; return True

LABELS = {   # the page says "local"; the hosted version is not, so say what really happens
    "Local AI · your device": "Hosted demo · open model",
    "Everything runs locally": "Open models, nothing to install",
    "Private by design": "Hosted demo",
    "Local workspace · just for you": "Your own private workspace",
    "On-device processing": "Processed by an open model (Ollama Cloud)",
    "Audio stays on this computer": "Lecture audio is processed on the hosted server",
    "PDF stays on this computer": "PDF text is sent to Ollama Cloud",
    "Parsed and organized locally": "Processed by an open model (Ollama Cloud)",
    "Local model · your code is never generated": "Your code and output are never generated",
    "Powered locally on your computer": "Open-source models via Ollama Cloud",
    "Your local models will handle the busywork.": "An open model will handle the busywork.",
    "all from your own computer": "with nothing to install",
    "Turn a lecture into notes": "Turn a lecture into notes"}

def relabel(html):
    i, j = html.lower().find("<html"), html.lower().rfind("</html>")
    if i >= 0 and j > i: html = "<!doctype html>\n" + html[i:j + 7]      # drops stray text before and after the page
    for a, b in LABELS.items(): html = html.replace(a, b)
    return html

@app.middleware("http")
async def hosted(request: Request, call_next):
    ws = request.cookies.get("sloth_ws", "")
    fresh = not re.fullmatch(r"[0-9a-f]{32}", ws)
    if fresh: ws = uuid.uuid4().hex
    token = WS.set(ws)
    try:
        if request.method == "POST" and UPLOAD.match(request.url.path):
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
            if not allowed(ip):
                return JSONResponse({"detail": "Limit reached for now (a few uploads per hour). Please try again later."}, 429)
        resp = await call_next(request)
        if request.url.path == "/" and "text/html" in resp.headers.get("content-type", ""):
            body = b"".join([c async for c in resp.body_iterator]).decode("utf-8", "ignore")
            keep = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-type")}
            resp = Response(relabel(body), media_type="text/html", headers=keep)
        if fresh: resp.set_cookie("sloth_ws", ws, max_age=30 * 86400, httponly=True, samesite="lax")
        return resp
    finally:
        WS.reset(token)