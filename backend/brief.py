"""A one-click customer brief before a meeting (operator, 2026-10-23), written by
Compass over facts this plugin computed.

The model never produces a figure: `facts` gathers every number from the
reports -- consumption and MACC, solutions and pitches with their sizing,
pipeline and quota, and what the vault says about the customer -- and the
prompt tells it to use those and nothing else, and to say when something is
not known. A brief is kept with the hash of its facts, so it is written again
only when what it was written from changed (or when asked).
"""
from __future__ import annotations

import hashlib
import json

SECTIONS = ["Headline", "Where they stand", "What moved", "What they are building", "What to pitch",
            "Pipeline and quota", "From recent conversations", "Questions to ask", "Watch out for"]
RECENT_MONTHS = 6
TOP = 8


def _r(value):
    return round(value) if isinstance(value, (int, float)) else value


def facts(customer: dict, analysis: dict, quota: dict | None, solutions_view: dict, sizing_by_name: dict,
          vault: dict) -> dict:
    kpis = (analysis.get("dashboard") or {}).get("kpis") or {}
    commitment = analysis.get("commitment") or {}
    closed = [month for month in analysis.get("months") or [] if month["month"] <= (analysis.get("last_closed_month") or "")]
    pipeline = analysis.get("pipeline") or {}
    opportunities = [item for item in pipeline.get("opportunities") or [] if item.get("status") in (None, "Open")]
    return {
        "customer": customer["name"],
        "as_of": analysis.get("as_of"),
        "last_closed_month": analysis.get("last_closed_month"),
        "currency": analysis.get("currency"),
        "consumption": {
            "last_month": _r(kpis.get("latest_total")), "month_on_month_pct": kpis.get("latest_mom_pct"),
            "year_on_year_pct": kpis.get("latest_yoy_pct"), "year_to_date": _r(kpis.get("ytd")),
            "year_to_date_growth_pct": kpis.get("ytd_growth_pct"), "monthly_run_rate_3m": _r(kpis.get("burn_rate_3m")),
            "this_month_so_far": _r(kpis.get("current_so_far")), "next_12_months_forecast": _r(kpis.get("next_12_months")),
            "by_month": [{"month": month["month"], "total": _r(month.get("actual"))} for month in closed[-RECENT_MONTHS:]],
            "top_services_last_month": [{"service": row["name"], "cost": _r(row["cost"]), "change_pct": row.get("change_pct")}
                                        for row in ((analysis.get("top_services") or {}).get("rows") or [])[:TOP]],
            "anomalies": [{"service": item.get("service"), "kind": item.get("kind"), "cost": _r(item.get("cost")),
                           "baseline": _r(item.get("baseline")), "change_pct": item.get("change_pct")}
                          for item in (analysis.get("anomalies") or [])[:5]],
        },
        "commitment": {key: _r(commitment.get(key)) for key in (
            "type", "amount", "start", "end", "consumed", "consumed_pct", "elapsed_pct", "remaining", "run_rate",
            "projected_exhaustion", "projected_at_end", "projected_shortfall", "verdict")} if commitment else None,
        "solutions": [{"solution": item["name"], "play": item["play"], "subscriptions": item["subscriptions"],
                       "monthly_in_them": _r(item["monthly"])} for item in (solutions_view.get("solutions") or [])[:10]],
        "pitches": [{"pitch": item["pitch"], "because_of": item["solution"],
                     "sized_monthly_small_medium_large": sizing_by_name.get(item["solution"])}
                    for item in (solutions_view.get("pitches") or [])[:6]],
        "pipeline": [{"opportunity": item.get("title"), "stage": item.get("stage"),
                      "expected_monthly": _r(item.get("expected_monthly_usd")), "starts": item.get("consumption_start")}
                     for item in opportunities[:TOP]],
        "quota": {key: _r((quota or {}).get(key)) for key in ("baseline", "above_to_date", "above_projected",
                                                               "above_with_pipeline")} if quota else None,
        "pipeline_against_actual": {key: _r(((quota or {}).get("pipeline") or {}).get(key))
                                    for key in ("planned_to_date", "achieved_to_date", "gap", "behind")} if quota else None,
        "vault": vault,
    }


def fingerprint(found: dict) -> str:
    """The facts' identity, as-of date aside: the same data on another day is the same brief."""
    stable = {key: value for key, value in found.items() if key != "as_of"}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def messages(found: dict) -> list[dict[str, str]]:
    headings = "\n".join(f"## {name}" for name in SECTIONS)
    system = (
        "You are a Core42 account strategist preparing a seller for a meeting with an Azure customer in the UAE. "
        "Core42 sells Azure consumption against the customer's MACC and its own offers, including Compass by Core42 "
        "(sovereign, in-country AI models).\n\n"
        "Rules:\n"
        "- Use ONLY the facts in the JSON the user sends. Never invent a number, a date, a person, a product or an "
        "event. Quote figures as given; you may round them (e.g. $5.98M) and add or compare them, nothing more.\n"
        "- When a section has no facts, write one line saying it is not known; do not fill it.\n"
        "- Money is in the given currency; write it compactly ($1.2M, $350K).\n"
        "- Say plainly what matters for the conversation; no generic advice.\n"
        "- Answer in markdown with exactly these headings, in this order, under 450 words in all:\n"
        f"{headings}\n"
        "- 'Headline' is two sentences. 'What to pitch' is at most three bullets, each with its sizing when given. "
        "'Questions to ask' is 3-5 bullets. 'From recent conversations' uses only the vault notes."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": "Facts:\n```json\n" + json.dumps(found, indent=1, default=str) + "\n```"}]
