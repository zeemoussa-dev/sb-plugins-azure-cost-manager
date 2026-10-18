"""A linked customer's signed value lives on its Customer note, in the vault.

The operator decided (2026-10-17) that the vault is the single source of truth
for what a customer signed: Settings edits the note's `macc_*` properties
through the Entities plugin, and the operator can edit them in Obsidian too.
This plugin's own data keeps the signed value only for a customer with no
Customer note, or while the Entities plugin is missing or older than 1.3.

Reads are cached for a minute. Every customer listing reads every linked note,
and once all 99 customers had notes (2026-10-18) a listing took 9-15 s -- each
Entities read scans the vault index. A save here updates the cache at once; an
edit made in Obsidian shows within `CACHE_FOR`.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

SERVICE = "entities.customers"
CACHE_FOR = 60.0


class CommitmentNotes:
    def __init__(self, api, clock: Callable[[], float] = time.monotonic) -> None:
        self._api = api
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: dict[str, tuple[float, dict | None]] = {}

    def _service(self):
        service = self._api.get_service(SERVICE)
        # Entities before 1.3 has the service without a commitment on its notes.
        return service if service is not None and hasattr(service, "set_commitment") else None

    def available(self) -> bool:
        return self._service() is not None

    def read(self, customer_stem: str) -> dict | None:
        """The note's commitment as Entities reads it -- lenient, so a field the
        operator left blank in Obsidian comes back empty rather than failing. A
        failed read (no such note) is never cached: it is asked again next time."""
        with self._lock:
            hit = self._cached.get(customer_stem)
            if hit and self._clock() - hit[0] < CACHE_FOR:
                return hit[1]
        service = self._service()
        if service is None:
            return None
        value = service.commitment(customer_stem)
        with self._lock:
            self._cached[customer_stem] = (self._clock(), value)
        return value

    def write(self, customer_stem: str, commitment: dict | None) -> dict | None:
        service = self._service()
        if service is None:
            raise RuntimeError("the Entities plugin 1.3 or later is needed to keep a signed value on a Customer note")
        # Entities refuses a field it does not know; before 1.8 it has no `affiliates`.
        known = (getattr(service, "COMMITMENT_FIELDS", None)
                 or ("type", "amount", "currency", "start", "end", "note", "include_marketplace", "subtract_credits"))
        if commitment is not None:
            commitment = {field: value for field, value in commitment.items() if field in known}
        try:
            written = service.set_commitment(customer_stem, commitment)
        except Exception:
            with self._lock:
                self._cached.pop(customer_stem, None)
            raise
        with self._lock:
            self._cached[customer_stem] = (self._clock(), written)
        return written
