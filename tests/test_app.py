"""UI tests (Streamlit AppTest, mock LLM): upload the real sample PDFs, check pre-fill, evaluate."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp import db
from rfp.document_tool import extract_metadata, extract_text

PDFS = Path(__file__).resolve().parent.parent / "sample_pdfs"


def test_metadata_is_prefilled_from_the_pdf_text():
    meta = extract_metadata(extract_text((PDFS / "orbit_digital.pdf").read_bytes())[0])
    assert meta == {"supplier_name": "Orbit Digital", "submission_date": "2026-08-21", "experience_rating": 10.0}
    assert extract_metadata("[Page 1]\nno metadata here") == {"supplier_name": None, "submission_date": None,
                                                                "experience_rating": None}


def test_app_full_flow_with_uploaded_pdfs(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ui.db"))
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.secrets["LLM_PROVIDER"] = "mock"  # never hit a real API from tests, even if a key is configured
    at.run()
    assert not at.exception
    assert next(b for b in at.button if "Evaluate" in b.label).disabled  # nothing uploaded yet

    at.file_uploader[0].set_value([(p.name, p.read_bytes(), "application/pdf") for p in sorted(PDFS.glob("*.pdf"))]).run()
    assert not at.exception
    assert sorted(t.value for t in at.text_input) == ["Apex Systems", "BrightPath Tech", "NexaWorks", "Orbit Digital"]
    assert sorted(s.value for s in at.slider) == [5, 8, 9, 10]  # ratings read from the PDFs

    evaluate = next(b for b in at.button if "Evaluate" in b.label)
    assert not evaluate.disabled
    evaluate.click().run()
    assert not at.exception
    run = at.session_state["run"]
    assert run["status"] == "completed" and len(run["suppliers"]) == 4
    assert db.load_run(run["rfp_run_id"])["rfp_run_id"] == run["rfp_run_id"]


def test_save_criteria_round_trip(tmp_path):
    p = str(tmp_path / "c.db")
    db.init_db(p)
    rows = db.get_criteria(p, active_only=False)
    rows[0]["weight"], rows[4]["is_active"], rows[4]["weight"] = 40, 0, 10
    db.save_criteria(rows, p)
    active = db.get_criteria(p)
    assert len(active) == 4 and active[0]["weight"] == 40 and sum(c["weight"] for c in active) == 100
    db.init_db(p)  # re-init must never overwrite user edits
    assert len(db.get_criteria(p)) == 4
