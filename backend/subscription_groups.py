"""Subscription groups (operator, 2026-10-29: "how much M42 spends on storage regarding
Genome" -- the Genome programme's subscriptions are named EGP, Labware Genome, BIX...):
a customer's own named groups of subscriptions, matched by fragments of their names,
and what each group spent per month -- on everything, or on one service.

Data, not code: a group is `{name, match: [fragments]}` kept on the customer, so a
new programme is a new group, never a release. Pure functions over merged months.
"""
from __future__ import annotations

MAX_GROUPS = 20
MAX_FRAGMENTS = 30
REPORT_MONTHS = 12


class GroupsError(ValueError):
    pass


def validated(groups) -> list[dict]:
    if not isinstance(groups, list):
        raise GroupsError("subscription groups are a list")
    if len(groups) > MAX_GROUPS:
        raise GroupsError(f"at most {MAX_GROUPS} subscription groups")
    cleaned, names = [], set()
    for group in groups:
        if not isinstance(group, dict):
            raise GroupsError("a subscription group is {name, match}")
        name = str(group.get("name") or "").strip()
        if not name:
            raise GroupsError("a subscription group needs a name")
        if name.lower() in names:
            raise GroupsError(f"two groups are named {name!r}")
        match = group.get("match") or []
        if not isinstance(match, list) or not all(isinstance(fragment, str) for fragment in match):
            raise GroupsError("a group's match is a list of name fragments")
        fragments = list(dict.fromkeys(fragment.strip() for fragment in match if fragment.strip()))
        if not fragments:
            raise GroupsError(f"{name}: say which subscription names belong to it")
        if len(fragments) > MAX_FRAGMENTS:
            raise GroupsError(f"{name}: at most {MAX_FRAGMENTS} name fragments")
        names.add(name.lower())
        cleaned.append({"name": name, "match": fragments})
    return cleaned


def subscription_name(label: str) -> str:
    """`"EGP Data(631892e7-...)"` -> `"EGP Data"`: the id must not match a fragment."""
    return label.split("(")[0].strip() if label.endswith(")") and "(" in label else label


def group_of(label: str, groups: list[dict]) -> str | None:
    """The first group one of whose fragments the subscription's name contains."""
    name = subscription_name(label).lower()
    return next((group["name"] for group in groups
                 if any(fragment.lower() in name for fragment in group["match"])), None)


def report(merged: dict, groups: list[dict], service: str | None = None,
           most_months: int = REPORT_MONTHS) -> dict:
    """Each group's monthly cost and its subscriptions', from the subscription x service
    pairs; `service` limits it to that service (e.g. Storage)."""
    shown_months = [month for month in sorted(merged) if (merged[month].get("actual") or {}).get("pairs")][-most_months:]
    found = {group["name"]: {"name": group["name"], "match": group["match"], "monthly": {}, "subscriptions": {}}
             for group in groups}
    services: dict[str, float] = {}
    for month in shown_months:
        for label, spend in merged[month]["actual"]["pairs"].items():
            name = group_of(label, groups)
            if name is None:
                continue
            for service_name, cost in spend.items():
                services[service_name] = services.get(service_name, 0.0) + cost
            cost = spend.get(service, 0.0) if service else sum(spend.values())
            if not cost:
                continue
            row = found[name]
            row["monthly"][month] = row["monthly"].get(month, 0.0) + cost
            subscription = row["subscriptions"].setdefault(label, {"name": label, "monthly": {}})
            subscription["monthly"][month] = subscription["monthly"].get(month, 0.0) + cost
    rows = []
    for row in found.values():
        subscriptions = sorted(row["subscriptions"].values(), key=lambda item: -sum(item["monthly"].values()))
        rows.append({**row, "monthly": _rounded(row["monthly"]),
                     "subscriptions": [{**item, "monthly": _rounded(item["monthly"])} for item in subscriptions]})
    return {"months": shown_months, "service": service, "groups": rows,
            # The services the groups' subscriptions use, biggest first: what can be chosen.
            "services": [name for name, _ in sorted(services.items(), key=lambda item: -item[1])]}


def _rounded(monthly: dict[str, float]) -> dict[str, float]:
    return {month: round(cost, 2) for month, cost in monthly.items()}
