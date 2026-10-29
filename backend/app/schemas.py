from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)

    @field_validator("full_name")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class EnrollmentStatus(BaseModel):
    modality: str
    required: bool = False         # face and voice are required for sign-in; fingerprint is optional
    state: Literal["enrolled", "not_enrolled"]
    method: str | None
    sample_count: int
    quality: float | None
    enrolled_at: datetime | None
    module_available: bool
    module_detail: str


class UserOut(ORM):
    id: int
    full_name: str
    email: str
    account_number: str
    role: str = "user"
    created_at: datetime


class UserDetail(UserOut):
    enrollments: list[EnrollmentStatus]
    probation_until: datetime | None = None
    session_scope: str | None = None
    recovery: list[dict[str, Any]] = []       # open or recent recovery requests for this account


TransactionType = Literal["domestic_transfer", "bill_payment", "cash_withdrawal", "wire_transfer"]


class TransactionCreate(BaseModel):
    # the account is always the signed-in user; a client cannot choose it
    amount: float = Field(gt=0, le=10_000_000)
    recipient_name: str = Field(min_length=1, max_length=120)
    recipient_account: str = Field(min_length=3, max_length=40)
    transaction_type: TransactionType = "domestic_transfer"
    recipient_is_new: bool = False
    is_international: bool = False
    new_device: bool = False
    note: str | None = Field(default=None, max_length=200)
    local_hour: int | None = Field(default=None, ge=0, le=23)    # the user's local hour; enables the time-of-day factor


class RiskPreviewIn(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    transaction_type: TransactionType = "domestic_transfer"
    recipient_is_new: bool = False
    is_international: bool = False
    new_device: bool = False
    local_hour: int | None = Field(default=None, ge=0, le=23)


class AttemptOut(ORM):
    id: int
    transaction_id: int
    modality_results: list[dict[str, Any]]
    fixed_outcome: dict[str, Any]
    risk_aware_outcome: dict[str, Any]
    active_policy: str
    decision: str
    explanation: str
    latency_ms: float
    created_at: datetime


class TransactionOut(ORM):
    id: int
    user_id: int
    user_name: str | None = None
    amount: float
    currency: str
    recipient_name: str
    recipient_account: str
    transaction_type: str
    recipient_is_new: bool
    is_international: bool
    new_device: bool
    note: str | None
    local_hour: int | None = None
    risk_score: float
    risk_category: str
    risk_factors: list[dict[str, Any]]
    decision: str
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None
    attempt_count: int = 0
    modality_summary: list[dict[str, Any]] = []


class TransactionDetail(TransactionOut):
    attempts: list[AttemptOut]


class TransactionList(BaseModel):
    total: int
    items: list[TransactionOut]
