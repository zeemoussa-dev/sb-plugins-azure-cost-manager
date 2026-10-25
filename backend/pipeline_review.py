"""The pipeline review's foundations (PLAN.md, "Pipeline review", release 1): its
settings and the monthly snapshot (operator, 2026-10-25: "the whole concept of weekly is
wrong" -- consumption settles by the month, so the review is monthly).

Why snapshots: a customer's natural trend recomputed today has already absorbed the
growth the team drove, so the team's impact would vanish. A snapshot holds, per month,
the pipeline as it stood and each customer's natural trend fitted on the months closed
before it; comparing two months' snapshots is "what changed this month". The running
month's snapshot is live -- refreshed when the report is opened -- and stays as it last
was once the month is over. An opportunity
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
KEPT_MONTHS = 36
# The running month's snapshot is retaken when it is older than this.
LIVE_FOR_HOURS = 6
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


def stale(snapshot: dict | None, now: datetime) -> bool:
    """The running month's snapshot is retaken when older than LIVE_FOR_HOURS."""
    if not snapshot or not snapshot.get("taken_at"):
        return True
    return now - datetime.fromisoformat(snapshot["taken_at"]) > timedelta(hours=LIVE_FOR_HOURS)


def normalized(snapshots: list[dict]) -> list[dict]:
    """Snapshots keyed by month. The weekly ones taken first (2026-10-25) count as the month
    they were taken in."""
    found = {}
    for row in snapshots:
        month = row.get("month") or (row.get("taken_at") or row.get("week_end") or "")[:7]
        if month:
            found[month] = {**row, "month": month}
    return [found[month] for month in sorted(found)]


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


def kept(snapshots: list[dict], new: dict) -> list[dict]:
    """Newest last, one per month (a retake replaces), at most three years."""
    others = [row for row in normalized(snapshots) if row["month"] != new["month"]]
    return sorted([*others, new], key=lambda row: row["month"])[-KEPT_MONTHS:]


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
    """Section 1: what changed since last month's snapshot. With no earlier snapshot, the
    opportunities opened during the month stand in for "new", and the section says so."""
    changes = []
    before = {row["id"]: row for row in (previous or {}).get("opportunities") or []} if previous else None
    rank = {stage: index for index, stage in enumerate(STAGES)}
    for row in current["opportunities"]:
        if before is None:
            opened = row.get("created") or ""
            if opened[:7] == current["month"]:
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
    return {"compared_with": (previous or {}).get("month"), "first_snapshot": previous is None, "changes": changes}


def unit_of(customer_id: str | None, customers: dict[str, dict]) -> str | None:
    """The customer an account manager is measured on: an affiliate with an account manager
    of its own, different from its parent's, is its own unit (DGE's entities each have
    theirs); any other affiliate counts with its parent's group, as quota does."""
    customer = customers.get(customer_id or "") or {}
    parent = customer.get("parent")
    if not parent:
        return customer_id
    own = "account_manager" not in (customer.get("inherited") or []) and customer.get("account_manager")
    parents = (customers.get(parent) or {}).get("account_manager") or {}
    return customer_id if own and own.get("key") != parents.get("key") else parent


def landing(rows: list[dict], chosen: dict, span: list[str]) -> dict:
    """The pipeline's plan by month over `span` (the quota period: months gone count too),
    raw and weighted by stage."""
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


def verdict(planned: float, grown: float, tolerance_pct: float) -> str:
    """A customer's growth above its baseline against what its opportunities planned."""
    if planned <= 0:
        return "growing without opportunities" if grown > 0 else "no opportunities"
    if grown <= planned * STARTED_FLOOR:
        return "not growing"
    ratio = grown / planned
    if ratio < 1 - tolerance_pct / 100:
        return "short"
    if ratio > 1 + tolerance_pct / 100:
        return "over"
    return "landed"


def growth_against_plan(groups: dict[str, dict], rows: list[dict], units: dict[str, str], customers: dict[str, dict],
                        chosen: dict, span: list[str], tolerance_pct: float) -> dict:
    """Section 3 (operator, 2026-10-25: "compare the size of the opportunity with the customer's
    growth in H2"): per customer group, the opportunities' plan against its consumption
    above the quota baseline, month by month over the quota period -- closed months actual,
    the rest the automatic forecast. `groups` is unit id -> {"name", "months": quota rows};
    `units` is opportunity id -> its unit (`unit_of`)."""
    planned: dict[str, dict[str, list[float]]] = {}
    count: dict[str, int] = {}
    for row in rows:
        group = units.get(row["id"])
        if group not in groups:
            continue
        count[group] = count.get(group, 0) + 1
        if not counted(row):
            continue
        weight = weight_of(row, chosen)
        for month, usd in planned_by_month(row).items():
            if month in span:
                cell = planned.setdefault(group, {}).setdefault(month, [0.0, 0.0])
                cell[0] += usd
                cell[1] += usd * weight
    found, totals = [], {month: {"growth": 0.0, "planned": 0.0, "weighted": 0.0, "kind": None} for month in span}
    for group, info in groups.items():
        by_month = {row["month"]: row for row in info["months"]}
        months_rows, closed = [], {"growth": 0.0, "planned": 0.0}
        whole = {"growth": 0.0, "planned": 0.0, "weighted": 0.0}
        for month in span:
            quota_row = by_month.get(month) or {}
            raw, weighted = (planned.get(group) or {}).get(month, [0.0, 0.0])
            growth = float(quota_row.get("above") or 0.0)
            kind = quota_row.get("kind") or "forecast"
            months_rows.append({"month": month, "kind": kind, "growth": round(growth, 2),
                                "planned": round(raw, 2), "weighted": round(weighted, 2)})
            whole["growth"] += growth
            whole["planned"] += raw
            whole["weighted"] += weighted
            if kind == "actual":
                closed["growth"] += growth
                closed["planned"] += raw
            totals[month]["growth"] += growth
            totals[month]["planned"] += raw
            totals[month]["weighted"] += weighted
            totals[month]["kind"] = kind
        manager = (customers.get(group) or {}).get("account_manager") or {}
        found.append({"id": group, "name": info["name"], "account_manager": manager.get("name"),
                      "opportunities": count.get(group, 0), "baseline": info.get("baseline"), "months": months_rows,
                      "growth_to_date": round(closed["growth"], 2), "planned_to_date": round(closed["planned"], 2),
                      "growth_period": round(whole["growth"], 2), "planned_period": round(whole["planned"], 2),
                      "weighted_period": round(whole["weighted"], 2),
                      "verdict": verdict(closed["planned"], closed["growth"], tolerance_pct)})
    found.sort(key=lambda row: (-row["planned_period"], -row["growth_period"]))
    planned_to_date = sum(row["planned_to_date"] for row in found)
    growth_to_date = sum(row["growth_to_date"] for row in found)
    counts: dict[str, int] = {}
    for row in found:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {"rows": found, "counts": counts,
            "months": {month: {key: (round(value, 2) if isinstance(value, float) else value) for key, value in cell.items()}
                       for month, cell in totals.items()},
            "growth_to_date": round(growth_to_date, 2), "planned_to_date": round(planned_to_date, 2),
            "growth_period": round(sum(row["growth_period"] for row in found), 2),
            "planned_period": round(sum(row["planned_period"] for row in found), 2),
            "weighted_period": round(sum(row["weighted_period"] for row in found), 2),
            "verdict": verdict(planned_to_date, growth_to_date, tolerance_pct)}


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


def rollup(rows: list[dict], growth: dict, units: dict[str, str], customers: dict[str, dict], level: str, chosen: dict,
           span: list[str], closed: set[str], slipped: dict[str, int], tolerance_pct: float) -> list[dict]:
    """One row per account manager (all customers), per customer group (a manager, segment
    or PSS) or per opportunity (one customer), with the level each drills into: what was
    planned in the period and to date, against the growth above baseline."""
    kind = level.partition(":")[0]
    if kind == "customer":
        found = []
        for row in rows:
            plan = planned_by_month(row)
            raw = sum(plan.get(month, 0.0) for month in span) if counted(row) else 0.0
            found.append({"key": row["id"], "label": row.get("title") or "", "drill": None, "stem": row.get("stem"),
                          "opportunities": 1, "stage": row.get("stage"), "status": row.get("status"),
                          "planned_period": round(raw, 2), "weighted_period": round(raw * weight_of(row, chosen), 2),
                          "planned_to_date": round(sum(plan.get(month, 0.0) for month in closed) if counted(row) else 0.0, 2),
                          "growth_to_date": None, "growth_period": None, "verdict": None,
                          "slipped_months": slipped.get(row["id"], 0)})
        return sorted(found, key=lambda row: -row["planned_period"])
    slipped_by_group: dict[str, int] = {}
    for row in rows:
        group = units.get(row["id"])
        slipped_by_group[group] = slipped_by_group.get(group, 0) + slipped.get(row["id"], 0)
    if kind != "all":
        return [{"key": row["id"], "label": row["name"], "drill": f"customer:{row['id']}", "stem": None,
                 **{key: row[key] for key in ("opportunities", "planned_period", "weighted_period", "planned_to_date",
                                              "growth_to_date", "growth_period", "verdict")},
                 "slipped_months": slipped_by_group.get(row["id"], 0)} for row in growth["rows"]]
    managers: dict[str, dict] = {}
    for row in growth["rows"]:
        manager = (customers.get(row["id"]) or {}).get("account_manager") or {}
        key = manager.get("key") or ""
        entry = managers.setdefault(key, {"key": key, "label": manager.get("name") or NO_MANAGER, "drill": f"am:{key}",
                                          "stem": None, "opportunities": 0, "planned_period": 0.0, "weighted_period": 0.0,
                                          "planned_to_date": 0.0, "growth_to_date": 0.0, "growth_period": 0.0,
                                          "slipped_months": 0, "customers": 0})
        entry["customers"] += 1
        for field in ("opportunities", "planned_period", "weighted_period", "planned_to_date", "growth_to_date", "growth_period"):
            entry[field] += row[field]
        entry["slipped_months"] += slipped_by_group.get(row["id"], 0)
    for entry in managers.values():
        for field in ("planned_period", "weighted_period", "planned_to_date", "growth_to_date", "growth_period"):
            entry[field] = round(entry[field], 2)
        entry["verdict"] = verdict(entry["planned_to_date"], entry["growth_to_date"], tolerance_pct)
    return sorted(managers.values(), key=lambda row: (-row["planned_period"], -row["growth_period"]))
