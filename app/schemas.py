import uuid
from datetime import datetime
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
    scheduled_at: datetime
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: Literal["USD"] = "USD"

    @field_validator("scheduled_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone")
        return v

    @model_validator(mode="after")
    def _price_matches_tier(self) -> "JobCreate":
        expected = TIER_PRICES[self.service_type]
        if self.amount != expected:
            raise ValueError(f"amount for {self.service_type} must be {expected}")
        return self


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
    checklist_items: list[ChecklistItemOut]
    payment: PaymentSummary | None
