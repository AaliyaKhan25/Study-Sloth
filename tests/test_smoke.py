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
    assert progress == [(0.05, "Uploading lecture for transcription"), (0.5, "Transcription complete")]

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