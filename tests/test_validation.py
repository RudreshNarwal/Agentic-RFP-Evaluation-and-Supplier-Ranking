from rfp.validation import normalize

CRITERIA = [
    {"criterion_id": 1, "name": "Tech", "weight": 60, "max_score": 10},
    {"criterion_id": 2, "name": "Price", "weight": 40, "max_score": 10},
]


def item(cid, score, **kw):
    return {"criterion_id": cid, "score": score, "max_score": 10, "justification": "j", "evidence": "e", **kw}


def test_clean_output_passes_without_warnings():
    card, warnings = normalize({"criteria": [item(1, 8), item(2, 6)], "risks": ["r"], "overall_summary": "s"}, CRITERIA, "S")
    assert warnings == []
    assert card["scores"] == {1: 8.0, 2: 6.0}
    assert card["risks"] == ["r"] and card["overall_summary"] == "s"


def test_json_string_and_code_fences_are_parsed():
    raw = '```json\n{"criteria": [{"criterion_id": 1, "score": 7, "justification": "j", "evidence": "e"}, {"criterion_id": 2, "score": 5, "justification": "j", "evidence": "e"}]}\n```'
    card, warnings = normalize(raw, CRITERIA, "S")
    assert card["scores"] == {1: 7.0, 2: 5.0} and warnings == []


def test_malformed_json_zero_fills_every_criterion_with_warning():
    card, warnings = normalize("this is not json {", CRITERIA, "S")
    assert card["scores"] == {1: 0.0, 2: 0.0}
    assert any("not valid JSON" in w for w in warnings)


def test_missing_criterion_is_filled_with_zero():
    card, warnings = normalize({"criteria": [item(1, 8)]}, CRITERIA, "S")
    assert card["scores"][2] == 0.0
    assert any("criterion 2" in w and "missing" in w for w in warnings)


def test_out_of_range_scores_are_clipped():
    card, warnings = normalize({"criteria": [item(1, 14), item(2, -3)]}, CRITERIA, "S")
    assert card["scores"] == {1: 10.0, 2: 0.0}
    assert sum("clipped" in w for w in warnings) == 2


def test_non_numeric_score_unknown_id_and_duplicate():
    raw = {"criteria": [item(1, "eight"), item(2, 5), item(2, 9), item(99, 5)]}
    card, warnings = normalize(raw, CRITERIA, "S")
    assert card["scores"] == {1: 0.0, 2: 5.0}  # bad score -> 0, duplicate -> first kept, unknown id dropped
    text = " ".join(warnings)
    assert "criterion 1" in text and "duplicate" in text and "unknown criterion_id 99" in text


def test_numeric_string_score_is_accepted_and_max_score_comes_from_db():
    card, warnings = normalize({"criteria": [item(1, "7", max_score=100), item(2, 6)]}, CRITERIA, "S")
    assert card["scores"][1] == 7.0 and warnings == []
    assert {c["criterion_id"]: c["max_score"] for c in card["criteria"]} == {1: 10, 2: 10}


def test_missing_evidence_is_warned():
    card, warnings = normalize({"criteria": [item(1, 8, evidence=""), item(2, 6)]}, CRITERIA, "S")
    assert card["scores"][1] == 8.0
    assert any("no evidence" in w for w in warnings)


def test_none_input_zero_fills():
    card, warnings = normalize(None, CRITERIA, "S")
    assert card["scores"] == {1: 0.0, 2: 0.0} and warnings


def test_null_text_fields_keep_a_valid_score():
    card, warnings = normalize({"criteria": [item(1, 8, justification=None, evidence="e"), item(2, 6, evidence=None)]},
                               CRITERIA, "S")
    assert card["scores"] == {1: 8.0, 2: 6.0}
    assert not any("invalid score" in w for w in warnings)
    assert any("criterion 2" in w and "no evidence" in w for w in warnings)


def test_clipped_score_still_gets_evidence_check():
    card, warnings = normalize({"criteria": [item(1, 12, evidence=""), item(2, 6)]}, CRITERIA, "S")
    assert card["scores"][1] == 10.0
    assert any("clipped" in w for w in warnings) and any("criterion 1" in w and "no evidence" in w for w in warnings)


DOC = "[Page 1]\nWe hold ISO/IEC 27001:2022 certification and\nencrypt data with AES-256 at rest.\n[Page 2]\nPricing: $540,000 licence."


def test_evidence_grounding_accepts_real_quotes_and_flags_invented_ones():
    raw = {"criteria": [item(1, 8, evidence='[Page 1] "We hold ISO/IEC 27001:2022 certification and encrypt data" ... AES-256 at rest'),
                        item(2, 6, evidence="SOC 2 Type II report available on request")]}
    card, warnings = normalize(raw, CRITERIA, "S", doc_text=DOC)
    verified = {c["criterion_id"]: c["evidence_verified"] for c in card["criteria"]}
    assert verified == {1: True, 2: False}
    assert card["scores"] == {1: 8.0, 2: 6.0}  # grounding warns, it doesn't silently change the LLM's judgment
    assert any("criterion 2" in w and "not found in the document" in w for w in warnings)


def test_wrong_page_tag_or_missing_page_is_not_verified():
    ok = "[Page 1] We hold ISO/IEC 27001:2022 certification and"
    wrong_page = "[Page 2] We hold ISO/IEC 27001:2022 certification and"
    no_such_page = "[Page 9] 27001 certified and"
    raw = {"criteria": [item(1, 8, evidence=ok), item(2, 6, evidence=wrong_page)]}
    card, _ = normalize(raw, CRITERIA, "S", doc_text=DOC)
    assert [c["evidence_verified"] for c in card["criteria"]] == [True, False]
    card, _ = normalize({"criteria": [item(1, 8, evidence=no_such_page), item(2, 6)]}, CRITERIA, "S", doc_text=DOC)
    assert card["criteria"][0]["evidence_verified"] is False
