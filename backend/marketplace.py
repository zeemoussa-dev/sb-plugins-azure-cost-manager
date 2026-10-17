"""Marketplace: which partner solutions a customer bought, what they cost by month,
and how much of it counts toward the customer's MACC -- per customer, and across
every customer (the partners' view of the business).

Azure does not say which offers are MACC-eligible at this scope, so every
Marketplace dollar counts unless the operator marked the offer as not eligible
(operator, 2026-10-17); one list, applied to every customer. A solution that
billed nothing in the period -- a free plan, a trial, a preview model billed on
another line -- is still a solution the customer adopted, and is listed apart.
"""
from __future__ import annotations

from . import months


def offer_key(publisher: str, offer: str) -> str:
    return f"{publisher}|{offer}"


def not_eligible_keys(offers: list[dict]) -> set[str]:
    return {offer_key(item["publisher"], item["offer"]) for item in offers}


def _in_period(month: str, first: str | None, last: str | None) -> bool:
    return (not first or month >= first) and (not last or month <= last)


def _covered(seen: set[str], first: str | None, last: str | None) -> dict:
    """The period a report covers. With no lower bound ("from the start") it is the
    first month that has any Marketplace data, never an invented date."""
    return {"first": first or (min(seen) if seen else None), "last": last or (max(seen) if seen else None),
            "from_start": first is None}


def _items(entries: dict[str, dict], first: str | None, last: str | None):
    """`(account, month, item)` for every Marketplace item in the period."""
    for account, entry in entries.items():
        for month, data in sorted((entry.get("months") or {}).items()):
            if _in_period(month, first, last):
                for item in (data.get("marketplace") or {}).get("items") or []:
                    yield account, month, item


def customer_report(entries: dict[str, dict], labels: dict[str, str], not_eligible: set[str],
                    first: str | None = None, last: str | None = None) -> dict:
    solutions: dict[tuple, dict] = {}
    monthly: dict[str, dict] = {}
    seen: set[str] = set()
    for account, month, item in _items(entries, first, last):
        seen.add(month)
        key = (item["publisher"], item["offer"], item["plan"])
        counted = offer_key(item["publisher"], item["offer"]) not in not_eligible
        solution = solutions.setdefault(key, {
            "publisher": item["publisher"], "offer": item["offer"], "plan": item["plan"],
            "macc_eligible": counted, "total": 0.0, "by_month": {}, "subscriptions": set(), "enrollments": set(),
            "recurring": False, "metered": False, "quantity": 0.0, "unit": item.get("unit") or "",
            "first_month": month, "last_month": month})
        solution["total"] += item["cost"]
        solution["by_month"][month] = solution["by_month"].get(month, 0.0) + item["cost"]
        if item.get("subscription"):
            solution["subscriptions"].add(item["subscription"])
        solution["enrollments"].add(labels.get(account, account))
        solution["recurring"] |= bool(item.get("recurring"))
        solution["metered"] |= not item.get("recurring")
        solution["quantity"] += item.get("quantity") or 0.0
        solution["first_month"] = min(solution["first_month"], month)
        solution["last_month"] = max(solution["last_month"], month)
        total = monthly.setdefault(month, {"month": month, "total": 0.0, "macc": 0.0, "by_publisher": {}})
        total["total"] += item["cost"]
        total["macc"] += item["cost"] if counted else 0.0
        total["by_publisher"][item["publisher"]] = total["by_publisher"].get(item["publisher"], 0.0) + item["cost"]

    def finished(solution: dict) -> dict:
        return {**solution, "total": round(solution["total"], 2),
                "by_month": {month: round(cost, 2) for month, cost in sorted(solution["by_month"].items())},
                "subscriptions": sorted(solution["subscriptions"]), "enrollments": sorted(solution["enrollments"]),
                "kind": "SaaS" if solution["recurring"] and not solution["metered"]
                else "Metered" if not solution["recurring"] else "SaaS + metered"}

    listed = sorted((finished(solution) for solution in solutions.values()), key=lambda s: -abs(s["total"]))
    billed = [solution for solution in listed if round(solution["total"], 2) != 0]
    adopted = [solution for solution in listed if round(solution["total"], 2) == 0]
    publishers: dict[str, dict] = {}
    for solution in billed:
        publisher = publishers.setdefault(solution["publisher"], {"publisher": solution["publisher"], "total": 0.0,
                                                                  "macc": 0.0, "solutions": 0})
        publisher["total"] += solution["total"]
        publisher["macc"] += solution["total"] if solution["macc_eligible"] else 0.0
        publisher["solutions"] += 1
    month_rows = [{"month": row["month"], "total": round(row["total"], 2), "macc": round(row["macc"], 2),
                   "not_macc": round(row["total"] - row["macc"], 2),
                   "by_publisher": {name: round(cost, 2) for name, cost in row["by_publisher"].items()}}
                  for row in sorted(monthly.values(), key=lambda row: row["month"])]
    total = sum(row["total"] for row in month_rows)
    macc = sum(row["macc"] for row in month_rows)
    return {
        "period": _covered(seen, first, last),
        "total": round(total, 2), "macc": round(macc, 2), "not_macc": round(total - macc, 2),
        "solutions": billed, "adopted": adopted,
        "publishers": sorted(({**p, "total": round(p["total"], 2), "macc": round(p["macc"], 2)}
                              for p in publishers.values()), key=lambda p: -p["total"]),
        "monthly": month_rows,
        "reconciliation": reconcile(entries, first, last),
    }


def reconcile(entries: dict[str, dict], first: str | None, last: str | None) -> list[dict]:
    """Months where the itemised charges and the invoiced Marketplace disagree by
    more than a dollar -- a sign a month's charges were read before they settled."""
    gaps = []
    for account, entry in entries.items():
        for month, data in sorted((entry.get("months") or {}).items()):
            balance, charges = data.get("balance") or {}, data.get("marketplace")
            if not _in_period(month, first, last) or not charges or not balance or balance.get("missing"):
                continue
            itemised = sum(item["cost"] for item in charges.get("items") or [])
            if abs(itemised - balance.get("marketplace", 0.0)) > 1:
                gaps.append({"account": account, "month": month, "itemised": round(itemised, 2),
                             "invoiced": round(balance.get("marketplace", 0.0), 2)})
    return gaps


def _consumption(entries: dict[str, dict], first: str | None, last: str | None) -> float:
    """Invoiced consumption in the period (usage + Marketplace - credits), or Cost
    Management's actual where a month has no balance -- the denominator that says
    how much of a customer's spend is Marketplace."""
    total = 0.0
    for entry in entries.values():
        for month, data in (entry.get("months") or {}).items():
            if not _in_period(month, first, last):
                continue
            balance = data.get("balance") or {}
            if balance and not balance.get("missing"):
                total += balance.get("usage", 0.0) + balance.get("marketplace", 0.0) - balance.get("credits", 0.0)
            else:
                total += sum(((data.get("actual") or {}).get("service") or {}).values())
    return total


def profile_groups(profiles: dict[str, dict]) -> list[tuple[dict, dict[str, dict]]]:
    """Billing profiles that belong to no customer, grouped the way Settings
    suggests (a renewal, or linked under one parent) and named after the group's
    shortest name -- usually the parent enrollment's."""
    groups: dict[str, dict[str, dict]] = {}
    for name, entry in profiles.items():
        groups.setdefault(entry.get("group_key") or entry.get("display_name") or name, {})[name] = entry
    listed = []
    for key, entries in groups.items():
        names = [entry.get("display_name") or account for account, entry in entries.items()]
        listed.append(({"id": f"profile:{key}", "name": min(names, key=len), "parent": None, "profile": True},
                       entries))
    return sorted(listed, key=lambda item: item[0]["name"].lower())


def across_customers(customers: list[tuple[dict, dict[str, dict]]], not_eligible: set[str],
                     first: str | None = None, last: str | None = None) -> dict:
    """Every partner solution across every customer. Each enrollment is counted
    once, under the customer it belongs to, so a group and its affiliates do not
    double-count."""
    seen_accounts: set[str] = set()
    seen: set[str] = set()
    solutions: dict[tuple, dict] = {}
    by_customer: dict[str, dict] = {}
    monthly: dict[str, dict] = {}
    # Who bought what, when: one line per solution, plan, buyer and month -- the
    # export's PivotTable is built on these.
    lines: dict[tuple, dict] = {}
    names = {customer["id"]: customer["name"] for customer, _ in customers}
    for customer, entries in customers:
        own = {account: entry for account, entry in entries.items() if account not in seen_accounts}
        seen_accounts |= set(own)
        record = by_customer.setdefault(customer["id"], {"id": customer["id"], "name": customer["name"],
                                                         "parent": customer.get("parent"),
                                                         "profile": bool(customer.get("profile")),
                                                         "accounts": [], "consumption": 0.0, "total": 0.0,
                                                         "macc": 0.0, "solutions": set(), "publishers": {}})
        record["accounts"] += sorted(own)
        record["consumption"] += _consumption(own, first, last)
        for _, month, item in _items(own, first, last):
            seen.add(month)
            counted = offer_key(item["publisher"], item["offer"]) not in not_eligible
            key = (item["publisher"], item["offer"])
            solution = solutions.setdefault(key, {"publisher": item["publisher"], "offer": item["offer"],
                                                  "macc_eligible": counted, "total": 0.0, "plans": set(),
                                                  "customers": {}, "by_month": {}, "recurring": False})
            solution["total"] += item["cost"]
            solution["plans"].add(item["plan"])
            solution["recurring"] |= bool(item.get("recurring"))
            solution["customers"][customer["name"]] = solution["customers"].get(customer["name"], 0.0) + item["cost"]
            solution["by_month"][month] = solution["by_month"].get(month, 0.0) + item["cost"]
            record["total"] += item["cost"]
            record["macc"] += item["cost"] if counted else 0.0
            record["solutions"].add(key)
            record["publishers"][item["publisher"]] = record["publishers"].get(item["publisher"], 0.0) + item["cost"]
            row = monthly.setdefault(month, {"month": month, "total": 0.0, "macc": 0.0})
            row["total"] += item["cost"]
            row["macc"] += item["cost"] if counted else 0.0
            line = lines.setdefault((item["publisher"], item["offer"], item["plan"], customer["id"], month), {
                "publisher": item["publisher"], "solution": item["offer"], "plan": item["plan"] or "",
                "buyer": customer["name"],
                "group": names.get(customer.get("parent"), customer["name"]),
                "buyer_type": "Billing profile" if customer.get("profile")
                else "Affiliate" if customer.get("parent") else "Customer",
                "month": month, "amount": 0.0, "macc_eligible": counted})
            line["amount"] += item["cost"]

    solution_rows = []
    for solution in solutions.values():
        customers_sorted = sorted(solution["customers"].items(), key=lambda item: -item[1])
        solution_rows.append({
            "publisher": solution["publisher"], "offer": solution["offer"], "macc_eligible": solution["macc_eligible"],
            "total": round(solution["total"], 2), "macc": round(solution["total"], 2) if solution["macc_eligible"] else 0.0,
            "plans": sorted(plan for plan in solution["plans"] if plan),
            "customers": [{"name": name, "total": round(cost, 2)} for name, cost in customers_sorted],
            "adopted_by": len(solution["customers"]),
            "by_month": {month: round(cost, 2) for month, cost in sorted(solution["by_month"].items())},
            "kind": "SaaS" if solution["recurring"] else "Metered",
        })
    solution_rows.sort(key=lambda row: (-abs(row["total"]), -row["adopted_by"]))
    publishers: dict[str, dict] = {}
    for row in solution_rows:
        publisher = publishers.setdefault(row["publisher"], {"publisher": row["publisher"], "total": 0.0, "macc": 0.0,
                                                             "solutions": 0, "customers": set()})
        publisher["total"] += row["total"]
        publisher["macc"] += row["macc"]
        publisher["solutions"] += 1
        publisher["customers"] |= {customer["name"] for customer in row["customers"]}
    customer_rows = [{"id": record["id"], "name": record["name"], "parent": record["parent"],
                      "profile": record["profile"], "accounts": record["accounts"],
                      "consumption": round(record["consumption"], 2),
                      "total": round(record["total"], 2), "macc": round(record["macc"], 2),
                      "solutions": len(record["solutions"]),
                      "top_publisher": max(record["publishers"].items(), key=lambda item: item[1])[0]
                      if record["publishers"] else None}
                     for record in by_customer.values()]
    total = sum(row["total"] for row in monthly.values())
    macc = sum(row["macc"] for row in monthly.values())
    return {
        "period": _covered(seen, first, last),
        "total": round(total, 2), "macc": round(macc, 2), "not_macc": round(total - macc, 2),
        "solutions": solution_rows,
        "publishers": sorted(({"publisher": p["publisher"], "total": round(p["total"], 2), "macc": round(p["macc"], 2),
                               "solutions": p["solutions"], "customers": sorted(p["customers"])}
                              for p in publishers.values()), key=lambda p: -p["total"]),
        "customers": sorted(customer_rows, key=lambda row: -row["total"]),
        "monthly": [{"month": row["month"], "total": round(row["total"], 2), "macc": round(row["macc"], 2)}
                    for row in sorted(monthly.values(), key=lambda row: row["month"])],
        "lines": sorted(({**line, "amount": round(line["amount"], 2)} for line in lines.values()),
                        key=lambda line: (line["publisher"], line["solution"], line["buyer"], line["month"])),
    }


def default_period(today_month: str, months_back: int = 12) -> tuple[str, str]:
    """The last twelve months, through the current one."""
    return months.shift(today_month, -(months_back - 1)), today_month
