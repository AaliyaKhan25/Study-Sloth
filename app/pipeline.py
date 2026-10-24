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

def _split_words(text, limit):
    parts, words, size = [], [], 0
    for word in text.split():
        if len(word) > limit:
            if words:
                parts.append(" ".join(words)); words, size = [], 0
            parts.extend(word[i:i + limit] for i in range(0, len(word), limit))
        elif words and size + len(word) + 1 > limit:
            parts.append(" ".join(words)); words, size = [word], len(word)
        else:
            words.append(word); size += len(word) + (1 if len(words) > 1 else 0)
    if words: parts.append(" ".join(words))
    return parts

def _pdf_chunks(path, limit=12000):
    from pypdf import PdfReader
    reader = PdfReader(path)
    chunks, current, current_size, text_pages = [], [], 0, 0
    for page_number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if not text: continue
        text_pages += 1
        marker = f"[Source page {page_number}]\n"
        for part in _split_words(text, limit - len(marker)):
            block = marker + part
            if current and current_size + len(block) + 1 > limit:
                chunks.append("\n".join(current)); current, current_size = [], 0
            current.append(block); current_size += len(block) + 1
    if current: chunks.append("\n".join(current))
    if not text_pages:
        raise ValueError("No selectable text was found in this PDF. Scanned PDFs need OCR before note generation.")
    return chunks

def _pdf_notes_from_text(text, title, final=False):
    if final:
        prompt = (f"Create short, clear study notes for the PDF titled {title!r} from these section notes. "
                  "Combine repeated ideas, keep important definitions, formulas, processes and comparisons, "
                  "and retain source page references in [p. N] form. Use a few headings and concise bullets; "
                  "aim for under 1000 words. Use only the supplied material.\n\n" + text)
    else:
        prompt = (f"Summarize this part of the PDF titled {title!r} as concise study notes. "
                  "Keep important definitions, formulas, steps, distinctions and examples. Use a heading and "
                  "at most 8 concise bullets. Preserve source page references such as [Source page 4]. "
                  "Do not add outside facts.\n\n" + text)
    result = chat(prompt, system=SYS, num_predict=1536 if final else 512).strip()
    if not result: raise RuntimeError("The local model returned empty notes.")
    return result

def _group_notes(parts, limit=4500):
    groups, current, current_size = [], [], 0
    for part in parts:
        subparts = _split_words(part, limit) if len(part) > limit else [part]
        for item in subparts:
            if current and current_size + len(item) + 2 > limit:
                groups.append(current); current, current_size = [], 0
            current.append(item); current_size += len(item) + 2
    if current: groups.append(current)
    return groups

def pdf_notes_job(doc_id, path, p):
    doc = db.q("select title from pdf_notes where id=?", (doc_id,))[0]
    title = doc["title"]
    p(0.02, "Extracting PDF text")
    chunks = _pdf_chunks(path)
    if len(chunks) == 1:
        p(0.08, "Summarizing PDF with local qwen3:4b")
        summaries = [_pdf_notes_from_text(chunks[0], title, final=True)]
    else:
        summaries = []
        for i, chunk in enumerate(chunks):
            p(0.05 + 0.6 * i / len(chunks), f"Summarizing section {i + 1}/{len(chunks)} with local qwen3:4b")
            summaries.append(_pdf_notes_from_text(chunk, title))
            p(0.05 + 0.6 * (i + 1) / len(chunks), f"Summarized section {i + 1}/{len(chunks)}")
    level = 0
    while sum(map(len, summaries)) > 5000:
        if level >= 8: raise RuntimeError("Could not combine the PDF notes into a short summary.")
        groups = _group_notes(summaries)
        combined = []
        for i, group in enumerate(groups):
            p(0.72 + 0.18 * min(level + (i + 1) / len(groups), 1), "Combining section notes")
            combined.append(_pdf_notes_from_text("\n\n".join(group), title))
        summaries = combined; level += 1
    if len(chunks) == 1:
        notes = summaries[0]
    else:
        p(0.94, "Writing final notes")
        notes = _pdf_notes_from_text("\n\n".join(summaries), title, final=True)
    db.x("update pdf_notes set notes=? where id=?", (notes, doc_id))

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

def pdf_job(lid, path, p):
    from pypdf import PdfReader
    lec = db.q("select * from lectures where id=?", (lid,))[0]
    names = [u["name"] for u in units_of(lec["subject_id"])] or ["General"]
    p(0.1, "Reading PDF")
    pages = [f"[p.{i}]\n{(pg.extract_text() or '').strip()}" for i, pg in enumerate(PdfReader(path).pages, 1)]
    db.x("update lectures set transcript=? where id=?", ("\n\n".join(pages), lid))
    pts, cs = [], list(chunks(pages, 3500))      # a few pages at a time, so nothing is cut off
    for i, c in enumerate(cs):
        p(0.15 + 0.75 * i / max(len(cs), 1), f"Writing notes {i + 1}/{len(cs)}")
        r = chat_json(f'Units: {names}\nThese are pages from the student\'s notes. Extract every teaching point. Keep every named item (tools, terms, formulas, steps) and do not skip or merge items. Return JSON: {{"points":[{{"unit":"<one of the units above>","heading":"short","text":"1-3 sentences","ts":"page, e.g. p.3"}}]}}\n\n{c}', system=SYS)
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
