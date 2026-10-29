"""Database tables. Biometric templates are NOT stored here, only metadata and a file reference."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    account_number: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(10), default="user")      # user | admin
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # unused since lockouts became source-scoped
    probation_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")


class Device(Base):
    """A browser the user has signed in from successfully. Identified by a random id the client keeps;
    only a hash is stored. Used to scope lockouts so an attacker's failures cannot lock the owner out."""
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "device_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    device_hash: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryRequest(Base):
    """A request to wipe an account's biometric references because the owner cannot provide them.
    pending -> approved (executed by an admin after the cooling-off) | denied | cancelled by the owner."""
    __tablename__ = "recovery_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    earliest_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(300))
    device_hash: Mapped[str | None] = mapped_column(String(32))


class Session(Base):
    """Login session. Only a SHA-256 of the bearer token is stored, never the token."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)
    # full: everything. limited: password only and face/voice not enrolled yet, so enrollment pages only.
    # preauth: the password was right but the face and voice check is still pending; reaches nothing else.
    scope: Mapped[str] = mapped_column(String(10), default="full")
    attempts: Mapped[int] = mapped_column(Integer, default=0)       # biometric login tries made with a preauth session


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "modality"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    modality: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(120))
    sample_count: Mapped[int] = mapped_column(Integer)
    quality: Mapped[float | None] = mapped_column(Float)
    template_file: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="enrollments")


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    recipient_name: Mapped[str] = mapped_column(String(120))
    recipient_account: Mapped[str] = mapped_column(String(40))
    transaction_type: Mapped[str] = mapped_column(String(30))
    recipient_is_new: Mapped[bool] = mapped_column(default=False)
    is_international: Mapped[bool] = mapped_column(default=False)
    new_device: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(String(200))
    local_hour: Mapped[int | None] = mapped_column(Integer)      # hour of day the user reported, for time-aware risk
    risk_score: Mapped[float] = mapped_column(Float)
    risk_category: Mapped[str] = mapped_column(String(12))
    risk_factors: Mapped[list] = mapped_column(JSON)
    # pending -> approved | rejected | additional_verification_required
    decision: Mapped[str] = mapped_column(String(40), default="pending")
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="transactions")
    attempts: Mapped[list["AuthAttempt"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", order_by="AuthAttempt.id"
    )


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    modality_results: Mapped[list] = mapped_column(JSON)
    fixed_outcome: Mapped[dict] = mapped_column(JSON)
    risk_aware_outcome: Mapped[dict] = mapped_column(JSON)
    active_policy: Mapped[str] = mapped_column(String(20))
    decision: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transaction: Mapped[Transaction] = relationship(back_populates="attempts")


class Event(Base):
    """Append-only audit log: enrollments, standalone verifications, decisions, errors."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[int | None] = mapped_column(Integer)
    transaction_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSON)
    # who it came from, for scoping lockouts (hashes only, never the raw address or device id)
    device_hash: Mapped[str | None] = mapped_column(String(32))
    ip_hash: Mapped[str | None] = mapped_column(String(16))
    trusted: Mapped[bool | None] = mapped_column()          # was the device a known one for this user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # modality | fusion
    name: Mapped[str] = mapped_column(String(120))
    data_source: Mapped[str] = mapped_column(String(300))
    is_synthetic: Mapped[bool] = mapped_column(default=False)
    metrics: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
