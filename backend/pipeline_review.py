"""The pipeline review's foundations (PLAN.md, "Pipeline review", release 1): its
settings, the week it reports on, and the weekly snapshot.

Why snapshots: a customer's natural trend recomputed today has already absorbed the
growth the team drove, so the team's impact would vanish. A snapshot freezes, each week,
the pipeline as it stood and each customer's natural trend fitted on the closed months
before it; comparing two snapshots is also "what changed this week". An opportunity
seen for the first time is given a baseline -- the natural trend of its scope, frozen
then. One opened before the first snapshot is fitted on the months before it was
opened, recomputed once and marked `estimated`.

Pure: the service gathers the opportunities and monthly totals and keeps what this
returns.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import forecasting, months

STAGES = ("Identified", "Qualified", "Proposed", "Committed", "Closed")
DEFAULT_SETTINGS = {
    "stage_weights": {"Identified": 0.10, "Qualified": 0.25, "Proposed": 0.50, "Committed": 0.80, "Closed": 1.0},
    "won_weight": 1.0, "tolerance_pct": 20, "horizon_months": 12,
}
COUNTED_STATUSES = ("Open", "Won")
KEPT_WEEKS = 104
HORIZON_LIMIT = 24


def settings(stored: dict | None) -> dict:
    stored = stored or {}
    weights = {**DEFAULT_SETTINGS["stage_weights"], **(stored.get("stage_weights") or {})}
    return {"stage_weights": weights,
            "won_weight": stored.get("won_weight", DEFAULT_SETTINGS["won_weight"]),
            "tolerance_pct": stored.get("tolerance_pct", DEFAULT_SETTINGS["tolerance_pct"]),
            "horizon_months": stored.get("horizon_months", DEFAULT_SETTINGS["horizon_months"])}


def validated(changes: dict) -> dict:
    """Only known settings, each in range; a stage weight is a share, 0 to 1."""
    clean: dict = {}
    for stage, weight in ((changes or {}).get("stage_weights") or {}).items():
        if stage not in STAGES:
            raise ValueError(f"{stage!r} is not a stage ({', '.join(STAGES)})")
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
            raise ValueError(f"the weight of {stage} must be between 0 and 1")
        clean.setdefault("stage_weights", {})[stage] = float(weight)
    if "won_weight" in (changes or {}):
        weight = changes["won_weight"]
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
            raise ValueError("the weight of a won opportunity must be between 0 and 1")
        clean["won_weight"] = float(weight)
    if "tolerance_pct" in (changes or {}):
        tolerance = changes["tolerance_pct"]
        if not isinstance(tolerance, (int, float)) or not 0 <= tolerance <= 100:
            raise ValueError("the tolerance is a percentage between 0 and 100")
        clean["tolerance_pct"] = float(tolerance)
    if "horizon_months" in (changes or {}):
        horizon = changes["horizon_months"]
        if not isinstance(horizon, int) or not 1 <= horizon <= HORIZON_LIMIT:
            raise ValueError(f"the horizon is 1 to {HORIZON_LIMIT} months")
        clean["horizon_months"] = horizon
    return clean


def week_end(today: date) -> date:
    """The last week that has closed: weeks close on Sunday night, so on a Sunday the
    week still running is not the one reported."""
    return today - timedelta(days=((today.weekday() + 1) % 7) or 7)


def scope_of(opportunity: dict, services: set[str]) -> list[str]:
    """The services an opportunity covers: its `technologies` matched to the customer's
    billed services, case and spacing aside, a technology naming a service or a service
    naming a technology. None matched: unscoped, and it influences nothing."""
    wanted = [" ".join(str(item).lower().split()) for item in opportunity.get("technologies") or [] if str(item).strip()]
    found = [service for service in sorted(services)
             if any(item == " ".join(service.lower().split()) or (len(item) >= 4 and item in service.lower())
                    or (len(service) >= 4 and service.lower() in item) for item in wanted)]
    return found


def natural(trend: list[dict], fitted_through: str, horizon: int) -> dict | None:
    """The trend the customer (or one scope of it) was on, fitted on the closed months up
    to `fitted_through`, for the `horizon` months after it. None with too little history."""
    cut = [{**point, "partial": False} for point in trend if point["month"] <= fitted_through]
    following = months.shift(fitted_through, 1)
    found = forecasting.automatic(cut, date(int(following[:4]), int(following[5:7]), 1))
    if not found:
        return None
    projected = [point for point in found["series"] if point["forecast"] is not None][:horizon]
    return {"fitted_through": fitted_through, "r_squared": found["r_squared"], "mape": found["mape"],
            "by_month": {point["month"]: point["forecast"] for point in projected}}


def scope_trend(merged: dict, services: list[str], current_month: str) -> list[dict]:
    """A scope's monthly actual cost, from the merged months' services."""
    return [{"month": month, "actual": round(sum(((merged[month].get("actual") or {}).get("service") or {}).get(name, 0.0)
                                                 for name in services), 2),
             "partial": month >= current_month} for month in sorted(merged)]


def planned_by_month(opportunity: dict) -> dict[str, float]:
    """An opportunity's plan, or its start and monthly figure carried forward a year."""
    raw = opportunity.get("plan") or []
    # A note's plan is rows; a snapshot keeps it as month -> amount.
    plan = {month: float(usd) for month, usd in raw.items()} if isinstance(raw, dict) else \
        {row["month"]: float(row["usd"]) for row in raw}
    if plan:
        return plan
    start, monthly = opportunity.get("consumption_start"), opportunity.get("expected_monthly_usd")
    if start and monthly:
        return {month: float(monthly) for month in months.span(start, months.shift(start, 11))}
    return {}


def gaps(opportunities: list[dict], customers: dict[str, dict]) -> dict:
    """What weakens the review, for the seller to fix in the notes."""
    return {
        "customers_without_account_manager": sorted(row["name"] for row in customers.values() if not row.get("account_manager")),
        "opportunities_without_start": [row["title"] for row in opportunities if not row.get("consumption_start")],
        "opportunities_without_amount": [row["title"] for row in opportunities if not planned_by_month(row)],
        "opportunities_unscoped": [row["title"] for row in opportunities if not row.get("scope")],
    }


def taken_late(week: date, taken: datetime) -> bool:
    """A snapshot is on time if taken by the Monday after the week closed."""
    return taken.date() > week + timedelta(days=1)


def kept(snapshots: list[dict], new: dict) -> list[dict]:
    """Newest last, one per week (a retake replaces), at most two years."""
    others = [row for row in snapshots if row["week_end"] != new["week_end"]]
    return sorted([*others, new], key=lambda row: row["week_end"])[-KEPT_WEEKS:]
