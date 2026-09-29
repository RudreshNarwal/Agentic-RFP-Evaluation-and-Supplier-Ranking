"""Compare two completed runs: rank movement, PPI / absolute / per-criterion score changes, and what settings changed."""


def _movement(before, now):
    if before is None:
        return "new"
    if now is None:
        return "removed"
    return f"▲ {before - now}" if now < before else f"▼ {now - before}" if now > before else "="


def _delta(before, now):
    return None if before is None or now is None else round(now - before, 4)


def compare_runs(before, now):
    """before / now: run dicts as stored by the orchestrator. Rows are ordered by the current rank."""
    b = {s["supplier_name"]: s for s in before["suppliers"]}
    n = {s["supplier_name"]: s for s in now["suppliers"]}
    names = sorted(set(b) | set(n), key=lambda x: (n[x]["final_rank"] if x in n else 10**6, x.casefold()))

    suppliers, criteria = [], []
    for name in names:
        x, y = b.get(name), n.get(name)
        get = lambda s, k: s[k] if s else None
        suppliers.append({
            "supplier": name, "rank_before": get(x, "final_rank"), "rank_now": get(y, "final_rank"),
            "movement": _movement(get(x, "final_rank"), get(y, "final_rank")),
            "ppi_before": get(x, "ppi"), "ppi_now": get(y, "ppi"), "ppi_change": _delta(get(x, "ppi"), get(y, "ppi")),
            "absolute_before": get(x, "absolute_score"), "absolute_now": get(y, "absolute_score"),
            "absolute_change": _delta(get(x, "absolute_score"), get(y, "absolute_score")),
        })
        if x and y:
            old = {c["name"]: c["score"] for c in x["criteria"]}
            for c in y["criteria"]:
                if c["name"] in old:
                    criteria.append({"supplier": name, "criterion": c["name"], "score_before": old[c["name"]],
                                     "score_now": c["score"], "change": _delta(old[c["name"]], c["score"])})

    changes = []
    if before["llm"].get("model") != now["llm"].get("model") or before["llm"].get("provider") != now["llm"].get("provider"):
        changes.append(f"LLM: {before['llm']['provider']}/{before['llm']['model']} → {now['llm']['provider']}/{now['llm']['model']}")
    weights_before = {c["name"]: c["weight"] for c in before["criteria"]}
    weights_now = {c["name"]: c["weight"] for c in now["criteria"]}
    for name in sorted(set(weights_before) | set(weights_now)):
        wb, wn = weights_before.get(name), weights_now.get(name)
        if wb != wn:
            changes.append(f"Criterion '{name}': " + ("added" if wb is None else "removed" if wn is None
                                                      else f"weight {wb:g}% → {wn:g}%"))
    added, removed = sorted(set(n) - set(b)), sorted(set(b) - set(n))
    if added:
        changes.append("Suppliers added: " + ", ".join(added))
    if removed:
        changes.append("Suppliers removed: " + ", ".join(removed))
    order_before = [s["supplier_name"] for s in sorted(before["suppliers"], key=lambda s: s["final_rank"])]
    order_now = [s["supplier_name"] for s in sorted(now["suppliers"], key=lambda s: s["final_rank"])]
    return {"suppliers": suppliers, "criteria": criteria, "changes": changes,
            "same_order": [x for x in order_before if x in n] == [x for x in order_now if x in b]}
