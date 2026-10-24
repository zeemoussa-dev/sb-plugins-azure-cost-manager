"""More FinOps findings, computed before any model reads them (operator, 2026-10-24:
"use LLM inside the FinOps tab to the max"): what Azure Hybrid Benefit could take off
the bill, which up-front commitments may come up for renewal, and what looks like
waste worth asking about. Pure, like `finops`; Compass explains and ranks these, it
never computes them.
"""
from __future__ import annotations

from . import months

HYBRID_WINDOW = 3
# License meters Azure Hybrid Benefit removes when the customer brings its own licenses
# (Windows Server and SQL Server with Software Assurance) or subscriptions (RHEL, SUSE).
HYBRID_PRODUCTS = (
    ("Windows Server", "Windows Server", "Azure Hybrid Benefit for Windows Server (licenses with Software Assurance)"),
    ("SQL Server", "SQL Server ", "Azure Hybrid Benefit for SQL Server (licenses with Software Assurance)"),
    ("Red Hat Enterprise Linux", "Red Hat Enterprise Linux", "Azure Hybrid Benefit for Linux (Red Hat subscriptions)"),
    ("SUSE Linux", "SUSE", "Azure Hybrid Benefit for Linux (SUSE subscriptions)"),
)
# Not a license on a VM: SQL Server billed through Arc is its own offer.
HYBRID_EXCLUDED = ("SQL Server on Azure Arc",)
HYBRID_MIN_MONTHLY = 100.0

RENEWAL_LOOKAHEAD = 6
TERMS = (12, 36)

WASTE_MIN = 300.0
NON_PRODUCTION = {"Test", "Development", "Sandbox"}
PREMIUM_DISKS = ("Premium SSD", "Ultra Disk", "Premium SSD v2")
MONITORING = {"Log Analytics", "Azure Monitor", "Sentinel"}
MONITORING_SHARE = 0.3
MONITORING_MIN = 2000.0
STORAGE_ONLY = {"Storage", "Backup", "Azure NetApp Files", "Azure Files", "Bandwidth"}
STORAGE_ONLY_MIN = 1000.0


def hybrid_benefit(actual: dict[str, dict[str, float]], closed: list[str]) -> list[dict]:
    """License meters of the last closed months, monthly, by product: the most Azure
    Hybrid Benefit could take off -- if the customer holds the licenses."""
    window = closed[-HYBRID_WINDOW:]
    if not window:
        return []
    found: dict[str, dict] = {}
    for month in window:
        for key, cost in (actual.get(month) or {}).items():
            meter = key.split("|")[0].strip()
            if any(meter.startswith(excluded) for excluded in HYBRID_EXCLUDED):
                continue
            for product, prefix, program in HYBRID_PRODUCTS:
                if meter.startswith(prefix):
                    row = found.setdefault(product, {"product": product, "program": program, "meters": {}, "monthly": 0.0})
                    row["meters"][meter] = row["meters"].get(meter, 0.0) + cost / len(window)
                    row["monthly"] += cost / len(window)
                    break
    rows = [{**row, "monthly": round(row["monthly"], 2),
             "meters": {meter: round(cost, 2) for meter, cost in sorted(row["meters"].items(), key=lambda item: -item[1])}}
            for row in found.values() if row["monthly"] >= HYBRID_MIN_MONTHLY]
    return sorted(rows, key=lambda row: -row["monthly"])


def renewals(purchases: list[dict], current_month: str) -> list[dict]:
    """When each commitment bought up front would renew, on a one-year or a three-year
    term -- the data does not say which, so both are given -- and which falls soon."""
    horizon = months.shift(current_month, RENEWAL_LOOKAHEAD)
    found = []
    for purchase in purchases:
        dates = {f"{term // 12}y": months.shift(purchase["month"], term) for term in TERMS}
        soon = [term for term, month in dates.items() if months.shift(current_month, -1) <= month <= horizon]
        found.append({"bought": purchase["month"], "amount": purchase["bought_up_front"], "renews_if": dates,
                      "soon": soon})
    return found


def waste(subscriptions: list[dict]) -> list[dict]:
    """What looks like waste in a subscription's last closed months, to ask the customer's
    engineers about -- never stated as waste: premium disks where nothing is production,
    monitoring out of proportion, and subscriptions that only store."""
    found = []
    for row in subscriptions:
        services = {item["name"]: item["monthly"] for item in row.get("top_services") or []}
        meters = {item["name"]: item["monthly"] for item in row.get("top_meters") or []}
        monthly = row.get("monthly") or 0.0
        if row.get("environment") in NON_PRODUCTION:
            premium = sum(cost for meter, cost in meters.items() if meter.startswith(PREMIUM_DISKS))
            if premium >= WASTE_MIN:
                found.append({"subscription": row["subscription"], "kind": "premium-disks-non-production",
                              "monthly_at_stake": round(premium, 2),
                              "detail": f"Premium or Ultra disks in a {row['environment'].lower()} subscription"})
        watching = sum(cost for service, cost in services.items() if service in MONITORING)
        if watching >= MONITORING_MIN and monthly and watching / monthly >= MONITORING_SHARE:
            found.append({"subscription": row["subscription"], "kind": "monitoring-share",
                          "monthly_at_stake": round(watching, 2),
                          "detail": f"Monitoring and log ingestion is {round(watching / monthly * 100)}% of the subscription"})
        # `top_services` is the top five only: they must also carry nearly all the spend.
        if (monthly >= STORAGE_ONLY_MIN and services and set(services) <= STORAGE_ONLY
                and sum(services.values()) >= 0.95 * monthly):
            found.append({"subscription": row["subscription"], "kind": "storage-only",
                          "monthly_at_stake": round(monthly, 2),
                          "detail": "Only storage and backup are billed here: data kept after a workload left?"})
    return sorted(found, key=lambda item: -item["monthly_at_stake"])
