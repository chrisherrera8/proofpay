from decimal import Decimal as D

from app.models import Mandate
from app.policy import DEFAULT_RULES, MandateRules, evaluate, get_mandate


def item(label, visible=True, passed=True):
    return {"item": label, "visible": visible, "pass": passed, "confidence": 0.9, "note": ""}


ALL_OK = [item("Kitchen"), item("Bathroom"), item("Floors"), item("Surfaces")]


def rules(**kw):
    base = dict(min_score=D("0.80"), auto_release_ceiling=D("25.00"), required_items=())
    return MandateRules(**{**base, **kw})


def run(amount="10.00", score="1.00", items=ALL_OK, **kw):
    return evaluate(D(amount), D(score), items, rules(**kw))


# --- the seven rules -------------------------------------------------------------------------

def test_all_pass_auto_releases():
    d = run()
    assert d.outcome == "auto_release"
    assert d.reasons


def test_nothing_visible_rejects():
    d = run(score="0.00", items=[item("Kitchen", visible=False), item("Floors", visible=False)])
    assert d.outcome == "reject"
    assert "No checklist item was visible" in d.reasons[0]


def test_empty_items_rejects():
    assert run(score="0.00", items=[]).outcome == "reject"


def test_required_item_failed_rejects():
    d = run(items=[item("Kitchen", passed=False)] + ALL_OK[1:], required_items=("Kitchen",))
    assert d.outcome == "reject"
    assert d.reasons == ["Required item failed: Kitchen"]


def test_score_below_min_rejects():
    d = run(score="0.79")
    assert d.outcome == "reject"
    assert "0.79" in d.reasons[0] and "0.80" in d.reasons[0]


def test_required_item_not_visible_needs_approval():
    items = [item("Kitchen", visible=False)] + ALL_OK[1:]
    d = run(items=items, required_items=("Kitchen",))
    assert d.outcome == "needs_approval"
    assert d.reasons == ["Required item was not visible: Kitchen"]


def test_required_item_missing_from_results_needs_approval():
    d = run(required_items=("Garage",))
    assert d.outcome == "needs_approval"
    assert "Garage" in d.reasons[0]


def test_other_visible_failure_needs_approval_when_score_clears():
    items = [item(f"Room {n}", passed=n != 0) for n in range(5)]  # 1 of 5 failed -> score 0.80
    d = run(score="0.80", items=items)
    assert d.outcome == "needs_approval"
    assert d.reasons == ["Item failed: Room 0"]


def test_not_visible_item_is_not_a_failure():
    items = [item("Kitchen", visible=False, passed=False)] + ALL_OK[1:]
    assert run(items=items).outcome == "auto_release"


def test_amount_over_ceiling_needs_approval():
    d = run(amount="30.00")
    assert d.outcome == "needs_approval"
    assert d.reasons == ["Amount $30.00 is above the auto-release ceiling of $25.00"]


# --- boundaries ------------------------------------------------------------------------------

def test_score_exactly_at_minimum_passes():
    assert run(score="0.80").outcome == "auto_release"


def test_score_just_under_minimum_rejects():
    assert run(score="0.79").outcome == "reject"


def test_amount_exactly_at_ceiling_auto_releases():
    assert run(amount="25.00").outcome == "auto_release"


def test_amount_one_cent_over_ceiling_needs_approval():
    assert run(amount="25.01").outcome == "needs_approval"


# --- required-item matching, reasons, order --------------------------------------------------

def test_required_item_match_is_case_insensitive_and_trimmed():
    items = [item("kitchen", passed=False)] + ALL_OK[1:]
    assert run(items=items, required_items=("  KITCHEN ",)).outcome == "reject"
    ok = run(required_items=("kitchen",))
    assert ok.outcome == "auto_release"


def test_failed_required_item_is_not_also_listed_as_other_failure():
    items = [item("Kitchen", passed=False)] + ALL_OK[1:]
    d = run(score="0.75", items=items, required_items=("Kitchen",))
    assert not any(r.startswith("Item failed") for r in d.reasons)


def test_several_reasons_are_returned_together():
    items = [item("Kitchen", passed=False), item("Bathroom", visible=False)] + ALL_OK[2:]
    d = run(amount="30.00", score="0.50", items=items, required_items=("Kitchen", "Bathroom"))
    assert d.outcome == "reject"
    assert d.reasons == [
        "Required item failed: Kitchen",
        "Score 0.50 is below the minimum of 0.80",
        "Required item was not visible: Bathroom",
        "Amount $30.00 is above the auto-release ceiling of $25.00",
    ]


def test_rule_order_reject_beats_needs_approval():
    # over the ceiling AND under the minimum score: the earlier (reject) rule sets the outcome
    d = run(amount="30.00", score="0.50")
    assert d.outcome == "reject"
    assert d.reasons[0].startswith("Score")
    assert d.reasons[1].startswith("Amount")


def test_rule_order_nothing_visible_comes_first():
    d = run(score="0.00", items=[item("Kitchen", visible=False)], required_items=("Kitchen",))
    assert d.outcome == "reject"
    assert d.reasons[0].startswith("No checklist item")


def test_custom_rules_are_respected():
    assert run(amount="40.00", auto_release_ceiling=D("50.00")).outcome == "auto_release"
    assert run(score="0.90", min_score=D("0.95")).outcome == "reject"


# --- get_mandate -----------------------------------------------------------------------------

def test_get_mandate_defaults_when_table_empty(db):
    assert get_mandate(db) == DEFAULT_RULES
    assert DEFAULT_RULES == MandateRules(D("0.80"), D("25.00"), ())


def test_get_mandate_uses_newest_row(db):
    db.add(Mandate(min_score=D("0.50"), auto_release_ceiling=D("5.00"), required_items=["Old"]))
    db.flush()
    db.add(Mandate(min_score=D("0.90"), auto_release_ceiling=D("50.00"), required_items=["Kitchen", "Floors"]))
    db.flush()
    assert get_mandate(db) == MandateRules(D("0.90"), D("50.00"), ("Kitchen", "Floors"))


def test_get_mandate_null_columns_fall_back_to_defaults(db):
    db.add(Mandate())
    db.flush()
    assert get_mandate(db) == DEFAULT_RULES


def test_as_dict_is_json_friendly():
    assert DEFAULT_RULES.as_dict() == {"min_score": "0.80", "auto_release_ceiling": "25.00", "required_items": []}
