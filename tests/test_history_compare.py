"""Run history: stored documents, re-evaluation, and run-to-run comparison."""
import sqlite3
from pathlib import Path

import pytest

from rfp import db
from rfp.compare import compare_runs
from rfp.orchestrator import run_batch

PDFS = Path(__file__).resolve().parent.parent / "sample_pdfs"
META = {"Apex Systems": ("apex_systems.pdf", "2026-08-20", 8), "BrightPath Tech": ("brightpath_tech.pdf", "2026-08-25", 5),
        "NexaWorks": ("nexaworks.pdf", "2026-08-18", 9), "Orbit Digital": ("orbit_digital.pdf", "2026-08-21", 10)}


@pytest.fixture
def dbp(tmp_path):
    p = str(tmp_path / "h.db")
    db.init_db(p)
    return p


def subs():
    return [{"supplier_name": n, "submission_date": d, "experience_rating": r, "filename": f,
             "pdf_bytes": (PDFS / f).read_bytes()} for n, (f, d, r) in META.items()]


def test_documents_are_stored_and_a_run_can_be_reevaluated(dbp):
    first = run_batch(subs(), db_path=dbp, provider="mock", model="m")
    inputs = db.get_run_inputs(first["rfp_run_id"], dbp)
    assert [(s["supplier_name"], s["pdf_bytes"]) for s in inputs] == [(s["supplier_name"], s["pdf_bytes"]) for s in subs()]

    with db.connect(dbp) as conn:  # the user changes the criteria before re-evaluating
        conn.execute("UPDATE evaluation_criteria SET weight = 40 WHERE criterion_id = 1")
        conn.execute("UPDATE evaluation_criteria SET weight = 0 WHERE criterion_id = 5")
    second = run_batch(inputs, db_path=dbp, provider="mock", model="m", source_run_id=first["rfp_run_id"])
    assert second["source_run_id"] == first["rfp_run_id"]

    runs = db.list_runs(dbp)
    assert [r["rfp_run_id"] for r in runs][:2] == [second["rfp_run_id"], first["rfp_run_id"]]
    newest = runs[0]
    assert newest["suppliers"] == 4 and newest["winner"] == second["suppliers"][0]["supplier_name"]
    assert newest["can_reevaluate"] and newest["source_run_id"] == first["rfp_run_id"]

    cmp = compare_runs(first, second)
    assert "Criterion 'Technical Capability': weight 30% → 40%" in cmp["changes"]
    assert "Criterion 'Support & Experience': weight 10% → 0%" in cmp["changes"]
    assert len(cmp["suppliers"]) == 4 and all(r["ppi_change"] is not None for r in cmp["suppliers"])


def test_compare_reports_movement_score_changes_and_membership():
    def run(model, rows):
        return {"llm": {"provider": "gemini", "model": model},
                "criteria": [{"name": "Tech", "weight": 60}, {"name": "Price", "weight": 40}],
                "suppliers": [{"supplier_name": n, "final_rank": r, "ppi": p, "absolute_score": a,
                               "criteria": [{"name": "Tech", "score": t}, {"name": "Price", "score": 5}]}
                              for n, r, p, a, t in rows]}
    before = run("m1", [("A", 1, 100, 80, 8), ("B", 2, 90, 70, 7), ("Gone", 3, 50, 40, 4)])
    now = run("m2", [("B", 1, 100, 85, 9), ("A", 2, 95, 78, 8), ("New", 3, 60, 50, 5)])
    cmp = compare_runs(before, now)
    rows = {r["supplier"]: r for r in cmp["suppliers"]}
    assert [r["supplier"] for r in cmp["suppliers"]] == ["B", "A", "New", "Gone"]  # current rank order
    assert rows["B"]["movement"] == "▲ 1" and rows["A"]["movement"] == "▼ 1"
    assert rows["New"]["movement"] == "new" and rows["Gone"]["movement"] == "removed"
    assert rows["B"]["ppi_change"] == 10 and rows["A"]["absolute_change"] == -2
    assert {"supplier": "B", "criterion": "Tech", "score_before": 7, "score_now": 9, "change": 2} in cmp["criteria"]
    assert "LLM: gemini/m1 → gemini/m2" in cmp["changes"]
    assert "Suppliers added: New" in cmp["changes"] and "Suppliers removed: Gone" in cmp["changes"]
    assert cmp["same_order"] is False


def test_old_databases_are_upgraded_in_place(tmp_path):
    p = str(tmp_path / "old.db")
    conn = sqlite3.connect(p)  # schema from before history support: no source_run_id / pdf_blob
    conn.executescript("""
        CREATE TABLE rfp_runs (rfp_run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
                               llm_provider TEXT, llm_model TEXT, warnings_json TEXT, run_json TEXT);
        CREATE TABLE supplier_results (rfp_run_id TEXT NOT NULL, supplier_name TEXT NOT NULL,
            submission_date TEXT NOT NULL, experience_rating REAL NOT NULL, source_file TEXT,
            status TEXT NOT NULL DEFAULT 'pending', absolute_score REAL, ppi REAL, final_rank INTEGER, result_json TEXT,
            PRIMARY KEY (rfp_run_id, supplier_name));
        INSERT INTO rfp_runs VALUES ('RFP-OLD', '2026-01-01T00:00:00', 'completed', 'mock', 'm', '[]', '{}');
        INSERT INTO supplier_results (rfp_run_id, supplier_name, submission_date, experience_rating, final_rank)
            VALUES ('RFP-OLD', 'Apex', '2026-01-01', 5, 1);""")
    conn.commit()
    conn.close()
    db.init_db(p)
    old = db.list_runs(p)[0]
    assert old["winner"] == "Apex" and not old["can_reevaluate"]  # history kept; no stored PDFs to re-run
    assert db.get_run_inputs("RFP-OLD", p) is None
