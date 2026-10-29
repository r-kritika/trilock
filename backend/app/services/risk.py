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
    # --- time-aware factors (all rule-based; they need the user's history, see authentication.build_risk_input) ---
    # many payments in a short time: (earlier payments inside the window, points), the highest match applies
    velocity_window_minutes: int = 10
    velocity_points: list[tuple[int, float]] = field(default_factory=lambda: [(2, 10), (4, 20)])
    # money leaving over 24 hours, this payment included
    daily_total_threshold: float = 10000
    daily_total_points: float = 10
    # unusual hour. With a learned profile (enough approved history) the hour must be within this many hours of the
    # user's typical hour; without one a fixed night window is used.
    usual_hour_min_history: int = 5
    usual_hour_max_deviation: float = 6.0
    usual_hour_points: float = 8
    night_start_hour: int = 0
    night_end_hour: int = 5          # exclusive: 00:00 to 04:59
    night_points: float = 8
    # a very new account moving real money, or a long-dormant one suddenly active
    new_account_hours: float = 24
    new_account_min_amount: float = 1000
    new_account_points: float = 10
    dormant_days: float = 60
    dormant_min_amount: float = 1000
    dormant_points: float = 8
    # biometrics were added, replaced or removed on an account that already had some
    recent_biometric_change_hours: float = 24
    recent_biometric_change_points: float = 12
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
    # time-related inputs (None / 0 = unknown, no factor)
    local_hour: int | None = None               # hour of day 0-23 where the user is, sent by the client
    recent_count: int = 0                       # this user's earlier payments inside the velocity window
    amount_24h: float = 0.0                     # total of this user's earlier payments in the last 24 h
    account_age_hours: float | None = None
    hours_since_last_txn: float | None = None
    typical_hour: float | None = None           # learned from approved history (circular mean), if any
    biometric_changed_hours_ago: float | None = None


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


def circular_gap(a: float, b: float) -> float:
    d = abs(a - b) % 24
    return min(d, 24 - d)


def _time_factors(inp: RiskInput, cfg: RiskConfig) -> list[RiskFactor]:
    out: list[RiskFactor] = []
    pts = [p for n, p in cfg.velocity_points if inp.recent_count >= n]
    if pts:
        out.append(RiskFactor("velocity", max(pts), f"{inp.recent_count + 1} payments within {cfg.velocity_window_minutes} minutes"))
    if inp.amount_24h > 0 and inp.amount_24h + inp.amount >= cfg.daily_total_threshold:
        out.append(RiskFactor("daily_total", cfg.daily_total_points,
                              f"{inp.amount_24h + inp.amount:,.0f} USD moving out within 24 hours"))
    if inp.local_hour is not None:
        if inp.typical_hour is not None:
            if circular_gap(inp.local_hour, inp.typical_hour) > cfg.usual_hour_max_deviation:
                out.append(RiskFactor("unusual_hour", cfg.usual_hour_points,
                                      f"{inp.local_hour:02d}:00 is far from this user's usual hours (around {inp.typical_hour:.0f}:00)"))
        elif cfg.night_start_hour <= inp.local_hour < cfg.night_end_hour:
            out.append(RiskFactor("night_hour", cfg.night_points, f"Night-time payment ({inp.local_hour:02d}:00)"))
    if (inp.account_age_hours is not None and inp.account_age_hours < cfg.new_account_hours
            and inp.amount >= cfg.new_account_min_amount):
        out.append(RiskFactor("new_account", cfg.new_account_points, f"Account is only {inp.account_age_hours:.0f} hours old"))
    if (inp.hours_since_last_txn is not None and inp.hours_since_last_txn > cfg.dormant_days * 24
            and inp.amount >= cfg.dormant_min_amount):
        out.append(RiskFactor("dormant_account", cfg.dormant_points,
                              f"First payment in {inp.hours_since_last_txn / 24:.0f} days"))
    if (inp.biometric_changed_hours_ago is not None
            and inp.biometric_changed_hours_ago < cfg.recent_biometric_change_hours):
        out.append(RiskFactor("recent_biometric_change", cfg.recent_biometric_change_points,
                              f"Biometrics were changed {inp.biometric_changed_hours_ago:.0f} hours ago"))
    return out


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

    factors += _time_factors(inp, cfg)

    score = round(min(100.0, sum(f.points for f in factors)), 2)
    return RiskAssessment(score=score, category=categorize(score, cfg), factors=factors)
