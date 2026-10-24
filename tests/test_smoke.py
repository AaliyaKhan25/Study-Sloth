import os, tempfile
os.environ["SLOTH_DB"] = os.path.join(tempfile.mkdtemp(), "sloth.db")   # throwaway database
from unittest import mock
from fastapi.testclient import TestClient
import app.pipeline as pl

FAKE = {"units": [{"name": "Unit 1: Joins", "topics": ["inner"]}], "aim": "A", "theory": "T",
        "procedure": ["s1"], "conclusion": "C", "viva": [{"q": "why?", "a": "x"}]}

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