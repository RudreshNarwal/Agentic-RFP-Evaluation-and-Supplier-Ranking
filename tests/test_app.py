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
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ui.db"))
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.secrets["LLM_PROVIDER"] = "mock"  # never hit a real API from tests, even if a key is configured
    at.run()
    assert not at.exception
    assert next(b for b in at.button if "Evaluate" in b.label).disabled  # nothing uploaded yet

    at.file_uploader[0].set_value([(p.name, p.read_bytes(), "application/pdf") for p in sorted(PDFS.glob("*.pdf"))]).run()
    assert not at.exception
    names = sorted(t.value for t in at.text_input if t.label == "Supplier name")
    assert names == ["Apex Systems", "BrightPath Tech", "NexaWorks", "Orbit Digital"]
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


def _ui(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ui.db"))
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(k, "")  # no server key (and stops .env from filling one in)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "")
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.secrets["LLM_PROVIDER"] = "mock"
    at.run()
    at.file_uploader[0].set_value([(p.name, p.read_bytes(), "application/pdf") for p in sorted(PDFS.glob("*.pdf"))]).run()
    return at


def _evaluate_button(at):
    return next(b for b in at.button if "Evaluate" in b.label)


def test_real_provider_without_any_key_blocks_evaluation(tmp_path, monkeypatch):
    at = _ui(tmp_path, monkeypatch)
    at.selectbox(key="llm_provider").set_value("gemini").run()
    assert not at.exception
    assert _evaluate_button(at).disabled
    assert any("Add a Google API key" in w.value for w in at.warning)


def test_ui_key_and_vertex_choice_reach_the_llm_but_never_the_env_or_run_json(tmp_path, monkeypatch):
    import json
    import os
    seen = []

    def fake(system, prompt, schema, provider, model, **creds):
        seen.append((provider, model, creds))
        return json.dumps({"criteria": [{"criterion_id": i, "score": 7, "max_score": 10, "justification": "j",
                                         "evidence": ""} for i in range(1, 6)], "risks": [], "overall_summary": "s"})
    monkeypatch.setattr("rfp.llm.complete_json", fake)
    at = _ui(tmp_path, monkeypatch)
    at.selectbox(key="llm_provider").set_value("gemini").run()
    at.radio(key="llm_endpoint").set_value("Vertex AI").run()
    at.text_input(key="llm_key_gemini").input("ui-secret-key").run()
    assert not _evaluate_button(at).disabled
    _evaluate_button(at).click().run()
    assert not at.exception
    assert seen and all(p == "gemini" and c == {"vertex": True, "api_key": "ui-secret-key"} for p, _, c in seen)
    assert os.environ.get("GOOGLE_API_KEY") == ""
    run = at.session_state["run"]
    assert "ui-secret-key" not in json.dumps(run) and "ui-secret-key" not in json.dumps(db.load_run(run["rfp_run_id"]))


def test_redact_removes_the_key_from_error_text():
    from rfp.orchestrator import redact
    assert redact("401 Incorrect API key provided: sk-abc123", {"api_key": "sk-abc123"}) == "401 Incorrect API key provided: ***"
    assert redact("boom", {}) == "boom"


def test_history_reevaluate_and_compare_in_the_ui(tmp_path, monkeypatch):
    at = _ui(tmp_path, monkeypatch)  # mock provider, four PDFs uploaded
    _evaluate_button(at).click().run()
    assert not at.exception
    first = at.session_state["run"]
    assert at.session_state["main_tab"] == "③ Pipeline"  # the pipeline is shown after a run
    assert any("Document Tool" in c.value for c in at.caption)  # pipeline stage cards rendered

    assert at.selectbox(key="hist_pick").value == first["rfp_run_id"]  # History follows the run just made
    at.button(key="hist_reevaluate").click().run()
    assert not at.exception
    second = at.session_state["run"]
    assert second["rfp_run_id"] != first["rfp_run_id"] and second["source_run_id"] == first["rfp_run_id"]
    assert at.session_state["main_tab"] == "⑦ History & Compare"
    assert at.selectbox(key="cmp_before").value == first["rfp_run_id"]
    assert at.selectbox(key="cmp_now").value == second["rfp_run_id"]
    assert at.selectbox(key="hist_pick").value == second["rfp_run_id"]
    assert any("Same ranking order" in s.value for s in at.success)  # mock scoring is deterministic
