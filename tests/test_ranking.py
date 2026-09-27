import pytest

from rfp.ranking import rank_suppliers

CRITERIA = [
    {"criterion_id": 1, "name": "A", "weight": 60, "max_score": 10},
    {"criterion_id": 2, "name": "B", "weight": 40, "max_score": 10},
]


def sup(name, a, b, date="2026-01-10", rating=3):
    return {"supplier_name": name, "submission_date": date, "experience_rating": rating, "scores": {1: a, 2: b}}


def by_name(results):
    return {r["supplier_name"]: r for r in results}


def test_hand_computed_scores_benchmarks_gaps_and_ppi():
    # Benchmarks: A=8 (S1), B=10 (S2)
    res = rank_suppliers(CRITERIA, [sup("S2", 4, 10), sup("S1", 8, 5)])
    r = by_name(res["suppliers"])
    assert res["benchmarks"] == {1: 8, 2: 10}

    assert r["S1"]["absolute_score"] == pytest.approx(68.0)  # 0.8*60 + 0.5*40
    assert r["S2"]["absolute_score"] == pytest.approx(64.0)  # 0.4*60 + 1.0*40
    assert r["S1"]["ppi"] == pytest.approx(80.0)  # (100*60 + 50*40) / 100
    assert r["S2"]["ppi"] == pytest.approx(70.0)  # (50*60 + 100*40) / 100

    s1 = {c["criterion_id"]: c for c in r["S1"]["criteria"]}
    assert s1[1]["gap"] == 0 and s1[1]["relative_pct"] == pytest.approx(100.0)
    assert s1[2]["gap"] == -5 and s1[2]["relative_pct"] == pytest.approx(50.0)

    assert [s["supplier_name"] for s in res["suppliers"]] == ["S1", "S2"]
    assert [s["final_rank"] for s in res["suppliers"]] == [1, 2]


def test_zero_benchmark_is_safe_and_gives_no_peer_credit():
    res = rank_suppliers(CRITERIA, [sup("X", 5, 0), sup("Y", 10, 0)])
    x = by_name(res["suppliers"])["X"]
    b = {c["criterion_id"]: c for c in x["criteria"]}[2]
    assert b["benchmark"] == 0 and b["relative_pct"] == 0.0 and b["gap"] == 0
    assert x["ppi"] == pytest.approx(50 * 0.6)


def test_all_zero_batch_cannot_show_a_perfect_ppi():
    res = rank_suppliers(CRITERIA, [sup("X", 0, 0), sup("Y", 0, 0)])
    assert all(s["ppi"] == 0 and s["absolute_score"] == 0 for s in res["suppliers"])


def test_name_tie_break_is_case_insensitive():
    res = rank_suppliers(CRITERIA, [sup("zeta", 5, 5), sup("Beta", 5, 5), sup("alpha", 5, 5)])
    assert [s["supplier_name"] for s in res["suppliers"]] == ["alpha", "Beta", "zeta"]


def test_tie_break_order_ppi_then_date_then_rating_then_name():
    same = (5, 5)  # identical scores -> identical PPI for everyone
    res = rank_suppliers(CRITERIA, [
        sup("Zeta", *same, date="2026-01-05", rating=2),   # earliest date -> 1st
        sup("Delta", *same, date="2026-01-09", rating=4),  # same date as others below, highest rating -> 2nd
        sup("Beta", *same, date="2026-01-09", rating=3),   # rating 3, name Beta < Gamma -> 3rd
        sup("Gamma", *same, date="2026-01-09", rating=3),  # -> 4th
        sup("Alpha", 9, 9, date="2026-02-01", rating=1),   # higher PPI beats everything -> overall 1st
    ])
    assert [s["supplier_name"] for s in res["suppliers"]] == ["Alpha", "Zeta", "Delta", "Beta", "Gamma"]
    assert [s["final_rank"] for s in res["suppliers"]] == [1, 2, 3, 4, 5]
    notes = [s["tie_break_note"] for s in res["suppliers"]]
    assert "higher PPI" in notes[0]
    assert "earlier submission date" in notes[1]
    assert "higher experience rating" in notes[2]
    assert "supplier name" in notes[3]


def test_float_noise_does_not_break_ppi_ties():
    crit = [{"criterion_id": i, "name": str(i), "weight": w, "max_score": 10} for i, w in [(1, 30), (2, 20), (3, 20), (4, 20), (5, 10)]]
    a = {"supplier_name": "B-late", "submission_date": "2026-01-02", "experience_rating": 3, "scores": {1: 7, 2: 7, 3: 7, 4: 7, 5: 7}}
    b = {"supplier_name": "A-early", "submission_date": "2026-01-01", "experience_rating": 3, "scores": {1: 7, 2: 7, 3: 7, 4: 7, 5: 7}}
    res = rank_suppliers(crit, [a, b])
    assert [s["supplier_name"] for s in res["suppliers"]] == ["A-early", "B-late"]


def test_same_inputs_same_output():
    sups = [sup("S1", 8, 5), sup("S2", 4, 10), sup("S3", 6, 6)]
    assert rank_suppliers(CRITERIA, sups) == rank_suppliers(CRITERIA, list(reversed(sups)))
