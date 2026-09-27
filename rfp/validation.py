"""Validation Tool: turn whatever the LLM returned into a complete, in-range, evidence-checked scorecard + warnings."""
import json
import math
import re
from typing import Optional

from pydantic import BaseModel, ValidationError


class CriterionResult(BaseModel):
    criterion_id: int
    score: float
    justification: Optional[str] = None  # null text must never invalidate a valid score
    evidence: Optional[str] = None


def parse_json(raw):
    """dict passthrough; strings may be wrapped in ``` fences or have chatter around the object."""
    if raw is None:
        return None, "no LLM output"
    if isinstance(raw, dict):
        return raw, None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip())
    for candidate in (text, (re.search(r"\{.*\}", text, re.S) or [None])[0]):
        if candidate:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data, None
            except json.JSONDecodeError:
                pass
    return None, "LLM output was not valid JSON"


def _plain(s):
    """Lowercase alphanumeric words only, so quotes match despite punctuation, ligatures, line breaks, page tags."""
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\[page \d+\]", " ", s.lower())))


def evidence_in_document(evidence, doc_text):
    """True if every quoted fragment (split on ... or …) of 3+ words appears verbatim in the document, and on the
    cited page(s) when the quote carries [Page N] tags."""
    parts = re.split(r"\[Page (\d+)\]", doc_text)  # ['', '1', text1, '2', text2, ...]
    pages = {int(n): t for n, t in zip(parts[1::2], parts[2::2])}
    cited = [int(n) for n in re.findall(r"\[Page (\d+)\]", evidence, re.I)]
    if cited and any(p not in pages for p in cited):
        return False
    doc = _plain(" ".join(pages[p] for p in cited) if cited else doc_text)
    fragments = [_plain(f) for f in re.split(r"\.\.\.|…", evidence)]
    fragments = [f for f in fragments if len(f.split()) >= 3]
    return bool(fragments) and all(f in doc for f in fragments)


def normalize(raw, criteria, supplier_name, doc_text=None):
    """criteria: active DB rows. Returns (scorecard, warnings). max_score always comes from the DB, never the LLM.
    If doc_text is given, every evidence quote is checked against it (grounding)."""
    warnings = []
    warn = lambda msg: warnings.append(f"{supplier_name}: {msg}")

    data, err = parse_json(raw)
    if err:
        warn(f"{err}; every criterion scored 0.")
    data = data or {}
    items = data.get("criteria")
    if data and not isinstance(items, list):
        warn("'criteria' list missing from LLM output.")
    items = items if isinstance(items, list) else []

    by_id = {c["criterion_id"]: c for c in criteria}
    got, invalid = {}, set()
    for it in items:
        try:
            r = CriterionResult.model_validate(it)
            if not math.isfinite(r.score):
                raise ValueError
        except (ValidationError, ValueError):
            cid = it.get("criterion_id") if isinstance(it, dict) else None
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                warn(f"dropped malformed criterion entry {str(it)[:80]!r}.")
                continue
            if cid in by_id and cid not in got:
                warn(f"criterion {cid} had invalid score {it.get('score')!r}; set to 0.")
                invalid.add(cid)
                got[cid] = CriterionResult(criterion_id=cid, score=0, justification=str(it.get("justification") or ""),
                                           evidence=str(it.get("evidence") or ""))
            continue
        if r.criterion_id not in by_id:
            warn(f"unknown criterion_id {r.criterion_id} dropped.")
        elif r.criterion_id in got:
            warn(f"duplicate result for criterion {r.criterion_id} ignored (first kept).")
        else:
            got[r.criterion_id] = r

    lines = []
    for c in criteria:
        cid, mx = c["criterion_id"], c["max_score"]
        r = got.get(cid)
        if r is None:
            if not err:
                warn(f"criterion {cid} ({c['name']}) missing from LLM output; scored 0.")
            r = CriterionResult(criterion_id=cid, score=0, justification="Not addressed in LLM output.")
            missing = True
        else:
            missing = False
            if not 0 <= r.score <= mx:
                clipped = min(max(r.score, 0), mx)
                warn(f"criterion {cid} score {r.score:g} out of range, clipped to {clipped:g} (0..{mx}).")
                r.score = clipped
        evidence = (r.evidence or "").strip()
        verified = None  # None = not checked (no document text supplied)
        if not missing and not evidence:
            warn(f"criterion {cid} ({c['name']}) has no evidence quote.")
        elif evidence and doc_text is not None:
            verified = evidence_in_document(evidence, doc_text)
            if not verified:
                warn(f"criterion {cid} ({c['name']}) evidence quote not found in the document (possible hallucination).")
        lines.append({"criterion_id": cid, "name": c["name"], "score": float(r.score), "max_score": mx,
                      "justification": (r.justification or "").strip(), "evidence": evidence,
                      "evidence_verified": verified})

    risks = data.get("risks")
    risks = [str(x) for x in risks] if isinstance(risks, list) else ([str(risks)] if risks else [])
    return {
        "criteria": lines,
        "scores": {l["criterion_id"]: l["score"] for l in lines},
        "risks": risks,
        "overall_summary": str(data.get("overall_summary") or ""),
        "answered": sum(1 for cid in got if cid not in invalid),  # criteria with a valid LLM score
    }, warnings
