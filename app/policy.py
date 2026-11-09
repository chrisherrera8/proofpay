"""Policy engine: decides what happens to a job after the vision check.

evaluate() is a pure function (no database, no I/O) so the rules can be read and tested on their own.
The LLM never decides: the vision step only reports what it sees per item.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Approval, Job, JobStatus, Mandate, Verification
from app.state_machine import transition

Outcome = Literal["auto_release", "needs_approval", "reject"]


@dataclass(frozen=True)
class MandateRules:
    min_score: Decimal
    auto_release_ceiling: Decimal
    required_items: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "min_score": str(self.min_score),
            "auto_release_ceiling": str(self.auto_release_ceiling),
            "required_items": list(self.required_items),
        }


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: list[str]


DEFAULT_RULES = MandateRules(
    min_score=Decimal("0.80"),
    auto_release_ceiling=Decimal("25.00"),
    required_items=(),
)


def _key(label: object) -> str:
    return str(label).strip().lower()


def _money(v: Decimal) -> str:
    return f"${v:.2f}"


def evaluate(amount: Decimal, score: Decimal, items: list[dict], rules: MandateRules) -> Decision:
    """Apply the seven rules in order. The first rule that matches sets the outcome; every rule that
    matches contributes its reason, so the admin screen can show everything that applies.

    items are the stored verification items: {"item", "visible", "pass", ...}.
    """
    visible = [i for i in items if i.get("visible")]
    required = {_key(r) for r in rules.required_items}
    by_label = {_key(i.get("item", "")): i for i in items}

    # (outcome, reason) for each rule that matches, in rule order.
    hits: list[tuple[Outcome, str]] = []

    if not visible:  # 1
        hits.append(("reject", "No checklist item was visible, so nothing could be verified"))

    for label in rules.required_items:  # 2
        item = by_label.get(_key(label))
        if item is not None and item.get("visible") and not item.get("pass"):
            hits.append(("reject", f"Required item failed: {label}"))

    if score < rules.min_score:  # 3
        hits.append(("reject", f"Score {score} is below the minimum of {rules.min_score}"))

    for label in rules.required_items:  # 4
        item = by_label.get(_key(label))
        if item is None or not item.get("visible"):
            hits.append(("needs_approval", f"Required item was not visible: {label}"))

    for i in visible:  # 5
        if not i.get("pass") and _key(i.get("item", "")) not in required:
            hits.append(("needs_approval", f"Item failed: {i.get('item')}"))

    if amount > rules.auto_release_ceiling:  # 6
        hits.append((
            "needs_approval",
            f"Amount {_money(amount)} is above the auto-release ceiling of {_money(rules.auto_release_ceiling)}",
        ))

    if not hits:  # 7
        return Decision("auto_release", ["All checks passed within the mandate"])
    return Decision(hits[0][0], [reason for _, reason in hits])


def get_mandate(db: Session) -> MandateRules:
    """The newest mandates row, or the built-in defaults if there is none.

    A NULL column in the row falls back to that column's default.
    """
    row = db.scalar(select(Mandate).order_by(Mandate.id.desc()).limit(1))
    if row is None:
        return DEFAULT_RULES
    return MandateRules(
        min_score=Decimal(row.min_score) if row.min_score is not None else DEFAULT_RULES.min_score,
        auto_release_ceiling=(
            Decimal(row.auto_release_ceiling)
            if row.auto_release_ceiling is not None
            else DEFAULT_RULES.auto_release_ceiling
        ),
        required_items=tuple(row.required_items or ()),
    )


_OUTCOME_STATUS = {
    "auto_release": JobStatus.RELEASED,
    "needs_approval": JobStatus.PENDING_APPROVAL,
    "reject": JobStatus.REJECTED,
}


def decide(db: Session, job: Job) -> Decision:
    """Evaluate a VERIFIED job and move it to RELEASED, PENDING_APPROVAL or REJECTED.

    Writes the POLICY_DECIDED audit row (through transition()) and, for needs_approval, a PENDING
    approval, all in the caller's transaction. Does not commit.
    """
    verification = db.scalar(
        select(Verification).where(Verification.job_id == job.id).order_by(Verification.id.desc()).limit(1)
    )
    if verification is None:
        raise ValueError(f"Job {job.id} has no verification to decide on")
    rules = get_mandate(db)
    score = Decimal(verification.score) if verification.score is not None else Decimal("0")
    decision = evaluate(job.amount, score, verification.results.get("items", []), rules)

    transition(
        db, job, _OUTCOME_STATUS[decision.outcome], actor="policy-engine", event="POLICY_DECIDED",
        payload={"outcome": decision.outcome, "reasons": decision.reasons, "rules": rules.as_dict(),
                 "verification_id": verification.id},
    )
    if decision.outcome == "needs_approval":
        db.add(Approval(job_id=job.id, status="PENDING", reason="; ".join(decision.reasons)[:1000]))
        db.flush()
    return decision
