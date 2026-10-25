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


# -- the report: sections 1-3 (release 2) ----------------------------------------------

NO_MANAGER = "No account manager"
STARTED_FLOOR = 0.05


def weight_of(row: dict, chosen: dict) -> float:
    if row.get("status") == "Won":
        return float(chosen["won_weight"])
    return float(chosen["stage_weights"].get(row.get("stage") or "", 0.0))


def counted(row: dict) -> bool:
    return row.get("status") in COUNTED_STATUSES


def monthly_of(row: dict) -> float:
    """What an opportunity adds a month at its steady state: its figure, else its plan's largest month."""
    plan = planned_by_month(row)
    return float(row.get("expected_monthly_usd") or (max(plan.values()) if plan else 0.0))


def in_level(customer_id: str | None, customers: dict[str, dict], level: str) -> bool:
    """`all`, `am:<person key>` (`am:` alone: no account manager), `segment:<name>`,
    `pss:<person key>` or `customer:<id>` (a group: the customer and its affiliates)."""
    if level == "all":
        return True
    found = customers.get(customer_id or "") or {}
    kind, _, value = level.partition(":")
    if kind == "am":
        manager = found.get("account_manager") or {}
        return (manager.get("key") or "") == value if value else not manager
    if kind == "segment":
        return (found.get("segment") or "") == value
    if kind == "pss":
        return any(person.get("key") == value for person in found.get("pss") or [])
    if kind == "customer":
        return customer_id == value or found.get("parent") == value
    raise ValueError(f"unknown level {level!r}")


def _movement_row(kind: str, row: dict, detail: str) -> dict:
    return {"kind": kind, "id": row.get("id"), "stem": row.get("stem"), "title": row.get("title"),
            "customer_id": row.get("customer_id"), "customer": row.get("customer"),
            "account_manager": (row.get("account_manager") or {}).get("name"), "detail": detail,
            "monthly": round(monthly_of(row), 2)}


def _months_between(old: str, new: str) -> int:
    return (int(new[:4]) - int(old[:4])) * 12 + int(new[5:7]) - int(old[5:7])


def movement(previous: dict | None, current: dict) -> dict:
    """Section 1: what changed between two weeks' snapshots. With no earlier snapshot, the
    opportunities opened during the week stand in for "new", and the section says so."""
    week = date.fromisoformat(current["week_end"])
    changes = []
    before = {row["id"]: row for row in (previous or {}).get("opportunities") or []} if previous else None
    rank = {stage: index for index, stage in enumerate(STAGES)}
    for row in current["opportunities"]:
        if before is None:
            opened = row.get("created") or ""
            if (week - timedelta(days=6)).isoformat() <= opened <= week.isoformat():
                changes.append(_movement_row("new", row, f"opened {opened}"))
            continue
        was = before.get(row["id"])
        if was is None:
            changes.append(_movement_row("new", row, f"stage {row.get('stage') or '-'}"))
            continue
        if row.get("status") != was.get("status"):
            kind = {"Won": "won", "Lost": "lost"}.get(row.get("status") or "", "status")
            changes.append(_movement_row(kind, row, f"{was.get('status') or '-'} → {row.get('status') or '-'}"))
        if row.get("stage") != was.get("stage"):
            up = rank.get(row.get("stage") or "", -1) > rank.get(was.get("stage") or "", -1)
            changes.append(_movement_row("stage up" if up else "stage down", row,
                                         f"{was.get('stage') or '-'} → {row.get('stage') or '-'}"))
        start, old = row.get("consumption_start"), was.get("consumption_start")
        if start != old:
            if start and old:
                moved = _months_between(old, start)
                changes.append(_movement_row("slipped" if moved > 0 else "pulled in", row,
                                             f"start {old} → {start} ({abs(moved)} month{'' if abs(moved) == 1 else 's'})"))
            else:
                changes.append(_movement_row("start set", row, f"start {old or '-'} → {start or '-'}"))
        if round(monthly_of(row)) != round(monthly_of(was)):
            changes.append(_movement_row("amount", row, f"${monthly_of(was):,.0f} → ${monthly_of(row):,.0f} a month"))
    if before is not None:
        listed = {row["id"] for row in current["opportunities"]}
        changes += [_movement_row("removed", row, "no longer listed") for row in before.values() if row["id"] not in listed]
    return {"compared_with": (previous or {}).get("week_end"), "first_snapshot": previous is None, "changes": changes}


def landing(rows: list[dict], chosen: dict, first_month: str, horizon: int) -> dict:
    """Section 2: the pipeline's planned consumption by month, raw and weighted by stage."""
    span = months.span(first_month, months.shift(first_month, horizon - 1))
    by_month = {month: {"raw": 0.0, "weighted": 0.0, "by_stage": {}} for month in span}
    for row in rows:
        if not counted(row):
            continue
        weight = weight_of(row, chosen)
        stage = "Won" if row.get("status") == "Won" else (row.get("stage") or "-")
        for month, usd in planned_by_month(row).items():
            if month in by_month:
                by_month[month]["raw"] += usd
                by_month[month]["weighted"] += usd * weight
                by_month[month]["by_stage"][stage] = by_month[month]["by_stage"].get(stage, 0.0) + usd
    for value in by_month.values():
        value["raw"], value["weighted"] = round(value["raw"], 2), round(value["weighted"], 2)
        value["by_stage"] = {stage: round(usd, 2) for stage, usd in value["by_stage"].items()}
    return {"months": by_month, "raw": round(sum(v["raw"] for v in by_month.values()), 2),
            "weighted": round(sum(v["weighted"] for v in by_month.values()), 2)}


def verdict(planned: float, added: float, tolerance_pct: float) -> str:
    if planned <= 0:
        return "no plan"
    if added <= planned * STARTED_FLOOR:
        return "late"
    ratio = added / planned
    if ratio < 1 - tolerance_pct / 100:
        return "short"
    if ratio > 1 + tolerance_pct / 100:
        return "over"
    return "landed"


def planned_vs_actual(rows: list[dict], measured: dict[str, dict], tolerance_pct: float) -> dict:
    """Section 3: each started opportunity's plan in the closed months against what it added
    above its frozen natural trend. `measured` is the service's: id -> {"months", "added",
    "against", "estimated"}; one with no trend to measure against says so."""
    found = []
    for row in rows:
        seen = measured.get(row["id"])
        if not seen:
            continue
        plan = planned_by_month(row)
        planned = sum(plan.get(month, 0.0) for month in seen["months"])
        added = sum(seen["added"].values()) if seen.get("added") is not None else None
        # Month by month: a short month is not made good by an over one after it.
        error = sum(abs(seen["added"].get(month, 0.0) - plan.get(month, 0.0)) for month in seen["months"]) \
            if seen.get("added") is not None else None
        found.append({"id": row["id"], "stem": row.get("stem"), "title": row.get("title"),
                      "customer_id": row.get("customer_id"), "customer": row.get("customer"),
                      "account_manager": (row.get("account_manager") or {}).get("name"),
                      "months": seen["months"], "planned": round(planned, 2),
                      "added": round(added, 2) if added is not None else None,
                      "error": round(error, 2) if error is not None else None,
                      "verdict": verdict(planned, added, tolerance_pct) if added is not None else "no trend",
                      "against": seen["against"], "estimated": seen.get("estimated", False)})
    measurable = [row for row in found if row["added"] is not None and row["planned"] > 0]
    planned_total = sum(row["planned"] for row in measurable)
    error = sum(row["error"] for row in measurable)
    counts: dict[str, int] = {}
    for row in found:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {"rows": sorted(found, key=lambda row: -row["planned"]), "counts": counts,
            "planned": round(planned_total, 2), "added": round(sum(row["added"] for row in measurable), 2),
            "accuracy": round(max(0.0, 1 - error / planned_total), 3) if planned_total else None}


def slips(snapshots: list[dict]) -> dict[str, int]:
    """Per opportunity, how many months its start moved later across the snapshots kept."""
    found: dict[str, int] = {}
    for before, after in zip(snapshots, snapshots[1:]):
        was = {row["id"]: row.get("consumption_start") for row in before.get("opportunities") or []}
        for row in after.get("opportunities") or []:
            old, new = was.get(row["id"]), row.get("consumption_start")
            if old and new and new > old:
                found[row["id"]] = found.get(row["id"], 0) + _months_between(old, new)
    return found


def rollup(rows: list[dict], checked: list[dict], customers: dict[str, dict], level: str,
           chosen: dict, first_month: str, horizon: int, slipped: dict[str, int]) -> list[dict]:
    """One row per account manager (all customers), per customer group (a manager, segment
    or PSS) or per opportunity (one customer), with the level each drills into."""
    kind = level.partition(":")[0]

    def key_of(row: dict) -> tuple[str, str, str | None]:
        if kind == "customer":
            return row["id"], row.get("title") or "", None
        if kind == "all":
            manager = row.get("account_manager") or {}
            return manager.get("key") or "", manager.get("name") or NO_MANAGER, f"am:{manager.get('key') or ''}"
        customer = customers.get(row.get("customer_id") or "") or {}
        group = customer.get("parent") or row.get("customer_id") or ""
        return group, (customers.get(group) or {}).get("name") or row.get("customer") or "", f"customer:{group}"

    span = set(months.span(first_month, months.shift(first_month, horizon - 1)))
    verdicts = {row["id"]: row for row in checked}
    groups: dict[str, dict] = {}
    for row in rows:
        key, label, drill = key_of(row)
        group = groups.setdefault(key, {"key": key, "label": label, "drill": drill, "opportunities": 0,
                                        "raw": 0.0, "weighted": 0.0, "verdicts": {}, "planned": 0.0, "error": 0.0,
                                        "slipped_months": 0, "stem": row.get("stem") if kind == "customer" else None})
        group["opportunities"] += 1
        if counted(row):
            ahead = sum(usd for month, usd in planned_by_month(row).items() if month in span)
            group["raw"] += ahead
            group["weighted"] += ahead * weight_of(row, chosen)
        seen = verdicts.get(row["id"])
        if seen:
            group["verdicts"][seen["verdict"]] = group["verdicts"].get(seen["verdict"], 0) + 1
            if seen["added"] is not None and seen["planned"] > 0:
                group["planned"] += seen["planned"]
                group["error"] += seen["error"]
        group["slipped_months"] += slipped.get(row["id"], 0)
    return sorted(({key: group[key] for key in ("key", "label", "drill", "opportunities", "verdicts", "slipped_months", "stem")}
                   | {"raw": round(group["raw"], 2), "weighted": round(group["weighted"], 2),
                      "accuracy": round(max(0.0, 1 - group["error"] / group["planned"]), 3) if group["planned"] else None}
                   for group in groups.values()), key=lambda row: -row["weighted"])
