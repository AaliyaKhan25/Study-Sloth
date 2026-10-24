import os, re, json
from . import db
from .llm import chat, chat_json

SYS = "You are a careful study assistant. Use ONLY the material given. If something is unclear, say so instead of guessing."
_wm = None

def units_of(sid):
    return json.loads(db.q("select units from subjects where id=?", (sid,))[0]["units"])

def syllabus_job(sid, text, p):
    p(0.2, "Reading syllabus")
    r = chat_json('Split this syllabus into units. Return JSON: {"units":[{"name":"Unit 1: Title","topics":["..."]}]}\n\n' + text[:8000], system=SYS)
    units = [u for u in r.get("units", []) if isinstance(u, dict) and u.get("name")] or [{"name": "General", "topics": []}]
    db.x("update subjects set syllabus=?, units=? where id=?", (text, json.dumps(units), sid))

def transcribe(path, p):
    global _wm
    from faster_whisper import WhisperModel
    if _wm is None:
        size = os.environ.get("SLOTH_WHISPER", "small")
        try: _wm = WhisperModel(size, device="cuda", compute_type="float16")   # NVIDIA GPU
        except Exception: _wm = WhisperModel(size, device="cpu", compute_type="int8")
    segs, info = _wm.transcribe(path, vad_filter=True)
    lines = []
    for s in segs:
        lines.append(f"[{int(s.start // 60):02d}:{int(s.start % 60):02d}] {s.text.strip()}")
        p(0.5 * min(s.end / max(info.duration, 1), 1), "Transcribing")
    return lines

def chunks(lines, size=4500):
    cur, n = [], 0
    for l in lines:
        if n + len(l) > size and cur: yield "\n".join(cur); cur, n = [], 0
        cur.append(l); n += len(l)
    if cur: yield "\n".join(cur)

def lecture_job(lid, path, p):
    lec = db.q("select * from lectures where id=?", (lid,))[0]
    names = [u["name"] for u in units_of(lec["subject_id"])] or ["General"]
    lines = transcribe(path, p)
    db.x("update lectures set transcript=? where id=?", ("\n".join(lines), lid))
    pts, cs = [], list(chunks(lines))
    for i, c in enumerate(cs):
        p(0.5 + 0.4 * i / max(len(cs), 1), f"Writing notes {i + 1}/{len(cs)}")
        r = chat_json(f'Units: {names}\nFrom this lecture transcript, extract the teaching points. Return JSON: {{"points":[{{"unit":"<one of the units above>","heading":"short","text":"1-3 sentences","ts":"MM:SS of the transcript line it came from"}}]}}\n\n{c}', system=SYS)
        pts += [x for x in r.get("points", []) if isinstance(x, dict)]
    db.x("update lectures set points=? where id=?", (json.dumps(pts), lid))
    p(0.93, "Making flashcards and questions")
    cards_from(lec["subject_id"], lid, "\n".join(f"{x.get('heading','')}: {x.get('text','')}" for x in pts)[:6000])

def cards_from(sid, lid, notes):
    r = chat_json('From these notes make study material. Return JSON: {"flashcards":[{"q":"","a":""}] (8), "quiz":[{"q":"","options":["","","",""],"answer":0}] (5, answer is option index), "viva":[{"q":"","a":""}] (5)}\n\n' + notes, system=SYS)
    db.x("delete from cards where lecture_id=?", (lid,))
    for k, key in (("flash", "flashcards"), ("quiz", "quiz"), ("viva", "viva")):
        for c in r.get(key, []):
            if isinstance(c, dict) and c.get("q"):
                extra = json.dumps({"options": c.get("options", []), "answer": c.get("answer", 0)}) if k == "quiz" else ""
                db.x("insert into cards(subject_id,lecture_id,kind,q,a,extra) values(?,?,?,?,?,?)", (sid, lid, k, c["q"], str(c.get("a", "")), extra))

def board_job(lid, path, p):
    lec = db.q("select * from lectures where id=?", (lid,))[0]
    names = [u["name"] for u in units_of(lec["subject_id"])] or ["General"]
    p(0.3, "Reading board photo")
    r = chat_json(f'Photo of a classroom board. Units: {names}. Extract formulas, definitions and diagrams (describe diagrams in one line). Do not add anything not visible; write [unclear] where unreadable. Return JSON: {{"items":[{{"unit":"<one of the units>","title":"","markdown":""}}]}}',
                  system=SYS, images=[open(path, "rb").read()])
    board = json.loads(lec["board"]) + [i for i in r.get("items", []) if isinstance(i, dict)]
    db.x("update lectures set board=? where id=?", (json.dumps(board), lid))

def match_unit(u, names):
    u = str(u or "")
    for n in names:
        if n == u or (u and (u in n or n in u)): return n
    return names[0]

def notes_view(lec, units):
    names = [u["name"] for u in units] or ["General"]
    out = {n: {"unit": n, "points": [], "board": []} for n in names}
    for pt in json.loads(lec["points"]): out[match_unit(pt.get("unit"), names)]["points"].append(pt)
    for b in json.loads(lec["board"]): out[match_unit(b.get("unit"), names)]["board"].append(b)
    return [v for v in out.values() if v["points"] or v["board"]]

def related(sid, text, k=6):
    words = set(re.findall(r"[a-z]{4,}", text.lower())); rows = []
    for lec in db.q("select title,points from lectures where subject_id=?", (sid,)):
        for pt in json.loads(lec["points"]):
            t = set(re.findall(r"[a-z]{4,}", (pt.get("heading", "") + " " + pt.get("text", "")).lower()))
            if words & t: rows.append((len(words & t), lec["title"], pt))
    rows.sort(key=lambda r: -r[0]); return rows[:k]

def lab_job(lid, img_path, p):
    lab = db.q("select * from labs where id=?", (lid,))[0]
    if img_path and not lab["output"].strip():
        p(0.15, "Reading output screenshot")
        txt = chat("Transcribe the text in this screenshot exactly, character for character. No commentary.", images=[open(img_path, "rb").read()])
        db.x("update labs set output=?, output_note=? where id=?", (txt, "Transcribed from your screenshot by a local vision model. Check it against the real output.", lid))
        lab["output"] = txt
    p(0.4, "Finding matching lecture notes")
    rel = related(lab["subject_id"], lab["title"] + " " + lab["code"])
    ctx = "\n".join(f"[{t} @ {pt.get('ts','?')}] {pt.get('heading','')}: {pt.get('text','')}" for _, t, pt in rel) or "(no lecture notes yet)"
    p(0.6, "Writing the record")
    r = chat_json(f'Write a lab record. Experiment: {lab["title"]}\n\nLECTURE NOTES (use for theory):\n{ctx}\n\nCODE:\n{lab["code"][:4000]}\n\nOUTPUT FROM THE STUDENT\'S REAL RUN:\n{lab["output"][:2000]}\n\nRules: the conclusion may only refer to what the output above shows; never invent results or numbers. Return JSON: {{"aim":"","theory":"","procedure":["step"],"conclusion":"","viva":[{{"q":"","a":""}}] (4, about why the code is written this way)}}', system=SYS)
    rec = {"aim": r.get("aim", ""), "theory": r.get("theory", ""), "conclusion": r.get("conclusion", ""),
           "procedure": "\n".join(map(str, r.get("procedure", []))),
           "sources": sorted({f"{t} @ {pt.get('ts','?')}" for _, t, pt in rel})}
    db.x("update labs set record=?, reviewed=0 where id=?", (json.dumps(rec), lid))
    db.x("delete from cards where lab_id=?", (lid,))
    for c in r.get("viva", []):
        if isinstance(c, dict) and c.get("q"):
            db.x("insert into cards(subject_id,lab_id,kind,q,a) values(?,?,'viva',?,?)", (lab["subject_id"], lid, c["q"], str(c.get("a", ""))))