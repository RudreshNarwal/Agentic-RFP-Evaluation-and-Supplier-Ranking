"""Orchestrator Agent: runs the tools in the required order (brief section 4, steps 3-9) and logs every call."""
import hashlib
import re
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

from rfp import db, evaluation_agent, llm
from rfp.document_tool import extract_text
from rfp.ranking import TIE_BREAK_ORDER, rank_suppliers
from rfp.validation import normalize

FORMULAS = {
    "absolute_score": "sum over criteria of (score / max_score) * weight",
    "benchmark": "highest validated score for the criterion across all suppliers in the run",
    "gap": "score - benchmark (0 for the benchmark leader, otherwise negative)",
    "relative_pct": "score / benchmark * 100; if benchmark == 0 then 0 (no supplier showed evidence, no peer credit)",
    "ppi": "sum(relative_pct * weight) / sum(weight)",
}


def criteria_errors(criteria):
    if not criteria:
        return ["No active evaluation criteria."]
    total = sum(c["weight"] for c in criteria)
    return [] if abs(total - 100) <= 1e-6 else [f"Active criteria weights total {total:g}%, must be 100%."]


def check_inputs(submissions, criteria):
    """Return a list of human-readable errors (empty = OK). Used by the UI too, before anything runs."""
    errors = criteria_errors(criteria)
    if not submissions:
        errors.append("Upload at least one supplier PDF.")
    names = [s["supplier_name"].strip() for s in submissions]
    if any(not n for n in names):
        errors.append("Every supplier needs a name.")
    dupes = sorted({n for n in names if n and [x.casefold() for x in names].count(n.casefold()) > 1})
    if dupes:
        errors.append(f"Duplicate supplier names: {', '.join(dupes)}.")
    for s in submissions:
        try:
            date.fromisoformat(str(s["submission_date"]))
        except ValueError:
            errors.append(f"{s['supplier_name']}: submission date must be YYYY-MM-DD.")
        if not 1 <= float(s["experience_rating"]) <= 10:
            errors.append(f"{s['supplier_name']}: experience rating must be between 1 and 10.")
    return errors


def _extract(sub):
    """Document Tool for one supplier. Returns (text or None, notes, log)."""
    name = sub["supplier_name"]
    try:
        text, pages = extract_text(sub["pdf_bytes"])
    except ValueError as e:
        return None, [f"{name}: evaluation failed ({e}); scored 0."], [("Document Tool", f"{name}: FAILED - unreadable file")]
    log = [("Document Tool", f"{name}: extracted {len(text):,} chars from {pages} page(s)")]
    if len(text) < 200:
        return None, [f"{name}: almost no extractable text ({len(text)} chars) - scanned/image PDF? LLM skipped."], log
    return text, [], log


def _name_re(name):
    """Whole-word match of a supplier name ("Nova" must not match inside "innovative")."""
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.I)


def _fingerprint(text, name):
    """Document identity with the supplier's own name masked, so identical proposals match across suppliers."""
    masked = _name_re(name).sub("<SUPPLIER>", text)
    return hashlib.sha256(" ".join(masked.split()).encode()).hexdigest()


def redact(message, creds):
    """Remove an API key from error text before it is shown, stored in SQLite or exported."""
    key = (creds or {}).get("api_key")
    return message.replace(key, "***") if key else message


def _evaluate_doc(name, text, criteria, provider, model, creds):
    """Evaluation Agent -> Validation Tool (-> one self-correction round). Never raises."""
    log, notes, raw, repair = [], [], None, None
    if text is not None:
        try:
            raw, notes = evaluation_agent.evaluate(text, criteria, name, provider, model, **creds)
            log.append(("Evaluation Agent", f"{name}: {provider}/{model} returned a scorecard"))
        except Exception as e:  # network/API error, bad key, refusal...
            notes.append(f"{name}: evaluation failed ({type(e).__name__}: {redact(str(e), creds)[:200]}); scored 0.")
            log.append(("Evaluation Agent", f"{name}: FAILED - {type(e).__name__}"))

    card, warnings = normalize(raw, criteria, name, doc_text=text)
    log.append(("Validation Tool", f"{name}: {len(warnings)} issue(s), "
                f"{sum(bool(c['evidence_verified']) for c in card['criteria'])}/{len(criteria)} evidence quotes verified"))

    fixable = [w for w in warnings if "has no evidence quote" not in w]  # "" evidence is allowed by the prompt
    if raw is not None and fixable and provider != "mock":
        # Agentic self-correction: feed the validator's findings back to the Evaluation Agent once.
        try:
            raw2 = evaluation_agent.repair(text, criteria, name, raw, fixable, provider, model, **creds)
            card2, warnings2 = normalize(raw2, criteria, name, doc_text=text)
            repair = {"issues_before": warnings, "issues_after": warnings2,
                      "accepted": _quality(card2, warnings2) > _quality(card, warnings)}
            if repair["accepted"]:
                card, warnings = card2, warnings2
            log.append(("Evaluation Agent", f"{name}: self-correction {len(repair['issues_before'])} -> "
                        f"{len(warnings2)} issue(s), {'accepted' if repair['accepted'] else 'kept first answer'}"))
        except Exception as e:
            log.append(("Evaluation Agent", f"{name}: self-correction failed - {type(e).__name__}"))
    return {"card": card, "warnings": notes + warnings, "log": log, "repair": repair, "failed": raw is None}


def _quality(card, warnings):
    """Compare scorecards on substance: criteria validly answered, then verified quotes, then fewest issues."""
    return card["answered"], sum(bool(c["evidence_verified"]) for c in card["criteria"]), -len(warnings)


def _share_scorecard(original, from_name, to_name, text, criteria):
    """Reuse a scorecard for an identical document: swap the supplier name, re-check evidence against this PDF."""
    swap = lambda v: _name_re(from_name).sub(to_name, v)
    raw = {"criteria": [{**c, "justification": swap(c["justification"]), "evidence": swap(c["evidence"])}
                        for c in original["card"]["criteria"]],
           "risks": [swap(r) for r in original["card"]["risks"]], "overall_summary": swap(original["card"]["overall_summary"])}
    card, warnings = normalize(raw, criteria, to_name, doc_text=text)
    note = (f"{to_name}: proposal text is identical to {from_name}'s (supplier name aside), so the same scorecard "
            f"was applied - identical documents must score identically. Review for a duplicate or collusive bid.")
    return {"card": card, "warnings": [note] + warnings, "log": [("Orchestrator", note.split(" Review")[0])],
            "repair": None, "failed": original["failed"]}


def run_batch(submissions, db_path=None, provider=None, model=None, on_progress=None, credentials=None):
    """submissions: [{supplier_name, submission_date (ISO str), experience_rating, pdf_bytes, filename}].
    credentials: optional {"api_key", "vertex"} for this run only (e.g. entered in the UI); never persisted."""
    creds = {k: v for k, v in (credentials or {}).items() if v is not None and v != ""}
    if provider is None:
        provider, model = llm.config()
    progress = on_progress or (lambda msg: None)
    steps = []

    def log(tool, detail):
        steps.append({"step": len(steps) + 1, "tool": tool, "detail": detail})
        progress(f"**{tool}** · {detail}")

    errors = check_inputs(submissions, db.get_criteria(db_path))
    if errors:
        raise ValueError(" ".join(errors))
    for s in submissions:
        s["supplier_name"] = s["supplier_name"].strip()

    now = datetime.now()
    run_id = f"RFP-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    db.create_run(run_id, now.isoformat(timespec="seconds"), provider, model, submissions, db_path)
    log("Orchestrator", f"batch {run_id} created with {len(submissions)} pending supplier entries")
    try:
        criteria = db.get_criteria(db_path)  # step 4: reload so the run uses the latest active criteria
        if errors := criteria_errors(criteria):  # criteria may have been edited since the input check
            raise ValueError(" ".join(errors))
        log("Orchestrator", f"reloaded {len(criteria)} active criteria (weights total 100%)")

        # Step 4a - Document Tool for every supplier.
        extracted = [_extract(sub) for sub in submissions]
        # Step 4b - consistency guard: evaluate each distinct document once (supplier name masked).
        first_of, groups = {}, []
        for i, (sub, (text, _, _)) in enumerate(zip(submissions, extracted)):
            key = _fingerprint(text, sub["supplier_name"]) if text else f"unique-{i}"
            first_of.setdefault(key, i)
            groups.append(first_of[key])
        unique = sorted(set(groups))
        # Step 4c/5 - Evaluation Agent + Validation Tool, in parallel; report each as it finishes.
        results = {}
        with ThreadPoolExecutor(max_workers=min(4, len(unique))) as ex:
            futures = {ex.submit(_evaluate_doc, submissions[i]["supplier_name"], extracted[i][0], criteria, provider, model, creds): i
                       for i in unique}
            for done, f in enumerate(as_completed(futures), start=1):
                results[futures[f]] = f.result()
                progress(f"✓ {submissions[futures[f]]['supplier_name']} evaluated ({done}/{len(unique)} distinct documents)")
        outputs = []
        for i, (sub, (text, notes, xlog)) in enumerate(zip(submissions, extracted)):
            out = results[i] if groups[i] == i else _share_scorecard(
                results[groups[i]], submissions[groups[i]]["supplier_name"], sub["supplier_name"], text, criteria)
            outputs.append({**out, "warnings": notes + out["warnings"], "log": xlog + out["log"]})
        warnings = []
        for out in outputs:
            warnings += out["warnings"]
            for tool, detail in out["log"]:
                log(tool, detail)
        backend = None
        if provider == "gemini":
            backend, note = llm.gemini_backend(**creds)
            if note:
                warnings.append(note)
        if all(o["failed"] for o in outputs):
            warnings.append("No supplier could be evaluated; the ranking below only reflects tie-break rules.")

        ranked = rank_suppliers(criteria, [
            {"supplier_name": s["supplier_name"], "submission_date": s["submission_date"],
             "experience_rating": float(s["experience_rating"]), "scores": o["card"]["scores"]}
            for s, o in zip(submissions, outputs)])
        log("Ranking Tool", "absolute scores, benchmarks, gaps, relative %, PPI, tie-breaks and ranks computed")

        details = {s["supplier_name"]: (s, o) for s, o in zip(submissions, outputs)}
        for row in ranked["suppliers"]:
            sub, out = details[row["supplier_name"]]
            evidence = {c["criterion_id"]: c for c in out["card"]["criteria"]}
            for line in row["criteria"]:
                e = evidence[line["criterion_id"]]
                line.update(justification=e["justification"], evidence=e["evidence"],
                            evidence_verified=e["evidence_verified"])
            row.update(source_file=sub.get("filename", ""), evaluation_status="failed" if out["failed"] else "ok",
                       risks=out["card"]["risks"], overall_summary=out["card"]["overall_summary"],
                       warnings=out["warnings"], self_correction=out["repair"])

        run = {
            "rfp_run_id": run_id, "created_at": now.isoformat(timespec="seconds"), "status": "completed",
            "llm": {"provider": provider, "model": model, **({"backend": backend} if backend else {})},
            "criteria": criteria, "formulas": FORMULAS, "tie_break_order": TIE_BREAK_ORDER,
            "benchmarks": {str(k): v for k, v in ranked["benchmarks"].items()},
            "suppliers": ranked["suppliers"], "warnings": warnings, "steps": steps,
        }
        log("Orchestrator", "persisting scored supplier entries + run JSON to SQLite")
        db.complete_run(run, db_path)
        return run
    except Exception as e:
        db.fail_run(run_id, f"{type(e).__name__}: {redact(str(e), creds)}", db_path)
        raise
