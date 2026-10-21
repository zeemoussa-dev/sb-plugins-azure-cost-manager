"""Marketplace whitespace (operator, 2026-10-21): what customers buy on the Azure
Marketplace from publishers other than Core42 -- by category and by customer --
and how much of each customer's Marketplace already goes to Core42. Spend that
counts toward a MACC either way is where a Core42 offer could compete.

Azure names no category for a Marketplace offer, so one is read from the
publisher's and offer's names; the first rule that matches wins, and an offer no
rule names is Other.
"""
from __future__ import annotations

import re

from .consumption_analysis import is_core42_publisher

OTHER = "Other"
# Order matters: backup before data ("data protection"), security before networking,
# data before AI ("Oracle AI Database@Azure" is a database).
_CATEGORIES = [
    ("Backup & DR", r"veeam|commvault|rubrik|cohesity|zerto|druva|netbackup|veritas|backup|disaster recovery"),
    ("Security", r"fortinet|fortigate|palo ?alto|check ?point|crowdstrike|zscaler|barracuda|sophos|trend ?micro|"
                 r"imperva|thales|cyberark|okta|darktrace|tenable|qualys|rapid7|f5|firewall|\bwaf\b|security|"
                 r"cyber|threat|siem|identity"),
    ("Data & Analytics", r"databricks|snowflake|informatica|mongodb|confluent|elastic|redis|cloudera|qlik|tableau|"
                         r"talend|fivetran|data|analytics|database|\bsql\b|\betl\b"),
    ("AI & ML", r"openai|anthropic|mistral|cohere|hugging ?face|nvidia|\bai\b|\bllm\b|\bgpt|machine learning|"
                r"cognitive|copilot"),
    ("Networking", r"cisco|netscaler|citrix adc|aviatrix|infoblox|riverbed|sd-?wan|network|load balanc|\bvpn\b"),
    ("DevOps & Apps", r"gitlab|github|jfrog|hashicorp|atlassian|servicenow|\bsap\b|openshift|kubernetes|devops|"
                      r"\bci/cd\b|monitoring|observability|dynatrace|datadog|new relic|splunk"),
    ("OS & images", r"linux|ubuntu|canonical|red ?hat|\brhel\b|suse|centos|rocky|alma|debian|windows server|"
                    r"\bimage\b|ntegral"),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _CATEGORIES]
CATEGORIES = [name for name, _ in _CATEGORIES] + [OTHER]
LISTED = 5


def category_of(publisher: str, offer: str) -> str:
    text = f"{publisher} {offer}"
    return next((name for name, pattern in _COMPILED if pattern.search(text)), OTHER)


def analyse(report: dict) -> dict:
    """From the cross-customer Marketplace report (`marketplace.across_customers`):
    the spend that went to other publishers, by category and by customer, and
    Core42's own share."""
    categories: dict[str, dict] = {}
    customers: dict[str, dict] = {}
    core42_total = third_party_total = 0.0
    for solution in report.get("solutions") or []:
        core42 = is_core42_publisher(solution["publisher"])
        for buyer in solution["customers"]:
            row = customers.setdefault(buyer["name"], {"name": buyer["name"], "core42": 0.0, "third_party": 0.0,
                                                       "macc_eligible": 0.0, "by_category": {}})
            if core42:
                row["core42"] += buyer["total"]
                continue
            category = category_of(solution["publisher"], solution["offer"])
            row["third_party"] += buyer["total"]
            row["macc_eligible"] += buyer["total"] if solution["macc_eligible"] else 0.0
            row["by_category"][category] = row["by_category"].get(category, 0.0) + buyer["total"]
        if core42:
            core42_total += solution["total"]
            continue
        third_party_total += solution["total"]
        category = category_of(solution["publisher"], solution["offer"])
        group = categories.setdefault(category, {"category": category, "total": 0.0, "macc_eligible": 0.0,
                                                 "customers": set(), "solutions": []})
        group["total"] += solution["total"]
        group["macc_eligible"] += solution["total"] if solution["macc_eligible"] else 0.0
        group["customers"] |= {buyer["name"] for buyer in solution["customers"]}
        group["solutions"].append({"publisher": solution["publisher"], "offer": solution["offer"],
                                   "total": solution["total"], "customers": solution["adopted_by"],
                                   "kind": solution.get("kind"), "macc_eligible": solution["macc_eligible"]})
    category_rows = [{**group, "total": round(group["total"], 2), "macc_eligible": round(group["macc_eligible"], 2),
                      "customers": len(group["customers"]),
                      "solutions": sorted(group["solutions"], key=lambda item: -item["total"])[:LISTED]}
                     for group in categories.values()]
    customer_rows = []
    for row in customers.values():
        bought = row["core42"] + row["third_party"]
        if not row["third_party"]:
            continue
        customer_rows.append({"name": row["name"], "third_party": round(row["third_party"], 2),
                              "macc_eligible": round(row["macc_eligible"], 2), "core42": round(row["core42"], 2),
                              "core42_share_pct": round(row["core42"] / bought * 100, 1) if bought else None,
                              "by_category": {name: round(cost, 2) for name, cost in
                                              sorted(row["by_category"].items(), key=lambda item: -item[1])}})
    everything = core42_total + third_party_total
    return {
        "period": report.get("period"),
        "third_party": round(third_party_total, 2),
        "core42": round(core42_total, 2),
        "core42_share_pct": round(core42_total / everything * 100, 1) if everything else None,
        "categories": sorted(category_rows, key=lambda row: -row["total"]),
        "customers": sorted(customer_rows, key=lambda row: -row["third_party"]),
    }
