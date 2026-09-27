"""Ranking Tool: deterministic scoring, peer benchmarks, PPI, tie-breaks, ranks. No LLM here."""

TIE_BREAK_ORDER = [
    "1) Higher PPI",
    "2) Earlier submission date",
    "3) Higher historical experience rating",
    "4) Supplier name (A→Z, case-insensitive)",
]


def relative_pct(score, benchmark):
    # Benchmark 0 means no supplier showed anything for this criterion, so nobody earns peer credit (0%).
    # Everyone gets the same value, so the criterion can't change the order, and a failed batch can't show PPI 100.
    return 0.0 if benchmark == 0 else score / benchmark * 100


def _sort_key(r):
    # PPI is rounded to 4 dp before comparing so float noise can't break a genuine tie.
    # Name is compared case-insensitively ("apex" and "Apex" sort together); exact name breaks any remaining tie.
    return (-r["ppi"], r["submission_date"], -r["experience_rating"], r["supplier_name"].casefold(), r["supplier_name"])


def _why_above(a, b):
    if a["ppi"] != b["ppi"]:
        return f"higher PPI ({a['ppi']:.2f} vs {b['ppi']:.2f})"
    if a["submission_date"] != b["submission_date"]:
        return f"PPI tie, earlier submission date ({a['submission_date']} vs {b['submission_date']})"
    if a["experience_rating"] != b["experience_rating"]:
        return f"PPI and date tie, higher experience rating ({a['experience_rating']} vs {b['experience_rating']})"
    return "PPI, date and rating tie, supplier name ascending"


def rank_suppliers(criteria, suppliers):
    """criteria: [{criterion_id, name, weight, max_score}]; suppliers: [{supplier_name, submission_date,
    experience_rating, scores: {criterion_id: validated score}}]. Returns benchmarks + ranked supplier rows."""
    total_weight = sum(c["weight"] for c in criteria)
    benchmarks = {c["criterion_id"]: max(s["scores"][c["criterion_id"]] for s in suppliers) for c in criteria}

    rows = []
    for s in suppliers:
        lines, absolute, weighted_rel = [], 0.0, 0.0
        for c in criteria:
            cid, w, mx = c["criterion_id"], c["weight"], c["max_score"]
            score, bench = s["scores"][cid], benchmarks[cid]
            rel = relative_pct(score, bench)
            points = score / mx * w
            absolute += points
            weighted_rel += rel * w
            lines.append({
                "criterion_id": cid, "name": c["name"], "weight": w, "max_score": mx, "score": score,
                "weighted_points": round(points, 4), "benchmark": bench, "gap": score - bench,
                "relative_pct": round(rel, 4),
            })
        rows.append({
            "supplier_name": s["supplier_name"],
            "submission_date": str(s["submission_date"]),
            "experience_rating": s["experience_rating"],
            "absolute_score": round(absolute, 4),
            "ppi": round(weighted_rel / total_weight, 4),
            "criteria": lines,
        })

    rows.sort(key=_sort_key)
    for i, r in enumerate(rows):
        r["final_rank"] = i + 1
        if len(rows) == 1:
            r["tie_break_note"] = "Only supplier in the batch."
        elif i + 1 < len(rows):
            r["tie_break_note"] = f"Ranked above {rows[i + 1]['supplier_name']}: {_why_above(r, rows[i + 1])}."
        else:
            r["tie_break_note"] = f"Last place; {rows[i - 1]['supplier_name']} ranks above it on {_why_above(rows[i - 1], r)}."
    return {"benchmarks": benchmarks, "suppliers": rows}
