"""Where a customer stands, as the seller knows it (operator, 2026-10-24: "the option to
modify where the customer is in digitalization, how the data is looking now -- a good
input before recommending a solution").

A few short fields per customer, kept in the plugin's data so they move with an export.
Compass may draft them from the reports and the vault, but a draft is only shown: what is
saved is the seller's. Every feature that recommends -- the brief, what to pitch, a use
case, a draft -- is handed the saved fields and told to treat them as fact.
"""
from __future__ import annotations

# (key, label, what to write) -- the order the card shows them in.
FIELDS = (
    ("digital_maturity", "Digital maturity", "Where they are: e.g. paper-heavy, digitising core processes, cloud-first, AI-native"),
    ("data_today", "Their data today", "Where it lives, how clean and connected it is, what platform, who owns it"),
    ("cloud_adoption", "Cloud adoption", "On-premises, hybrid, mid-migration, mostly Azure; landing zone; other clouds"),
    ("ai_readiness", "AI readiness", "Pilots, production use, governance in place, skills, appetite"),
    ("priorities", "Top priorities", "What leadership is pushing this year, in their words"),
    ("constraints", "Constraints", "Regulation, residency, budget, skills, procurement, politics"),
)
KEYS = tuple(key for key, _, _ in FIELDS)
LONGEST = 800


class CustomerProfile:
    def __init__(self, read, write, today) -> None:
        self._read = read
        self._write = write
        self._today = today

    def of(self, customer_id: str) -> dict:
        kept = (self._read() or {}).get(customer_id) or {}
        return {"fields": {key: kept.get("fields", {}).get(key, "") for key in KEYS}, "updated": kept.get("updated"),
                "labels": [{"key": key, "label": label, "hint": hint} for key, label, hint in FIELDS]}

    def save(self, customer_id: str, fields: dict) -> dict:
        cleaned = {key: " ".join(str((fields or {}).get(key) or "").split())[:LONGEST] for key in KEYS}
        state = self._read() or {}
        if any(cleaned.values()):
            state[customer_id] = {"fields": cleaned, "updated": self._today().isoformat()}
        else:
            state.pop(customer_id, None)
        self._write(state)
        return self.of(customer_id)

    def handed(self, customer_id: str) -> dict | None:
        """What a prompt is handed: the filled fields under their labels, or None."""
        fields = self.of(customer_id)["fields"]
        filled = {label: fields[key] for key, label, _ in FIELDS if fields.get(key)}
        return filled or None
