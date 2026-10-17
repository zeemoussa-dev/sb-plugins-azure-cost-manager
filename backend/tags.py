"""Cost by tag: which spellings of a business tag an enrollment uses, and what
each value cost.

Tags in the wild are inconsistent (2026-10-17, one customer's enrollment: 480
keys; `projectname`, `project name`, `project_name`, `pojectname`,
`x_projectname`; `prd`, `prod`, `production`). So a *dimension* -- Environment,
Project, ... -- is found among an enrollment's keys by spelling, and its values
are folded before they are added up.

Pure functions; the sync stores, per enrollment, each spelling's cost by value
and month (`entry["tags"]`).
"""
from __future__ import annotations

import re

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "Environment": ("environment", "env", "environmentname", "environmenttype", "envtype", "stage"),
    "Project": ("project", "projectname", "projectcode", "projectshort"),
    "Application": ("application", "applicationname", "app", "appname", "appcode", "applicationcode", "workload"),
    "Business unit": ("businessunit", "bu", "department", "division", "subsidiary", "groupcompany", "company"),
    # Not "createdby": two edits from "createdon", a date, and it names who clicked, not who owns.
    "Owner": ("owner", "projectowner", "applicationowner", "technicalowner", "resourceowner", "vmowner",
              "businessowner"),
    "Cost centre": ("costcenter", "costcentre", "costcode", "billingcode", "chargecode", "costgroup"),
}
# A spelling within this many edits of a dimension's name still counts:
# "environemnt", "envirornment", "pojectname", "buisnessunit" -- if it starts with the
# same letter: "revision" is two edits from "division" and holds timestamps.
TYPO_DISTANCE = 2
# Spellings queried per dimension and enrollment -- each one is a Cost Management
# query on the same per-sign-in budget as the sync.
MAX_SPELLINGS = 4
UNTAGGED = "(untagged)"

ENVIRONMENT_VALUES = {
    "production": "Production", "prod": "Production", "prd": "Production", "live": "Production", "prod1": "Production",
    "development": "Development", "dev": "Development", "develop": "Development",
    "test": "Test", "testing": "Test", "uat": "Test", "qa": "Test", "sit": "Test", "staging": "Test", "stg": "Test",
    "preprod": "Test", "preproduction": "Test", "nonproduction": "Non-production", "nonprod": "Non-production",
    "np": "Non-production", "npr": "Non-production", "nprd": "Non-production", "nonprd": "Non-production",
    "dr": "DR", "disasterrecovery": "DR",
    "poc": "PoC", "pilot": "PoC", "sandbox": "Sandbox", "sbx": "Sandbox",
}


def normalized(key: str) -> str:
    """A tag key with case, spaces, `_`, `-` and an `x_` prefix taken out."""
    key = key.strip().lower()
    key = re.sub(r"^x_", "", key)
    return re.sub(r"[^a-z0-9]", "", key)


def _distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > TYPO_DISTANCE:
        return TYPO_DISTANCE + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def dimension_of(key: str) -> str | None:
    """The dimension a tag key spells, or None. Short names ("env", "app", "bu")
    must match exactly: two edits away from three letters is anything."""
    plain = normalized(key)
    if not plain:
        return None
    best: tuple[int, str] | None = None
    for dimension, names in DIMENSIONS.items():
        for name in names:
            typo_allowed = len(name) >= 6 and plain[0] == name[0]
            distance = 0 if plain == name else (_distance(plain, name) if typo_allowed else TYPO_DISTANCE + 1)
            if distance <= TYPO_DISTANCE and (best is None or distance < best[0]):
                best = (distance, dimension)
    return best[1] if best else None


def spellings(keys: list[str]) -> dict[str, list[str]]:
    """Per dimension, the enrollment's keys that spell it -- the exact names
    first, then the nearest typos -- at most `MAX_SPELLINGS`."""
    found: dict[str, list[tuple[int, str]]] = {}
    for key in keys:
        dimension = dimension_of(key)
        if not dimension:
            continue
        plain = normalized(key)
        rank = min(_distance(plain, name) if plain != name else 0 for name in DIMENSIONS[dimension])
        found.setdefault(dimension, []).append((rank, key))
    return {dimension: [key for _, key in sorted(ranked, key=lambda item: (item[0], len(item[1]), item[1]))][:MAX_SPELLINGS]
            for dimension, ranked in found.items()}


def folded_value(dimension: str, value: str) -> str:
    plain = (value or "").strip()
    if not plain:
        return UNTAGGED
    if dimension == "Environment":
        return ENVIRONMENT_VALUES.get(re.sub(r"[^a-z0-9]", "", plain.lower()), plain)
    return plain


def _spelled_once(values: dict[str, float]) -> dict[str, float]:
    """Values that differ only in case or spacing, added up under the most
    expensive spelling."""
    groups: dict[str, dict[str, float]] = {}
    for value, cost in values.items():
        groups.setdefault(re.sub(r"\s+", " ", value.strip().lower()), {})[value] = cost
    return {max(spelled, key=spelled.get): sum(spelled.values()) for spelled in groups.values()}


def dimension_by_month(entries: dict[str, dict], dimension: str, totals: dict[str, float]) -> dict[str, dict[str, float]]:
    """Per month, a dimension's cost by folded value across the enrollments --
    every spelling added up -- and what no spelling tagged, against `totals`
    (the month's actual cost)."""
    by_month: dict[str, dict[str, float]] = {}
    for entry in entries.values():
        for key, spelling_data in (((entry.get("tags") or {}).get("by_key") or {}).items()):
            # Judged by today's rules, not the label stored when it was synced.
            if dimension_of(key) != dimension:
                continue
            for month, values in (spelling_data.get("months") or {}).items():
                target = by_month.setdefault(month, {})
                for value, cost in values.items():
                    if not value.strip() or abs(cost) < 0.01:
                        continue  # untagged under this spelling: may be tagged under another
                    name = folded_value(dimension, value)
                    target[name] = target.get(name, 0.0) + cost
    result = {}
    for month, values in sorted(by_month.items()):
        values = _spelled_once(values)
        tagged = sum(values.values())
        untagged = max(0.0, totals.get(month, 0.0) - tagged)
        if untagged >= 0.01:
            values[UNTAGGED] = untagged
        result[month] = {name: round(cost, 2) for name, cost in sorted(values.items(), key=lambda item: -item[1])}
    return result


def report(entries: dict[str, dict], totals: dict[str, float], current_month: str) -> dict:
    """Every dimension found on these enrollments: its values by month, its
    coverage in the last closed month, and the spellings behind it."""
    keys = sorted({key for entry in entries.values() for key in ((entry.get("tags") or {}).get("keys") or [])})
    found = spellings(keys)
    dimensions = []
    for dimension in DIMENSIONS:
        months = dimension_by_month(entries, dimension, totals)
        if not months and dimension not in found:
            continue
        closed = [month for month in months if month < current_month]
        last = closed[-1] if closed else None
        tagged = sum(cost for name, cost in months.get(last, {}).items() if name != UNTAGGED) if last else 0.0
        total = totals.get(last, 0.0) if last else 0.0
        dimensions.append({
            "dimension": dimension,
            "spellings": found.get(dimension, []),
            "all_spellings": sorted(key for key in keys if dimension_of(key) == dimension),
            "months": months,
            "last_month": last,
            "coverage_pct": round(tagged / total * 100, 1) if total else None,
            "values": len({name for values in months.values() for name in values if name != UNTAGGED}),
        })
    return {"tag_keys": len(keys), "dimensions": dimensions}
