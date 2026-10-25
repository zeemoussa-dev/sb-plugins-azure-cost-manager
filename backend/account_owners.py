"""Who covers a customer: its account manager, segment and PSS, as the Customer note
names them (operator, 2026-10-25: the pipeline review per account manager; "everyone
sees everything", so these are groupings, never permissions).

    account_manager: "[[ajay.malik@core42.ai|Ajay Malik]]"
    segment: "Strategic Accounts"
    pss: ["[[dalbir.maan@core42.ai|Dalbir Maan]]"]

A person is linked by the Person note's stem, the email, with the name as alias; a link
without an alias reads the Person note's `name`. An affiliate with none of its own takes
its parent's, field by field. Read through the Plugin API's index, never by walking
folders.
"""
from __future__ import annotations

import re

PERSON_TYPE = "Person"
NO_MANAGER = "No account manager"
_LINK = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")


def person(value, names: dict[str, str]) -> dict | None:
    """`"[[email|Name]]"`, `"[[email]]"` or a plain name -> `{"key", "name"}`."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _LINK.search(text)
    if not match:
        return {"key": text, "name": text}
    key = match.group(1).strip()
    return {"key": key, "name": (match.group(2) or names.get(key.lower()) or key).strip()}


def _people(value, names: dict[str, str]) -> list[dict]:
    items = value if isinstance(value, list) else ([value] if value else [])
    return [found for found in (person(item, names) for item in items) if found]


class AccountOwners:
    def __init__(self, api) -> None:
        self._api = api

    def of(self, stems: dict[str, tuple[str | None, str | None]]) -> dict[str, dict]:
        """Customer id -> `{"account_manager", "segment", "pss", "inherited"}` from one read
        of the index; `stems` is id -> (its Customer note's stem, its parent's)."""
        vault = getattr(self._api, "vault", None)
        if not vault:
            return {customer_id: covering({}, {}) for customer_id in stems}
        entries = vault.entries()
        names = {entry["stem"].lower(): str((entry.get("frontmatter") or {}).get("name") or "").strip()
                 for entry in entries if str((entry.get("frontmatter") or {}).get("type") or "") == PERSON_TYPE}
        names = {stem: name for stem, name in names.items() if name}
        hubs = {entry["stem"].lower(): entry.get("frontmatter") or {} for entry in entries}
        return {customer_id: covering(hubs.get((stem or "").lower(), {}), hubs.get((parent or "").lower(), {}), names)
                for customer_id, (stem, parent) in stems.items()}


def covering(own: dict, parent: dict, names: dict[str, str] | None = None) -> dict:
    """One customer's coverage: its own fields, else its parent's."""
    names = names or {}
    found, inherited = {}, []
    for key in ("account_manager", "segment", "pss"):
        value = own.get(key)
        if value in (None, "", []):
            value = parent.get(key)
            if value not in (None, "", []):
                inherited.append(key)
        found[key] = value
    return {"account_manager": person(found["account_manager"], names),
            "segment": str(found["segment"] or "").strip() or None,
            "pss": _people(found["pss"], names), "inherited": inherited}
