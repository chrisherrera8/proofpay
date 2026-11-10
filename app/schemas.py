import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.checklists import CHECKLIST_TEMPLATES
from app.pricing import TIER_PRICES

ServiceType = Literal[tuple(CHECKLIST_TEMPLATES)]  # type: ignore[valid-type]


class JobCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    address: str = Field(min_length=1, max_length=500)
    service_type: ServiceType
    cleaner_id: uuid.UUID
    # The cleaner is booked for this whole day; there are no time slots.
    service_date: date
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: Literal["USD"] = "USD"

    @field_validator("service_date")
    @classmethod
    def _not_in_the_past(cls, v: date) -> date:
        # One day of slack, because the customer's local "today" can be a day behind or ahead of UTC.
        if v < datetime.now(timezone.utc).date() - timedelta(days=1):
            raise ValueError("service_date can't be in the past")
        return v

    @model_validator(mode="after")
    def _price_matches_tier(self) -> "JobCreate":
        expected = TIER_PRICES[self.service_type]
        if self.amount != expected:
            raise ValueError(f"amount for {self.service_type} must be {expected}")
        return self


class CleanerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trim before the length and pattern checks

    name: str = Field(min_length=1, max_length=200)
    paypal_email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CleanerOut(BaseModel):
    """Public view: the PayPal email is never returned (the list endpoint has no auth)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_seed: bool
    created_at: datetime


class CleanerAvailability(CleanerOut):
    available: bool


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    required: bool
    position: int


class PaymentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    authorization_id: str | None
    authorized_amount: Decimal | None
    authorized_at: datetime | None
    status: str


class VerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    score: Decimal | None
    results: dict
    model: str
    created_at: datetime


class DecisionOut(BaseModel):
    outcome: Literal["auto_release", "needs_approval", "reject"]
    reasons: list[str]


class ApprovalDecisionIn(BaseModel):
    decision: Literal["approve", "deny"]
    decided_by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    content_type: str
    created_at: datetime


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    amount: Decimal
    status: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    customer_name: str
    customer_email: str
    address: str
    service_type: str
    scheduled_at: datetime
    amount: Decimal
    currency: str
    authorized_at: datetime | None
    created_at: datetime
    cleaner_id: uuid.UUID | None = None
    service_date: date | None = None
    checklist_items: list[ChecklistItemOut]
    payment: PaymentSummary | None
    verification: VerificationOut | None = None
    decision: DecisionOut | None = None
    payout: PayoutOut | None = None
