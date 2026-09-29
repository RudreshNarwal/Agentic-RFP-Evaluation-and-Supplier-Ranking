"""End-to-end: sample PDFs -> orchestrator (mock LLM) -> SQLite."""
from pathlib import Path

import pymupdf
import pytest

from rfp import db
from rfp.orchestrator import run_batch

PDFS = Path(__file__).resolve().parent.parent / "sample_pdfs"
# supplier -> (file, submission date, experience rating 1-10), as stated in each PDF
META = {"Apex Systems": ("apex_systems.pdf", "2026-08-20", 8), "BrightPath Tech": ("brightpath_tech.pdf", "2026-08-25", 5),
        "NexaWorks": ("nexaworks.pdf", "2026-08-18", 9), "Orbit Digital": ("orbit_digital.pdf", "2026-08-21", 10)}


def subs(extra=()):
    out = [{"supplier_name": n, "submission_date": d, "experience_rating": r, "filename": f,
            "pdf_bytes": (PDFS / f).read_bytes()} for n, (f, d, r) in META.items()]
    return out + list(extra)


def image_only_pdf():
    """A 'scanned' proposal: drawings only, no text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    for y in range(100, 700, 20):
        page.draw_line((72, y), (500, y), width=6)
    return doc.tobytes()


@pytest.fixture
def dbp(tmp_path):
    p = str(tmp_path / "t.db")
    db.init_db(p)
    return p


def test_full_run_is_persisted_and_deterministic(dbp):
    a = run_batch(subs(), db_path=dbp, provider="mock", model="m")
    b = run_batch(list(reversed(subs())), db_path=dbp, provider="mock", model="m")
    strip = lambda run: [(s["supplier_name"], s["final_rank"], s["absolute_score"], s["ppi"]) for s in run["suppliers"]]
    assert strip(a) == strip(b)
    assert [s["final_rank"] for s in a["suppliers"]] == [1, 2, 3, 4]
    assert all(len(s["criteria"]) == 5 and all(c["justification"] for c in s["criteria"]) for s in a["suppliers"])

    assert db.load_run(a["rfp_run_id"], dbp) == a
    runs = db.list_runs(dbp)
    assert len(runs) == 2 and all(r["status"] == "completed" for r in runs)
    with db.connect(dbp) as conn:
        assert conn.execute("SELECT COUNT(*) FROM supplier_results WHERE rfp_run_id=?", (a["rfp_run_id"],)).fetchone()[0] == 4


def test_image_only_and_corrupt_pdfs_become_warnings_not_crashes(dbp):
    bad = [{"supplier_name": "Scanned Co", "submission_date": "2026-03-01", "experience_rating": 3, "filename": "s.pdf",
            "pdf_bytes": image_only_pdf()},
           {"supplier_name": "Broken Co", "submission_date": "2026-03-01", "experience_rating": 3, "filename": "b.pdf",
            "pdf_bytes": b"not a pdf at all"}]
    run = run_batch(subs(bad), db_path=dbp, provider="mock", model="m")
    last_two = {s["supplier_name"] for s in run["suppliers"][-2:]}
    assert last_two == {"Scanned Co", "Broken Co"}
    text = " ".join(run["warnings"])
    assert "Scanned Co: almost no extractable text" in text and "Broken Co: evaluation failed" in text


def test_llm_exception_is_contained(dbp, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API down")
    monkeypatch.setattr("rfp.llm.complete_json", boom)
    run = run_batch(subs(), db_path=dbp, provider="anthropic", model="x")
    assert all(s["absolute_score"] == 0 for s in run["suppliers"])
    assert sum("API down" in w for w in run["warnings"]) == 4
    # all tied at PPI 0 (every benchmark is 0) -> earliest submission date decides
    assert [s["supplier_name"] for s in run["suppliers"]] == ["NexaWorks", "Apex Systems", "Orbit Digital", "BrightPath Tech"]


def test_invalid_inputs_rejected_before_run(dbp):
    with pytest.raises(ValueError, match="Duplicate supplier names"):
        run_batch(subs() + subs()[:1], db_path=dbp, provider="mock", model="m")
    with db.connect(dbp) as conn:
        conn.execute("UPDATE evaluation_criteria SET weight = 50 WHERE criterion_id = 1")
    with pytest.raises(ValueError, match="must be 100%"):
        run_batch(subs(), db_path=dbp, provider="mock", model="m")
    assert db.list_runs(dbp) == []


def test_supplier_entries_created_at_batch_step_and_marked_failed_on_crash(dbp, monkeypatch):
    def crash(*a, **k):
        raise RuntimeError("ranking exploded")
    monkeypatch.setattr("rfp.orchestrator.rank_suppliers", crash)
    with pytest.raises(RuntimeError):
        run_batch(subs(), db_path=dbp, provider="mock", model="m")
    run = db.list_runs(dbp)[0]
    rows = db.get_supplier_rows(run["rfp_run_id"], dbp)
    assert run["status"] == "failed" and len(rows) == 4
    assert all(r["status"] == "failed" and r["ppi"] is None for r in rows)


def test_self_correction_fixes_a_bad_first_answer(dbp, monkeypatch):
    """First LLM answer skips criteria and invents evidence; the validator's issues go back to the agent, which fixes them."""
    import json
    from rfp import db as _db
    crit = _db.get_criteria(dbp)
    calls = []

    def fake_llm(system, prompt, schema, provider, model, **kw):
        calls.append(prompt)
        if "automated validator" not in prompt:
            return json.dumps({"criteria": [{"criterion_id": 1, "score": 9, "max_score": 10,
                                             "justification": "j", "evidence": "quantum blockchain synergy platform"}]})
        return json.dumps({"criteria": [{"criterion_id": c["criterion_id"], "score": 7, "max_score": 10, "justification": "j",
                                         "evidence": "[Page 1] Balanced solution focused on implementation predictability"}
                                        for c in crit], "risks": [], "overall_summary": "s"})
    monkeypatch.setattr("rfp.llm.complete_json", fake_llm)
    run = run_batch(subs()[2:3], db_path=dbp, provider="gemini", model="x")  # NexaWorks only
    s = run["suppliers"][0]
    assert len(calls) == 2 and "not found in the document" in calls[1] and "missing from LLM output" in calls[1]
    assert s["self_correction"]["accepted"] and s["self_correction"]["issues_after"] == []
    assert all(c["score"] == 7 and c["evidence_verified"] for c in s["criteria"])


def test_non_iso_date_rejected(dbp):
    bad = subs()
    bad[0]["submission_date"] = "02/03/2026"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_batch(bad, db_path=dbp, provider="mock", model="m")


TWINS = {"Delta Analytics": ("2026-02-20", 3), "Echo Analytics": ("2026-02-24", 5),
         "Foxtrot Analytics": ("2026-02-24", 3), "Golf Analytics": ("2026-02-24", 3)}


def test_identical_proposals_share_one_scorecard_and_tie_breaks_2_to_4_decide(dbp, monkeypatch):
    import rfp.evaluation_agent as ea
    calls = []
    real = ea.evaluate
    monkeypatch.setattr(ea, "evaluate", lambda *a, **k: (calls.append(a[2]), real(*a, **k))[1])
    same = (PDFS / "nexaworks.pdf").read_bytes()  # identical document submitted under four names
    twins = [{"supplier_name": n, "submission_date": d, "experience_rating": r, "filename": f"{n}.pdf", "pdf_bytes": same}
             for n, (d, r) in TWINS.items()]
    run = run_batch(list(reversed(twins)), db_path=dbp, provider="mock", model="m")
    sup = run["suppliers"]
    assert len(calls) == 1  # evaluated once, shared three times
    assert len({s["ppi"] for s in sup}) == 1 and all(s["evaluation_status"] == "ok" for s in sup)
    assert [s["supplier_name"] for s in sup] == ["Delta Analytics", "Echo Analytics", "Foxtrot Analytics", "Golf Analytics"]
    assert "earlier submission date" in sup[0]["tie_break_note"]
    assert "higher experience rating" in sup[1]["tie_break_note"]
    assert "supplier name" in sup[2]["tie_break_note"]
    assert sum("identical to" in w for w in run["warnings"]) == 3
    assert all(c["evidence_verified"] for s in sup for c in s["criteria"] if c["evidence"])  # re-checked per PDF


def _fake_llm(first, second):
    import json
    def fake(system, prompt, schema, provider, model, **kw):
        return json.dumps(second) if "automated validator" in prompt else (first if isinstance(first, str) else json.dumps(first))
    return fake


GOOD = "[Page 1] Balanced solution focused on implementation predictability"


def test_repair_of_invalid_json_is_accepted_even_with_some_unverified_quotes(dbp, monkeypatch):
    crit = db.get_criteria(dbp)
    repaired = {"criteria": [{"criterion_id": c["criterion_id"], "score": 6, "max_score": 10, "justification": "j",
                              "evidence": GOOD if c["criterion_id"] > 2 else "invented words that are not there"}
                             for c in crit], "risks": [], "overall_summary": "s"}
    monkeypatch.setattr("rfp.llm.complete_json", _fake_llm("not json at all {", repaired))
    s = run_batch(subs()[2:3], db_path=dbp, provider="gemini", model="x")["suppliers"][0]
    assert s["self_correction"]["accepted"] and all(c["score"] == 6 for c in s["criteria"])


def test_worse_repair_that_drops_a_criterion_is_rejected(dbp, monkeypatch):
    crit = db.get_criteria(dbp)
    first = {"criteria": [{"criterion_id": c["criterion_id"], "score": 9, "max_score": 10, "justification": "j",
                           "evidence": GOOD if c["criterion_id"] > 1 else "made up claim about quantum synergy"}
                          for c in crit], "risks": [], "overall_summary": "s"}
    worse = {**first, "criteria": [c for c in first["criteria"] if c["criterion_id"] != 1]}
    monkeypatch.setattr("rfp.llm.complete_json", _fake_llm(first, worse))
    s = run_batch(subs()[2:3], db_path=dbp, provider="gemini", model="x")["suppliers"][0]
    assert not s["self_correction"]["accepted"] and all(c["score"] == 9 for c in s["criteria"])


def test_blank_evidence_alone_does_not_trigger_a_repair_call(dbp, monkeypatch):
    crit = db.get_criteria(dbp)
    answer = {"criteria": [{"criterion_id": c["criterion_id"], "score": 2, "max_score": 10, "justification": "not covered",
                            "evidence": ""} for c in crit], "risks": [], "overall_summary": "s"}
    calls = []
    monkeypatch.setattr("rfp.llm.complete_json", lambda *a, **k: (calls.append(1), __import__("json").dumps(answer))[1])
    run_batch(subs()[2:3], db_path=dbp, provider="gemini", model="x")
    assert len(calls) == 1


def test_failed_supplier_rows_are_marked_failed_in_sqlite(dbp):
    bad = [{"supplier_name": "Scanned Co", "submission_date": "2026-03-01", "experience_rating": 3, "filename": "s.pdf",
            "pdf_bytes": image_only_pdf()}]
    run = run_batch(subs(bad), db_path=dbp, provider="mock", model="m")
    status = {r["supplier_name"]: r["status"] for r in db.get_supplier_rows(run["rfp_run_id"], dbp)}
    assert status["Scanned Co"] == "failed" and status["NexaWorks"] == "scored"


def test_name_masking_is_whole_word():
    from rfp.orchestrator import _fingerprint
    body = "An innovative platform. {} Proposal."
    assert _fingerprint(body.format("Nova"), "Nova") == _fingerprint(body.format("Apex"), "Apex")
