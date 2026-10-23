"""Compass places the subscriptions the rules could not (operator, 2026-10-23: the
second part of LLM enablement).

The rules (`solutions`) stay the source of truth; Compass reads an unplaced
subscription's services, meters and resource-group names and says which solution
it most likely is -- an existing one from the catalog, or a NEW one, proposed as a
pattern that, once written into the vault as a Solution note, lets the rules place
it from then on without asking again. Every suggestion carries its reason and is
shown as Compass's, never as the rules'.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import solution_plays, solutions

BATCH = 12
CONFIDENCE = ("high", "medium", "low")


class PlacementError(ValueError):
    pass


def subject(customer: dict, row: dict) -> dict:
    """What Compass is shown about one subscription, and nothing else."""
    return {"key": f"{customer['id']}|{row['subscription']}", "customer": customer["name"],
            "subscription": row["subscription"], "monthly": round(row["monthly"]),
            "environment": row.get("environment"),
            "services": [f"{item['name']} ${round(item['monthly'])}/mo" for item in row.get("top_services") or []],
            "meters": [f"{item['name']} ${round(item['monthly'])}/mo" for item in row.get("top_meters") or []],
            "resource_groups": list(row.get("resource_groups") or [])}


def fingerprint(item: dict) -> str:
    """A subscription is asked about again only when what it runs changes."""
    stable = {key: item[key] for key in ("subscription", "services", "meters", "resource_groups")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def messages(items: list[dict], catalog: list[dict]) -> list[dict[str, str]]:
    known = [{"id": pattern["id"], "name": pattern["name"], "play": pattern["play"],
              "description": pattern.get("description") or ""} for pattern in catalog]
    plays = [play for play in solution_plays.PLAYS if play not in (solution_plays.UNASSIGNED,)]
    system = (
        "You classify Azure subscriptions into the solution a customer is building, for Core42 solution sellers. "
        "Each subscription comes with its largest services, its meter subcategories (where products such as Azure "
        "OpenAI, GPU series or Marketplace offers show) and its resource-group names.\n\n"
        "For EACH subscription answer one JSON object:\n"
        '{"key": <the key given>, "solution_id": <an id from the catalog, or null>, '
        '"new_solution": <null, or {"name", "play", "description", "requires", "supports", "names", "pitches"}>, '
        '"confidence": "high"|"medium"|"low", "reason": <one sentence citing the services, meters or names>}\n\n'
        "Rules:\n"
        "- Prefer an existing catalog solution when it fits. Propose new_solution only for a workload the catalog "
        "does not cover; give it a short name and a play from: " + ", ".join(plays) + ".\n"
        "- A new_solution's requires is a list of groups of signals (one signal of each group must be present); a "
        "signal is \"service:<exact service name as given>\", \"meter:<words from a meter>\" or \"name:<word in a "
        "subscription or resource-group name>\". supports and names are lists; pitches is a list of "
        "{\"missing\": [signals], \"pitch\": <what to sell when the customer runs none of them>}.\n"
        "- If nothing can be said, solution_id and new_solution are null, confidence low, and the reason says why.\n"
        "- Use only what is given. Answer with a JSON array, one object per subscription, and nothing else."
    )
    user = ("Catalog:\n```json\n" + json.dumps(known, indent=1) + "\n```\n\nSubscriptions:\n```json\n"
            + json.dumps([{key: item[key] for key in item if key != "customer"} for item in items], indent=1)
            + "\n```")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _json_array(reply: str) -> list:
    """The first JSON array in the reply, fenced or not."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", reply, re.DOTALL)
    text = fenced.group(1) if fenced else reply[reply.find("["):reply.rfind("]") + 1]
    try:
        found = json.loads(text)
    except ValueError as exc:
        raise PlacementError(f"Compass did not answer with the JSON asked for ({exc})") from exc
    if not isinstance(found, list):
        raise PlacementError("Compass did not answer with a list")
    return found


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "proposed"


def parse(reply: str, items: list[dict], catalog: list[dict]) -> dict[str, dict]:
    """`key -> suggestion`, each checked: an unknown solution id is dropped, and a new
    solution's pattern is validated -- one that does not hold keeps its name and reason
    but says its rules need fixing."""
    by_key = {item["key"]: item for item in items}
    names = {pattern["id"]: pattern["name"] for pattern in catalog}
    found: dict[str, dict] = {}
    for answer in _json_array(reply):
        if not isinstance(answer, dict) or answer.get("key") not in by_key:
            continue
        solution_id = answer.get("solution_id") if answer.get("solution_id") in names else None
        proposal = answer.get("new_solution") if isinstance(answer.get("new_solution"), dict) else None
        suggestion = {"solution_id": solution_id, "solution": names.get(solution_id),
                      "confidence": answer.get("confidence") if answer.get("confidence") in CONFIDENCE else "low",
                      "reason": str(answer.get("reason") or "")[:400], "proposal": None}
        if proposal and not solution_id and str(proposal.get("name") or "").strip():
            pattern = {"id": _slug(str(proposal["name"])), "name": str(proposal["name"]).strip(),
                       "play": proposal.get("play"), "description": str(proposal.get("description") or ""),
                       "requires": proposal.get("requires"), "supports": proposal.get("supports") or [],
                       "names": proposal.get("names") or [], "pitches": proposal.get("pitches") or []}
            try:
                solutions.validated([pattern])
                pattern["valid"], pattern["problem"] = True, None
            except solutions.PatternError as exc:
                pattern["valid"], pattern["problem"] = False, str(exc)
            suggestion["proposal"] = pattern
        found[answer["key"]] = suggestion
    return found


def proposals(suggestions: dict[str, dict], subjects: dict[str, dict]) -> list[dict]:
    """New solutions Compass proposed, merged by name, with the subscriptions behind them."""
    merged: dict[str, dict] = {}
    for key, suggestion in suggestions.items():
        proposal = suggestion.get("proposal")
        if not proposal:
            continue
        row = merged.setdefault(proposal["name"].lower(), {**proposal, "subscriptions": [], "customers": set(),
                                                            "monthly": 0.0})
        item = subjects.get(key) or {}
        row["subscriptions"].append({"key": key, "subscription": item.get("subscription"), "customer": item.get("customer")})
        if item.get("customer"):
            row["customers"].add(item["customer"])
        row["monthly"] += item.get("monthly") or 0
    return sorted(({**row, "customers": sorted(row["customers"]), "monthly": round(row["monthly"])}
                   for row in merged.values()), key=lambda row: -row["monthly"])


def solution_note(proposal: dict, today: str) -> str:
    """A proposal as a Solution note to paste into the vault (Work/Solutions/): once it is
    there, the rules place these subscriptions themselves."""
    pattern = {key: proposal[key] for key in ("requires", "supports", "names", "pitches") if proposal.get(key) is not None}
    play = proposal.get("play") or ""
    tag = "solution/" + play.lower().replace(" & ", "-").replace(" ", "-") if play else "solution/proposed"
    return f"""---
type: "Solution"
name: "{proposal['name']}"
solution_id: "{proposal['id']}"
play: "{play}"
status: "draft"
last_refreshed: "{today}"
tags: ["kind/solution", "{tag}"]
---

**Solution play:** {play} · proposed by Compass from customers' subscriptions; review before relying on it.

## Summary

{proposal.get('description') or ''}

## Architecture

## What the customer is building

## How to recognise it in the bill

## Pitches

## Sizing

## Playbooks

## Pattern

```json
{json.dumps(pattern, indent=2)}
```

## Sources
"""
