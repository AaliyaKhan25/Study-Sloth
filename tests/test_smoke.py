import os, tempfile
import sys
from types import SimpleNamespace
os.environ["SLOTH_DB"] = os.path.join(tempfile.mkdtemp(), "sloth.db")   # throwaway database
from unittest import mock
from fastapi.testclient import TestClient
import pytest
import app.pipeline as pl

FAKE = {"units": [{"name": "Unit 1: Joins", "topics": ["inner"]}], "aim": "A", "theory": "T",
        "procedure": ["s1"], "conclusion": "C",
        "flashcards": [{"q": "What does a join do?", "a": "Combines rows from related tables."}],
        "quiz": [{"q": "Which join keeps matching rows?", "options": ["INNER", "CROSS"], "answer": 0}],
        "viva": [{"q": "why?", "a": "x"}]}

def test_ollama_cloud_410_explains_cloud_model_setting(monkeypatch):
    import httpx
    import app.llm as llm

    response = mock.Mock(status_code=410, text="Gone")
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "410 Gone", request=mock.Mock(), response=response
    )
    monkeypatch.setattr(llm, "HOST", "https://ollama.com")

    with mock.patch.object(llm.httpx, "post", return_value=response):
        with pytest.raises(RuntimeError, match="gemma4:cloud"):
            llm.chat("test prompt")

def test_transcribe_reports_incompatible_pyav():
    class IncompatibleDecoder:
        def transcribe(self, path, **options):
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    with mock.patch.object(pl, "_wm", IncompatibleDecoder()):
        with pytest.raises(RuntimeError) as error:
            pl.transcribe("lecture.mp4", lambda *args: None)
        assert sys.executable in str(error.value)
        assert "pip install --upgrade -r" in str(error.value)
        assert "requirements.txt" in str(error.value)

def test_transcribe_retries_on_cpu_when_cuda_library_is_missing():
    class GpuModel:
        def transcribe(self, path, **options):
            def fail_while_decoding():
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield
            return fail_while_decoding(), SimpleNamespace(duration=1)

    class CpuModel:
        def transcribe(self, path, **options):
            segment = SimpleNamespace(start=0, end=1, text=" transcript ")
            return [segment], SimpleNamespace(duration=1)

    progress = []
    with mock.patch.object(pl, "_wm", GpuModel()), \
            mock.patch("faster_whisper.WhisperModel", return_value=CpuModel()) as whisper_model:
        assert pl.transcribe("lecture.mp4", lambda *args: progress.append(args)) == ["[00:00] transcript"]
    whisper_model.assert_called_once_with("small", device="cpu", compute_type="int8")
    assert progress == [(0.5, "Transcribing")]

def test_hosted_transcription_uses_groq_and_returns_timestamps(tmp_path, monkeypatch):
    from app import hosted_transcription

    audio_file = tmp_path / "lecture.mp4"
    audio_file.write_bytes(b"media")
    monkeypatch.setenv("GROQ_API_KEY", "test-api-key")

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "text": "Hello world",
                "segments": [
                    {"start": 61.2, "text": " Hello world "},
                    {"start": 90, "text": ""},
                ],
            }

    progress = []
    with mock.patch.object(hosted_transcription.httpx, "post", return_value=Response()) as request:
        lines = hosted_transcription.transcribe(str(audio_file), lambda *args: progress.append(args))

    assert lines == ["[01:01] Hello world"]
    assert request.call_args.args[0] == hosted_transcription.TRANSCRIPTION_URL
    assert request.call_args.kwargs["headers"] == {"Authorization": "Bearer test-api-key"}
    assert request.call_args.kwargs["data"]["model"] == "whisper-large-v3-turbo"
    assert progress == [
        (0.05, "Sending recording to Groq Whisper (long videos can take a few minutes)"),
        (0.5, "Transcription complete"),
    ]

def test_hosted_transcription_requires_groq_key(monkeypatch, tmp_path):
    from app import hosted_transcription

    audio_file = tmp_path / "lecture.mp4"
    audio_file.write_bytes(b"media")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        hosted_transcription.transcribe(str(audio_file), lambda *args: None)

def test_hosted_transcription_rejects_recordings_over_groq_limit(monkeypatch, tmp_path):
    from app import hosted_transcription

    audio_file = tmp_path / "large.mp4"
    with audio_file.open("wb") as recording:
        recording.seek(hosted_transcription.MAX_FILE_BYTES)
        recording.write(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "test-api-key")

    with mock.patch.object(hosted_transcription.httpx, "post") as request:
        with pytest.raises(RuntimeError, match="25 MB upload limit"):
            hosted_transcription.transcribe(str(audio_file), lambda *args: None)
    request.assert_not_called()

def test_unmounted_render_disk_paths_fall_back_with_warning(monkeypatch, caplog):
    import web

    monkeypatch.setattr(web.os, "access", lambda path, mode: False)
    monkeypatch.setenv("SLOTH_DB", "/var/data/template.db")
    monkeypatch.setenv("SLOTH_UPLOAD_DIR", "/var/data/uploads")
    monkeypatch.setenv("HF_HOME", "/var/data/huggingface")

    web._clear_unmounted_disk_paths()

    assert "SLOTH_DB" not in os.environ
    assert "SLOTH_UPLOAD_DIR" not in os.environ
    assert "HF_HOME" not in os.environ
    assert "using temporary service storage" in caplog.text

def test_hosted_app_keeps_lecture_transcription_enabled(monkeypatch):
    from app import main
    import web

    submitted = []
    monkeypatch.setattr(main, "save", lambda file: "lecture.mp4")
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    with TestClient(web.app) as client:
        sid = client.post("/api/subjects", data={"name": "Hosted course"}).json()["id"]
        response = client.post(
            f"/api/subjects/{sid}/lectures",
            data={"title": "Hosted lecture"},
            files={"file": ("lecture.mp4", b"media", "video/mp4")},
        )

    assert response.status_code == 200
    assert submitted[0][2] is pl.lecture_job

def test_hosted_lecture_rejects_oversized_video_before_saving(monkeypatch):
    from app import main
    import web

    submitted = []
    monkeypatch.setattr(main.app.state, "hosted", True)
    monkeypatch.setattr(main, "MAX_HOSTED_MEDIA_BYTES", 5)
    monkeypatch.setattr(main, "save", lambda file: pytest.fail("oversized upload should not be saved"))
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    with TestClient(web.app) as client:
        sid = client.post("/api/subjects", data={"name": "Hosted course"}).json()["id"]
        response = client.post(
            f"/api/subjects/{sid}/lectures",
            data={"title": "Large lecture"},
            files={"file": ("lecture.mp4", b"too large", "video/mp4")},
        )

    assert response.status_code == 413
    assert "25 MB or smaller" in response.json()["detail"]
    assert submitted == []

def test_local_lecture_upload_is_not_limited_to_hosted_groq_size(monkeypatch):
    from app import main

    submitted = []
    monkeypatch.setattr(main.app.state, "hosted", False)
    monkeypatch.setattr(main, "save", lambda file: "lecture.mp4")
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    with TestClient(main.app) as client:
        sid = client.post("/api/subjects", data={"name": "Local course"}).json()["id"]
        response = client.post(
            f"/api/subjects/{sid}/lectures",
            data={"title": "Local lecture"},
            files={"file": ("lecture.mp4", b"media", "video/mp4")},
        )

    assert response.status_code == 200
    assert submitted[0][2] is pl.lecture_job

def test_pdf_upload_submits_notes_and_study_set_job(monkeypatch):
    from app import main

    submitted = []
    monkeypatch.setattr(main, "save", lambda file: "reading.pdf")
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    with TestClient(main.app) as client:
        sid = client.post("/api/subjects", data={"name": "Biology"}).json()["id"]
        response = client.post(
            f"/api/subjects/{sid}/pdf-notes",
            data={"title": "Cell biology"},
            files={"file": ("cells.pdf", b"%PDF-test", "application/pdf")},
        )

    assert response.status_code == 200
    assert submitted[0][0] == "pdf_notes"
    assert submitted[0][2] is pl.pdf_notes_job

def test_scanned_syllabus_pdf_is_processed_as_a_background_job(monkeypatch):
    from app import main

    submitted = []
    monkeypatch.setattr(main, "save", lambda file: "syllabus.pdf")
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    with TestClient(main.app) as client:
        sid = client.post("/api/subjects", data={"name": "History"}).json()["id"]
        response = client.post(
            f"/api/subjects/{sid}/syllabus",
            files={"file": ("syllabus.pdf", b"%PDF-test", "application/pdf")},
        )

    assert response.status_code == 200
    assert submitted[0][0:3] == ("syllabus", sid, pl.syllabus_pdf_job)

def test_lecture_job_batches_notes_and_reports_completed_chunks():
    lines = [f"[00:00] {str(index).ljust(90, 'x')}" for index in range(200)]
    progress = []
    extracted_points = {"points": [{"unit": "Unit 1", "heading": "Topic", "text": "Details"}]}

    with mock.patch.object(pl.db, "q", return_value=[{"subject_id": 1}]), \
            mock.patch.object(pl.db, "x"), \
            mock.patch.object(pl, "units_of", return_value=[{"name": "Unit 1"}]), \
            mock.patch.object(pl, "transcribe", return_value=lines), \
            mock.patch.object(pl, "chat_json", return_value=extracted_points) as generate_notes, \
            mock.patch.object(pl, "cards_from") as generate_cards:
        pl.lecture_job(1, "lecture.mp4", lambda value, message="": progress.append((value, message)))

    assert generate_notes.call_count == 2
    assert progress[0] == (0.5, "Transcription finished; preparing lecture notes")
    assert any(message == "Extracted lecture chunk 2/2" for _, message in progress)
    assert progress[-2] == (pytest.approx(0.9), "Extracted lecture chunk 2/2")
    generate_cards.assert_called_once()

def test_pdf_notes_job_generates_flashcards_for_the_subject():
    progress = []
    with mock.patch.object(pl.db, "q", return_value=[{"title": "Cell biology", "subject_id": 7}]), \
            mock.patch.object(pl.db, "x") as update_pdf, \
            mock.patch.object(pl, "_pdf_chunks", return_value=["PDF source text"]) as read_pdf, \
            mock.patch.object(pl, "_pdf_notes_from_text", return_value="# Cell biology notes"), \
            mock.patch.object(pl, "cards_from", return_value=18) as generate_cards:
        pl.pdf_notes_job(12, "cells.pdf", lambda value, message="": progress.append((value, message)))

    assert read_pdf.call_args.kwargs["limit"] == 16000
    assert callable(read_pdf.call_args.kwargs["progress"])
    update_pdf.assert_called_once_with(
        "update pdf_notes set notes=? where id=?", ("# Cell biology notes", 12)
    )
    generate_cards.assert_called_once_with(7, None, "# Cell biology notes", pdf_note_id=12)
    assert progress[-1] == (0.96, "Making flashcards and questions from PDF notes")

def test_pdf_note_cards_job_can_create_deck_from_existing_notes():
    progress = []
    with mock.patch.object(
        pl.db, "q", return_value=[{"subject_id": 7, "notes": "Existing PDF notes"}]
    ), mock.patch.object(pl, "cards_from", return_value=18) as generate_cards:
        pl.pdf_note_cards_job(12, lambda value, message="": progress.append((value, message)))

    generate_cards.assert_called_once_with(7, None, "Existing PDF notes", pdf_note_id=12)
    assert progress[-1] == (0.9, "Added PDF cards to the Study deck")

def test_pdf_note_cards_job_rejects_missing_notes():
    with mock.patch.object(pl.db, "q", return_value=[{"subject_id": 7, "notes": ""}]):
        with pytest.raises(RuntimeError, match="notes are not ready"):
            pl.pdf_note_cards_job(12, lambda *args: None)

def test_pdf_cards_endpoint_queues_deck_creation_for_existing_notes(monkeypatch):
    from app import main

    submitted = []
    monkeypatch.setattr(main, "one", lambda *args: {"id": 12, "notes": "Existing notes"})
    monkeypatch.setattr(main.db, "q", lambda *args: [])
    monkeypatch.setattr(main, "submit", lambda *args: submitted.append(args))

    response = main.pdf_note_study_cards(12)

    assert response == {"ok": 1}
    assert submitted[0][0:3] == ("pdf_note_cards", 12, pl.pdf_note_cards_job)
    assert submitted[0][3] == 12

def test_scanned_pdf_pages_are_rendered_and_ocr_is_merged_in_page_order():
    import fitz
    from app import pdf_ocr

    source = fitz.open()
    text_page = source.new_page()
    text_page.insert_text((72, 72), "Selectable page text")
    scanned_page = source.new_page()
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 120), False)
    image.clear_with(255)
    scanned_page.insert_image(scanned_page.rect, stream=image.tobytes("png"))
    raw_pdf = source.tobytes()
    source.close()
    progress = []

    with mock.patch.object(pdf_ocr, "chat", return_value="OCR page text") as ocr:
        pages, total, used_ocr = pdf_ocr.extract_pdf_pages(
            raw_pdf,
            progress=lambda completed, count, page: progress.append((completed, count, page)),
        )

    assert pages == [(1, "Selectable page text"), (2, "OCR page text")]
    assert total == 2
    assert used_ocr is True
    assert progress == [(1, 1, 2)]
    assert ocr.call_args.kwargs["images"][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert ocr.call_args.kwargs["timeout"] == 180

def test_scanned_pdf_ocr_page_limit_has_actionable_error(monkeypatch):
    import fitz
    from app import pdf_ocr

    source = fitz.open()
    source.new_page()
    source.new_page()
    raw_pdf = source.tobytes()
    source.close()
    monkeypatch.setattr(pdf_ocr, "MAX_OCR_PAGES", 1)

    with pytest.raises(ValueError, match="2 pages that need OCR.*limit is 1"):
        pdf_ocr.extract_pdf_pages(raw_pdf)

def test_online_pdf_study_uses_ocr_extracted_page_text(monkeypatch):
    import online

    monkeypatch.setitem(
        online.JOBS, "ocr-test",
        {"status": "running", "progress": 0, "message": "", "result": None, "t": 0},
    )
    responses = [
        {"points": [{"text": "Photosynthesis", "topic": "Biology", "heading": "Photosynthesis", "ref": "p.1"}]},
        {"summary": ["Plants convert light into chemical energy."]},
        {"flashcards": [{"q": "What is photosynthesis?", "a": "Conversion of light to chemical energy."}],
         "quiz": [], "viva": []},
    ]
    with mock.patch.object(online, "extract_pdf_pages", return_value=([(1, "OCR extracted text")], 1, True)), \
            mock.patch.object(online, "chat_json", side_effect=responses):
        online.work("ocr-test", b"pdf-bytes", 1, "scan.pdf")

    assert online.JOBS["ocr-test"]["status"] == "done"
    assert online.JOBS["ocr-test"]["result"]["flashcards"][0]["q"] == "What is photosynthesis?"
    assert online.JOBS["ocr-test"]["result"]["points"][0]["text"] == "Photosynthesis"

def test_pdf_flashcards_are_stored_with_their_pdf_source():
    study_material = {
        "flashcards": [{"q": "What is a cell?", "a": "The basic unit of life."}],
        "quiz": [{"q": "Cells are?", "options": ["Living", "Rocks"], "answer": 0}],
        "viva": [{"q": "Name one cell part.", "a": "Nucleus."}],
    }
    with mock.patch.object(pl, "chat_json", return_value=study_material), \
            mock.patch.object(pl.db, "x") as store:
        count = pl.cards_from(7, None, "# Cell notes", pdf_note_id=12)

    assert count == 3
    assert store.call_args_list[0].args == ("delete from cards where pdf_note_id=?", (12,))
    inserts = [call.args for call in store.call_args_list[1:]]
    assert all("subject_id,pdf_note_id,kind,q,a,extra" in args[0] for args in inserts)
    assert all(args[1][0:2] == (7, 12) for args in inserts)

def test_parallel_map_runs_only_a_small_bounded_batch_and_preserves_order():
    import threading
    import time

    active = 0
    maximum = 0
    lock = threading.Lock()

    def work(value):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return value * 2

    progress = []
    assert pl._parallel_map(
        [1, 2, 3, 4], work, lambda value, message: progress.append((value, message)),
        0.0, 1.0, "Completed",
    ) == [2, 4, 6, 8]
    assert maximum == pl.MODEL_WORKERS == 2
    assert progress[-1] == (1.0, "Completed 4/4")

def test_lab_manual_requires_actual_outputs_before_final_print():
    from app import db
    from app.main import app

    result = {
        "aim": "Demonstrate a basic query.",
        "theory": "A query retrieves matching rows.",
        "materials": ["Database client"],
        "procedure": ["Create a table", "Run a query"],
        "reference_code": "SELECT 1;",
        "expected_output": "1",
        "expected_observation": "The query should return one row.",
        "flashcards": [{"q": "What does SELECT do?", "a": "It retrieves rows from a table."}],
        "quiz": [{"q": "Which statement reads rows?", "options": ["SELECT", "DROP"], "answer": 0}],
        "viva": [{"q": "What does SELECT do?", "a": "It retrieves data."}],
    }

    def run_inline(kind, ref, fn, *args):
        job_id = db.x(
            "insert into jobs(kind,ref_id,status,progress,message) values(?,?,'running',0,'Drafting')",
            (kind, ref),
        )
        fn(*args, lambda progress, message="": db.x(
            "update jobs set progress=?,message=? where id=?", (progress, message, job_id)
        ))
        db.x("update jobs set status='done',progress=1,message='Done' where id=?", (job_id,))

    with mock.patch.object(pl, "chat_json", lambda *a, **k: result), \
            mock.patch("app.main.submit", run_inline):
        client = TestClient(app)
        sid = client.post("/api/subjects", data={"name": "Databases"}).json()["id"]
        response = client.post(f"/api/subjects/{sid}/lab-manuals", data={
            "student_name": "Student",
            "class_name": "B.Tech Year 2",
            "branch": "Computer Science",
            "institution": "Example College",
            "semester": "4",
            "roll_number": "42",
            "experiment_index": "1. Basic SQL queries\n2. Table joins",
        })
        assert response.status_code == 200
        manual_id = response.json()["id"]
        manual = client.get(f"/api/lab-manuals/{manual_id}").json()
        assert manual["status"] == "done"
        assert len(manual["experiments"]) == 2
        cards = client.get(f"/api/subjects/{sid}").json()["cards"]
        assert any(card["manual_id"] == manual_id and card["kind"] == "flash" for card in cards)
        assert any(card["manual_id"] == manual_id and card["kind"] == "quiz" for card in cards)
        db.x("delete from cards where manual_id=?", (manual_id,))
        regenerated = client.post(f"/api/lab-manuals/{manual_id}/study-cards")
        assert regenerated.status_code == 200
        cards = client.get(f"/api/subjects/{sid}").json()["cards"]
        assert any(card["manual_id"] == manual_id and card["kind"] == "flash" for card in cards)
        assert any(card["manual_id"] == manual_id and card["kind"] == "quiz" for card in cards)
        assert client.post(f"/api/lab-manuals/{manual_id}/outputs", json={"outputs": ["only one"]}).status_code == 400
        outputs = ["id | name\n1 | Ada <3", ""]
        saved = client.post(f"/api/lab-manuals/{manual_id}/outputs", json={"outputs": outputs})
        assert saved.status_code == 200
        assert client.get(f"/api/lab-manuals/{manual_id}").json()["experiments"][0]["actual_output"] == outputs[0]
        page = client.get(f"/lab-manuals/{manual_id}/print")
        assert page.status_code == 200
        assert "AI-generated" not in page.text
        assert "Expected output" not in page.text
        assert "<h2>Output</h2><pre>id | name\n1 | Ada &lt;3</pre>" in page.text
        assert "<h2>Output</h2><pre>1</pre>" in page.text
        assert "Ada &lt;3" in page.text
        assert "Example College" in page.text

def test_lab_record_flow_and_review_gate():
    # The language model is replaced by a fake, so this checks the app's own rules.
    with mock.patch.object(pl, "chat_json", lambda *a, **k: FAKE):
        from app.main import app, pool
        c = TestClient(app)
        sid = c.post("/api/subjects", data={"name": "DBMS"}).json()["id"]
        c.post(f"/api/subjects/{sid}/syllabus", data={"text": "Unit 1 joins"})
        lid = c.post(f"/api/subjects/{sid}/labs",
                     data={"title": "Joins", "code": "select 1", "output": "1 row"}).json()["id"]
        pool.shutdown(wait=True)
        assert c.get(f"/api/subjects/{sid}").json()["subject"]["units"][0]["name"] == "Unit 1: Joins"
        assert c.get(f"/labs/{lid}/print").status_code == 409            # locked until reviewed
        bad = c.post(f"/api/labs/{lid}/review", json={"confirmed": False, "code": "c", "output": "o", "record": {}})
        assert bad.status_code == 400                                     # must confirm own run
        rec = c.get(f"/api/labs/{lid}").json()["record"]
        ok = c.post(f"/api/labs/{lid}/review", json={"confirmed": True, "code": "select 1", "output": "1 row", "record": rec})
        assert ok.status_code == 200
        page = c.get(f"/labs/{lid}/print")
        assert page.status_code == 200 and "1 row" in page.text           # output is the student's own
        cards = c.get(f"/api/subjects/{sid}").json()["cards"]
        assert any(card["lab_id"] == lid and card["kind"] == "flash" for card in cards)
        assert any(card["lab_id"] == lid and card["kind"] == "quiz" for card in cards)
        assert any(card["lab_id"] == lid and card["kind"] == "viva" for card in cards)