"""What the seller has told Compass about a customer (operator, 2026-10-23: "Brief me
has no memory").

One list per customer: an answer given in Explain this, a correction or addition to
the brief, anything the seller adds. Every Compass feature that writes about the
customer -- the brief, Explain this, drafts, sizing, next best actions -- is handed
it and told to treat it as fact. Kept in the plugin's data, so it moves with the
data export; the seller sees every line and can remove it.
"""
from __future__ import annotations

import uuid

LONGEST = 1000
KEPT = 60
# What a prompt is handed: the latest lines; a long-lived account must not crowd out the facts.
HANDED = 20


class CustomerMemory:
    def __init__(self, read, write, today) -> None:
        self._read = read
        self._write = write
        self._today = today

    def of(self, customer_id: str) -> list[dict]:
        return list((self._read() or {}).get(customer_id) or [])

    def add(self, customer_id: str, said: str, source: str = "you") -> list[dict]:
        said = " ".join(str(said or "").split())[:LONGEST]
        if not said:
            raise ValueError("say what Compass should remember")
        state = self._read() or {}
        lines = list(state.get(customer_id) or [])
        lines.append({"id": uuid.uuid4().hex[:10], "said": said, "on": self._today().isoformat(), "source": source})
        state[customer_id] = lines[-KEPT:]
        self._write(state)
        return state[customer_id]

    def remove(self, customer_id: str, line_id: str) -> list[dict]:
        state = self._read() or {}
        lines = [line for line in state.get(customer_id) or [] if line.get("id") != line_id]
        state[customer_id] = lines
        self._write(state)
        return lines

    def handed(self, customer_id: str) -> list[dict]:
        """The lines a prompt gets: what was said, when, and about what."""
        return [{"said": line["said"], "on": line["on"], "about": line.get("source")}
                for line in self.of(customer_id)[-HANDED:]]
