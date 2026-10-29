"""Analysis of one slice of a customer's bill (operator, 2026-10-29: "subscription and
service analysis per customer... based on the industry, the tags... use Compass"):
some services, some subscriptions or subscription groups, or both, read four ways --
the cost story, optimisation, growth and what the workload likely is.

Pure: the plugin computes every figure from the subscription x service pairs and the
footprints; Compass only reads them. A model's number is never shown as a fact.
"""
from __future__ import annotations

from . import compass, subscription_groups
from .industry import short as industry_short

REPORT_MONTHS = 12
RECENT = 3
TOP = 15
# Tag keys that name what a resource is for -- the ones worth handing Compass.
PURPOSE_KEYS = ("application", "applicationname", "application name", "project", "projectname", "projectcode",
                "workload", "department", "businessunit", "costcenter", "cost center", "environment", "service")
LENSES = ("cost_story", "optimisation", "growth", "architecture")


def _closed(merged: dict, current_month: str) -> list[str]:
    return [month for month in sorted(merged)
            if month < current_month and (merged[month].get("actual") or {}).get("pairs")][-REPORT_MONTHS:]


def _average(monthly: dict[str, float], months: list[str]) -> float:
    return round(sum(monthly.get(month, 0.0) for month in months) / len(months), 2) if months else 0.0


def options(merged: dict, groups: list[dict], current_month: str) -> dict:
    """What can be chosen: the groups, and each subscription and service by its monthly
    average over the last closed months, biggest first."""
    recent = _closed(merged, current_month)[-RECENT:]
    by_subscription: dict[str, float] = {}
    by_service: dict[str, float] = {}
    for month in recent:
        for label, spend in merged[month]["actual"]["pairs"].items():
            for service, cost in spend.items():
                by_subscription[label] = by_subscription.get(label, 0.0) + cost
                by_service[service] = by_service.get(service, 0.0) + cost
    count = max(1, len(recent))
    return {
        "groups": [{"name": group["name"], "match": group["match"]} for group in groups],
        "subscriptions": [{"name": name, "monthly": round(cost / count, 2), "group": subscription_groups.group_of(name, groups)}
                          for name, cost in sorted(by_subscription.items(), key=lambda item: -item[1]) if cost > 0],
        "services": [{"name": name, "monthly": round(cost / count, 2)}
                     for name, cost in sorted(by_service.items(), key=lambda item: -item[1]) if cost > 0],
    }


def validated(focus, groups: list[dict]) -> dict:
    if not isinstance(focus, dict):
        raise ValueError("say what to analyse: services, subscriptions or subscription groups")
    cleaned = {}
    for key in ("groups", "subscriptions", "services"):
        values = focus.get(key) or []
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{key} is a list of names")
        cleaned[key] = sorted({value.strip() for value in values if value.strip()})
    unknown = [name for name in cleaned["groups"] if name not in {group["name"] for group in groups}]
    if unknown:
        raise ValueError(f"no subscription group called {', '.join(unknown)}")
    if not any(cleaned.values()):
        raise ValueError("choose at least one service, subscription or subscription group")
    return cleaned


def key_of(focus: dict) -> str:
    """One analysis per choice, whatever order it was made in."""
    return "|".join(f"{kind}:{','.join(focus[kind])}" for kind in ("groups", "subscriptions", "services"))


def title_of(focus: dict) -> str:
    parts = [*focus["groups"], *(subscription_groups.subscription_name(name) for name in focus["subscriptions"])]
    where = ", ".join(parts) if parts else "all subscriptions"
    return f"{', '.join(focus['services'])} in {where}" if focus["services"] else where


def _in_focus(label: str, focus: dict, groups: list[dict]) -> bool:
    if not focus["groups"] and not focus["subscriptions"]:
        return True
    return label in focus["subscriptions"] or subscription_groups.group_of(label, groups) in focus["groups"]


def figures(merged: dict, focus: dict, groups: list[dict], current_month: str) -> dict:
    """The slice's cost per month, against the customer's whole bill, by service and by
    subscription; the change of the last three closed months against the three before."""
    closed = _closed(merged, current_month)
    shown = closed + ([current_month] if (merged.get(current_month) or {}).get("actual", {}).get("pairs") else [])
    total: dict[str, float] = {}
    whole: dict[str, float] = {}
    by_service: dict[str, dict[str, float]] = {}
    by_subscription: dict[str, dict[str, float]] = {}
    for month in shown:
        for label, spend in merged[month]["actual"]["pairs"].items():
            whole[month] = whole.get(month, 0.0) + sum(spend.values())
            if not _in_focus(label, focus, groups):
                continue
            for service, cost in spend.items():
                if focus["services"] and service not in focus["services"]:
                    continue
                total[month] = total.get(month, 0.0) + cost
                by_service.setdefault(service, {})[month] = by_service.get(service, {}).get(month, 0.0) + cost
                by_subscription.setdefault(label, {})[month] = by_subscription.get(label, {}).get(month, 0.0) + cost
    recent, before = closed[-RECENT:], closed[-2 * RECENT:-RECENT]

    def rows(found: dict[str, dict[str, float]]) -> list[dict]:
        listed = []
        for name, monthly in found.items():
            now, earlier = _average(monthly, recent), _average(monthly, before)
            listed.append({"name": name, "monthly_recent": now, "monthly_before": earlier,
                           "change_pct": round((now - earlier) / earlier * 100, 1) if earlier else None,
                           "by_month": {month: round(monthly.get(month, 0.0), 2) for month in shown}})
        return sorted(listed, key=lambda row: -row["monthly_recent"])

    recent_total, recent_whole = _average(total, recent), _average(whole, recent)
    return {
        "months": shown, "current_month": current_month if current_month in shown else None,
        "by_month": [{"month": month, "cost": round(total.get(month, 0.0), 2),
                      "share_of_bill_pct": round(total.get(month, 0.0) / whole[month] * 100, 1) if whole.get(month) else None}
                     for month in shown],
        "monthly_recent": recent_total, "monthly_before": _average(total, before),
        "change_pct": round((recent_total - _average(total, before)) / _average(total, before) * 100, 1)
        if _average(total, before) else None,
        "share_of_bill_pct": round(recent_total / recent_whole * 100, 1) if recent_whole else None,
        "services": rows(by_service), "subscriptions": rows(by_subscription),
    }


def footprint(entries: dict[str, dict], subscriptions: list[str]) -> dict:
    """The meters and resource groups of the slice's subscriptions, monthly averages over
    each enrollment's footprint period: what the workload is built from."""
    meters: dict[str, float] = {}
    resource_groups: dict[str, float] = {}
    wanted = set(subscriptions)
    for entry in entries.values():
        found = entry.get("footprint") or {}
        span = found.get("months") or 1
        for label, parts in (found.get("subscriptions") or {}).items():
            if label not in wanted:
                continue
            for meter, cost in (parts.get("meters") or {}).items():
                meters[meter] = meters.get(meter, 0.0) + cost / span
            for group, cost in (parts.get("resource_groups") or {}).items():
                resource_groups[group] = resource_groups.get(group, 0.0) + cost / span
    top = lambda found: [{"name": name, "monthly": round(cost, 2)}  # noqa: E731
                         for name, cost in sorted(found.items(), key=lambda item: -item[1])[:TOP] if cost >= 1]
    return {"meters": top(meters), "resource_groups": top(resource_groups)}


def _words(focus: dict, groups: list[dict]) -> set[str]:
    """What the slice is called: its groups' fragments and its subscriptions' names."""
    words = {fragment.lower() for group in groups if group["name"] in focus["groups"] for fragment in group["match"]}
    for label in focus["subscriptions"]:
        words |= {word.lower() for word in subscription_groups.subscription_name(label).replace("-", " ").split() if len(word) >= 4}
    return {word for word in words if len(word) >= 3}


def tag_hints(entries: dict[str, dict], focus: dict, groups: list[dict], month: str | None) -> list[dict]:
    """Tag values that name the slice (a "genomics" application, an "emirati genome platform"
    project), with what they cost in the month: tags carry no service split, so these are
    the whole tagged spend, said as such."""
    words = _words(focus, groups)
    if not words or not month:
        return []
    found: dict[tuple[str, str], float] = {}
    for entry in entries.values():
        for key, dimension in ((entry.get("tags") or {}).get("by_key") or {}).items():
            if key.strip().lower() not in PURPOSE_KEYS:
                continue
            for value, cost in ((dimension.get("months") or {}).get(month) or {}).items():
                if value and any(word in value.lower() for word in words):
                    found[(key.strip(), value)] = found.get((key.strip(), value), 0.0) + cost
    return [{"tag": key, "value": value, "monthly": round(cost, 2)}
            for (key, value), cost in sorted(found.items(), key=lambda item: -item[1])[:TOP] if cost >= 1]


def facts(customer_name: str, currency: str | None, focus: dict, groups: list[dict], found: dict, built_from: dict,
          tags: list[dict], brief_facts: dict | None, finops_candidates: list[dict], solutions: list[dict],
          industry: dict | None) -> dict:
    meters = {item["name"].lower() for item in built_from["meters"]}
    return {key: value for key, value in {
        "customer": customer_name, "currency": currency,
        "slice": {"title": title_of(focus), "services": focus["services"] or "all",
                  "subscription_groups": [group for group in groups if group["name"] in focus["groups"]],
                  "subscriptions": focus["subscriptions"]},
        "cost": {**{key: found[key] for key in ("monthly_recent", "monthly_before", "change_pct", "share_of_bill_pct")},
                 "by_month": [{**point, **({"partial": "billed so far, month not over"}
                                           if point["month"] == found.get("current_month") else {})}
                              for point in found["by_month"]]},
        "by_service": [{key: row[key] for key in ("name", "monthly_recent", "monthly_before", "change_pct")}
                       for row in found["services"][:TOP]],
        "by_subscription": [{key: row[key] for key in ("name", "monthly_recent", "monthly_before", "change_pct")}
                            for row in found["subscriptions"][:TOP]],
        "built_from": built_from,
        "tags_naming_it": tags,
        # The customer's steady on-demand usage whose meter the slice's subscriptions bill.
        "savings_candidates": [item for item in finops_candidates
                               if item["meter"].split("|")[0].strip().lower() in meters][:10],
        "solutions_in_these_subscriptions": solutions,
        "industry": industry_short(industry) if (industry or {}).get("industry") else None,
        "customer_context": (brief_facts or {}).get("customer_context"),
        "seller_says": (brief_facts or {}).get("seller_says"),
        "commitment": (brief_facts or {}).get("commitment"),
        "how_to_read": [
            "Monthly figures are averages of the last three closed months ('monthly_recent') against the three before.",
            "'built_from' is averaged over the footprint period and covers every service in those subscriptions.",
            "'tags_naming_it' is the whole spend carrying that tag value, on every service: never the slice's share.",
            *((brief_facts or {}).get("how_to_read") or []),
        ],
    }.items() if value not in (None, [], {})}


def messages(facts_given: dict, rules: str, industry_rule: str, context_rule: str) -> list[dict]:
    return [{"role": "system", "content": (
        "Analyse this slice of a customer's Azure bill for a Core42 seller, four ways. "
        "1. cost_story: what it costs, how it moved and where (which services and subscriptions), the likely reason. "
        "A month marked partial is still being billed: never read it as a fall. "
        "2. architecture: what the workload most likely is, from its services, meters, resource groups, subscription "
        "names and tags (e.g. a genome sequencing pipeline: blob storage tiers, batch compute, backup), with the "
        "evidence for it and how sure you are. "
        "3. optimisation: savings that keep the workload whole (storage tiers and lifecycle, reservations or savings "
        "plans for the steady candidates given, rightsizing, backup retention), each with what to check first; frame "
        "savings as money to reinvest, a seller is paid on consumption. "
        "4. growth: what to pitch next given the industry, the customer's stage and this workload (Core42's offers "
        "included), each with why it fits. "
        + industry_rule + " " + context_rule + "\n"
        'Answer with one JSON object: {"headline": <one sentence>, "cost_story": <markdown, at most 120 words>, '
        '"architecture": {"workload": <one sentence>, "confidence": "high"|"medium"|"low", "evidence": [<up to 5>]}, '
        '"optimisation": [{"move": <short>, "why": <one sentence>, "check_first": <one sentence>}], '
        '"growth": [{"pitch": <short>, "why": <one sentence>}], "questions": [<up to 3 for the customer>]}. '
        "At most 5 optimisation moves and 4 pitches. No figure that is not in the facts. Nothing else."
        f"\n\nRules:\n- {rules}")},
        {"role": "user", "content": "Facts:\n" + compass.json_block(facts_given)}]


def check(reply: str) -> dict:
    found = compass.json_object(reply)
    architecture = found.get("architecture") if isinstance(found.get("architecture"), dict) else {}

    def items(name: str, keys: tuple[str, ...], most: int) -> list[dict]:
        return [{key: str(item.get(key) or "")[:300] for key in keys}
                for item in (found.get(name) or []) if isinstance(item, dict) and item.get(keys[0])][:most]

    return {
        "headline": str(found.get("headline") or "")[:300],
        "cost_story": str(found.get("cost_story") or "")[:1200],
        "architecture": {"workload": str(architecture.get("workload") or "")[:300],
                         "confidence": architecture.get("confidence") if architecture.get("confidence") in ("high", "medium", "low") else "low",
                         "evidence": [str(item)[:240] for item in (architecture.get("evidence") or [])[:5]]},
        "optimisation": items("optimisation", ("move", "why", "check_first"), 5),
        "growth": items("growth", ("pitch", "why"), 4),
        "questions": [str(item)[:240] for item in (found.get("questions") or [])[:3]],
    }
