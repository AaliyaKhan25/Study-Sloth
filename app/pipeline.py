import os, re, json, sys
from pathlib import Path
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
    size = os.environ.get("SLOTH_WHISPER", "small")
    if _wm is None:
        try: _wm = WhisperModel(size, device="cuda", compute_type="float16")   # NVIDIA GPU
        except Exception: _wm = WhisperModel(size, device="cpu", compute_type="int8")

    def decode(model):
        segments, info = model.transcribe(path, vad_filter=True)
        return list(segments), info

    try:
        segs, info = decode(_wm)
    except TypeError as exc:
        if "metadata_errors" in str(exc):
            requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
            raise RuntimeError(
                "The installed PyAV version is incompatible with faster-whisper. "
                f'Update the Python running Study Sloth: "{sys.executable}" -m pip install '
                f'--upgrade -r "{requirements}", then restart Study Sloth.'
            ) from exc
        raise
    except Exception as exc:
        error = str(exc).lower()
        missing_cuda_library = (
            any(library in error for library in ("cublas", "cudnn", "cuda"))
            and any(message in error for message in ("not found", "cannot be loaded"))
        )
        if not missing_cuda_library:
            raise
        _wm = WhisperModel(size, device="cpu", compute_type="int8")
        segs, info = decode(_wm)

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
    r = chat_json(f'Write a lab record. Experiment: {lab["title"]}\n\nLECTURE NOTES (use for theory):\n{ctx}\n\nCODE:\n{lab["code"][:4000]}\n\nOUTPUT FROM THE STUDENT\'S REAL RUN:\n{lab["output"][:2000]}\n\nRules: the conclusion may only refer to what the output above shows; never invent results or numbers. Return JSON: {{"aim":"","theory":"","procedure":["step"],"conclusion":"","flashcards":[{{"q":"","a":""}}] (5 cards about the experiment and supplied code),"quiz":[{{"q":"","options":["","","",""],"answer":0}}] (3 questions, answer is option index),"viva":[{{"q":"","a":""}}] (4, about why the code is written this way)}}', system=SYS)
    flashcards = r.get("flashcards", [])
    if not isinstance(flashcards, list) or not any(
        isinstance(card, dict) and card.get("q") and card.get("a") for card in flashcards
    ):
        raise RuntimeError("The local model did not return lab flashcards.")
    rec = {"aim": r.get("aim", ""), "theory": r.get("theory", ""), "conclusion": r.get("conclusion", ""),
           "procedure": "\n".join(map(str, r.get("procedure", []))),
           "sources": sorted({f"{t} @ {pt.get('ts','?')}" for _, t, pt in rel})}
    db.x("update labs set record=?, reviewed=0 where id=?", (json.dumps(rec), lid))
    db.x("delete from cards where lab_id=?", (lid,))
    for card in flashcards:
        if isinstance(card, dict) and card.get("q") and card.get("a"):
            db.x("insert into cards(subject_id,lab_id,kind,q,a) values(?,?,'flash',?,?)",
                 (lab["subject_id"], lid, str(card["q"]), str(card["a"])))
    for card in r.get("quiz", []):
        if not isinstance(card, dict) or not card.get("q"):
            continue
        options = card.get("options", [])
        answer = card.get("answer", -1)
        if not isinstance(options, list) or len(options) < 2 or not isinstance(answer, int) or not 0 <= answer < len(options):
            continue
        extra = json.dumps({"options": options, "answer": answer})
        db.x("insert into cards(subject_id,lab_id,kind,q,a,extra) values(?,?,'quiz',?,'',?)",
             (lab["subject_id"], lid, str(card["q"]), extra))
    for c in r.get("viva", []):
        if isinstance(c, dict) and c.get("q"):
            db.x("insert into cards(subject_id,lab_id,kind,q,a) values(?,?,'viva',?,?)", (lab["subject_id"], lid, c["q"], str(c.get("a", ""))))

def lab_manual_job(manual_id, p):
    manual = db.q("select * from lab_manuals where id=?", (manual_id,))[0]
    titles = json.loads(manual["experiments"])
    records = []
    for i, title in enumerate(titles):
        p(0.1 + 0.8 * i / len(titles), f"Drafting experiment {i + 1}/{len(titles)}")
        rel = related(manual["subject_id"], title)
        notes = "\n".join(
            f"{source}: {pt.get('heading', '')} — {pt.get('text', '')}"
            for _, source, pt in rel
        ) or "(No course notes available; use general knowledge and state assumptions.)"
        result = chat_json(
            f'Create a careful educational lab-manual draft for this experiment: {title}\n'
            f'Course notes, if relevant:\n{notes[:5000]}\n\n'
            "Return JSON with these fields: aim (string), theory (string), materials (array of strings), "
            "procedure (array of numbered steps as strings), reference_code (string, may be empty if code "
            "language is unclear), expected_output (string), expected_observation (string), "
            "flashcards (array of 4 {q, a} objects), quiz (array of 3 {q, options, answer} objects; "
            "options must contain 4 choices and answer is the correct zero-based index), "
            "viva (array of {q, a} objects, 3 items). Make assumptions explicit. The code and expected "
            "output are illustrative examples only: do not claim that code was run, do not label expected "
            "output as an actual result, and do not claim that any measurement or observation happened. "
            "Use a small, understandable example. Keep content specific to the experiment title.",
            system=("You are preparing a draft study aid, not certifying experiment results. "
                    "Never claim to have run code or observed results. Clearly distinguish suggested "
                    "examples from actual student work."),
        )
        required = ("aim", "theory", "expected_output", "expected_observation")
        if not isinstance(result, dict) or any(not str(result.get(key, "")).strip() for key in required):
            raise RuntimeError(f"The local model did not return a complete draft for experiment: {title}")
        for key in ("materials", "procedure", "viva"):
            if not isinstance(result.get(key, []), list):
                raise RuntimeError(f"The local model returned invalid {key} for experiment: {title}")
        for key in ("flashcards", "quiz"):
            if not isinstance(result.get(key), list):
                raise RuntimeError(f"The local model returned invalid {key} for experiment: {title}")
        record = {
            "title": title,
            "aim": str(result["aim"]),
            "theory": str(result["theory"]),
            "materials": [str(item) for item in result.get("materials", []) if str(item).strip()],
            "procedure": [str(item) for item in result.get("procedure", []) if str(item).strip()],
            "reference_code": str(result.get("reference_code", "")),
            "expected_output": str(result["expected_output"]),
            "expected_observation": str(result["expected_observation"]),
            "viva": [
                {"q": str(item.get("q", "")), "a": str(item.get("a", ""))}
                for item in result.get("viva", [])
                if isinstance(item, dict) and item.get("q")
            ],
            "study": {
                "flashcards": result["flashcards"],
                "quiz": result["quiz"],
            },
        }
        records.append(record)
        db.x("update lab_manuals set experiments=? where id=?", (json.dumps(records), manual_id))
    _store_manual_cards(manual_id, manual["subject_id"], records)
    p(0.95, "Finishing manual draft")

def _store_manual_cards(manual_id, subject_id, records):
    db.x("delete from cards where manual_id=?", (manual_id,))
    for record in records:
        study = record.get("study", {})
        for card in study.get("flashcards", []):
            if isinstance(card, dict) and card.get("q") and card.get("a"):
                db.x(
                    "insert into cards(subject_id,manual_id,kind,q,a) values(?,?,'flash',?,?)",
                    (subject_id, manual_id, f"{record['title']}: {card['q']}", str(card["a"])),
                )
        for card in study.get("quiz", []):
            if not isinstance(card, dict) or not card.get("q"):
                continue
            options, answer = card.get("options"), card.get("answer", -1)
            if not isinstance(options, list) or len(options) < 2 or not isinstance(answer, int) or not 0 <= answer < len(options):
                continue
            extra = json.dumps({"options": options, "answer": answer})
            db.x(
                "insert into cards(subject_id,manual_id,kind,q,a,extra) values(?,?,'quiz',?,'',?)",
                (subject_id, manual_id, f"{record['title']}: {card['q']}", extra),
            )

def lab_manual_cards_job(manual_id, p):
    manual = db.q("select * from lab_manuals where id=?", (manual_id,))[0]
    records = json.loads(manual["experiments"])
    study_material = "\n\n".join(
        f"Experiment: {item.get('title', '')}\nAim: {item.get('aim', '')}\n"
        f"Theory: {item.get('theory', '')}\nProcedure: {'; '.join(item.get('procedure', []))}\n"
        f"Reference code: {item.get('reference_code', '')}\nExpected output: {item.get('expected_output', '')}"
        for item in records
    )
    p(0.2, "Creating manual flashcards and quizzes")
    result = chat_json(
        "Create study-deck materials from these lab manual experiments. Return JSON with "
        '"flashcards":[{"q":"","a":""}] (4 per experiment, based on the experiment concepts), '
        '"quiz":[{"q":"","options":["","","",""],"answer":0}] (3 per experiment; answer is the '
        "correct zero-based option index). Keep questions specific to the experiments and do not "
        "invent experimental results.\n\n" + study_material[:9000],
        system=SYS,
    )
    if not isinstance(result.get("flashcards"), list) or not isinstance(result.get("quiz"), list):
        raise RuntimeError("The local model did not return manual flashcards and quizzes.")
    for item in records:
        item.pop("study", None)
    records[0]["study"] = {
        "flashcards": result["flashcards"],
        "quiz": result["quiz"],
    }
    db.x("update lab_manuals set experiments=? where id=?", (json.dumps(records), manual_id))
    _store_manual_cards(manual_id, manual["subject_id"], records)
    p(0.9, "Adding cards to the study deck")
