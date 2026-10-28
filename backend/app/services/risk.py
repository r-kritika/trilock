"""Rule-based transaction risk scoring.

This is a transparent additive rule set, NOT a trained fraud model. Every factor adds points
(0-100 total, clipped) and every contribution is returned so the UI can show why a score is
what it is. Weights and cut-offs are experimental defaults and can be overridden through the
policy JSON file (key "risk").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class RiskCategory(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskConfig:
    # (amount in USD, points). Linear interpolation between points, flat after the last one.
    amount_curve: list[tuple[float, float]] = field(default_factory=lambda: [
        (0, 0), (100, 2), (500, 6), (2000, 15), (10000, 30), (50000, 40)])
    new_recipient_points: float = 20
    international_points: float = 12
    new_device_points: float = 10
    type_points: dict[str, float] = field(default_factory=lambda: {
        "domestic_transfer": 0, "bill_payment": 0, "cash_withdrawal": 5, "wire_transfer": 8})
    # amount much larger than the user's own approved history
    history_min_transactions: int = 3
    history_multiple: float = 3.0
    history_points: float = 12
    # category lower bounds (score >= bound -> category)
    medium_from: float = 25
    high_from: float = 50
    critical_from: float = 75


@dataclass
class RiskInput:
    amount: float
    transaction_type: str = "domestic_transfer"
    recipient_is_new: bool = False
    is_international: bool = False
    new_device: bool = False
    history_count: int = 0          # approved transactions by this user so far
    history_mean_amount: float = 0.0


@dataclass
class RiskFactor:
    name: str
    points: float
    description: str


@dataclass
class RiskAssessment:
    score: float
    category: RiskCategory
    factors: list[RiskFactor]

    def to_dict(self) -> dict:
        return {"score": self.score, "category": self.category.value,
                "factors": [asdict(f) for f in self.factors]}


def _interp(curve: list[tuple[float, float]], x: float) -> float:
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def categorize(score: float, cfg: RiskConfig) -> RiskCategory:
    if score >= cfg.critical_from:
        return RiskCategory.CRITICAL
    if score >= cfg.high_from:
        return RiskCategory.HIGH
    if score >= cfg.medium_from:
        return RiskCategory.MEDIUM
    return RiskCategory.LOW


def assess_risk(inp: RiskInput, cfg: RiskConfig | None = None) -> RiskAssessment:
    cfg = cfg or RiskConfig()
    if inp.amount < 0:
        raise ValueError("amount must not be negative")
    factors: list[RiskFactor] = []

    amt = round(_interp(cfg.amount_curve, inp.amount), 2)
    factors.append(RiskFactor("amount", amt, f"Amount {inp.amount:,.2f} USD"))

    if inp.recipient_is_new:
        factors.append(RiskFactor("new_recipient", cfg.new_recipient_points, "Recipient has not been paid before"))
    if inp.is_international:
        factors.append(RiskFactor("international", cfg.international_points, "Recipient is outside the home country"))
    if inp.new_device:
        factors.append(RiskFactor("new_device", cfg.new_device_points, "Request came from an unrecognised device"))

    tp = cfg.type_points.get(inp.transaction_type, 0)
    if tp:
        factors.append(RiskFactor("transaction_type", tp, f"Type '{inp.transaction_type}' carries extra risk"))

    if (inp.history_count >= cfg.history_min_transactions and inp.history_mean_amount > 0
            and inp.amount > cfg.history_multiple * inp.history_mean_amount):
        factors.append(RiskFactor(
            "unusual_amount", cfg.history_points,
            f"Amount is more than {cfg.history_multiple:g}x this user's average of {inp.history_mean_amount:,.2f}"))

    score = round(min(100.0, sum(f.points for f in factors)), 2)
    return RiskAssessment(score=score, category=categorize(score, cfg), factors=factors)
