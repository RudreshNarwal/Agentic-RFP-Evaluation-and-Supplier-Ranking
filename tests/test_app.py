"""UI smoke test (Streamlit AppTest, mock LLM) + criteria editing round-trip."""
from streamlit.testing.v1 import AppTest

from rfp import db


def test_app_full_flow_with_bundled_samples(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ui.db"))
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.secrets["LLM_PROVIDER"] = "mock"  # never hit a real API from tests, even if secrets.toml exists
    at.run()
    assert not at.exception
    at.toggle[0].set_value(True).run()
    evaluate = next(b for b in at.button if "Evaluate" in b.label)
    assert not evaluate.disabled
    evaluate.click().run()
    assert not at.exception
    run = at.session_state["run"]
    assert run["status"] == "completed" and len(run["suppliers"]) == 5
    assert run["suppliers"][-1]["supplier_name"] == "Scanned Supplier (error case)"
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
