"""Online entry point (Render). Password-protected; lecture audio is local-only.
Start:  python -m uvicorn web:app --host 0.0.0.0 --port $PORT     (needs SLOTH_WEB_PASSWORD)"""
import os, base64, secrets
from fastapi import Request
from fastapi.responses import Response
import app.pipeline as pl
from app.main import app

PASSWORD = os.environ.get("SLOTH_WEB_PASSWORD", "")
if not PASSWORD:
    raise SystemExit("Set SLOTH_WEB_PASSWORD first, so strangers cannot use your key and your data.")

def _no_audio(*a, **k):
    raise RuntimeError("Lecture recordings are processed in the local version of Study Sloth. Here, use PDF notes, a syllabus or lab code.")
if hasattr(pl, "transcribe"):
    pl.transcribe = _no_audio

@app.middleware("http")
async def gate(request: Request, call_next):
    h, ok = request.headers.get("authorization", ""), False
    if h.startswith("Basic "):
        try:
            _, _, pw = base64.b64decode(h[6:]).decode().partition(":")
            ok = secrets.compare_digest(pw, PASSWORD)
        except Exception:
            pass
    if not ok:
        return Response("Login required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Study Sloth"'})
    return await call_next(request)