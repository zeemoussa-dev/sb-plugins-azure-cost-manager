"""A linked customer's signed value lives on its Customer note, in the vault.

The operator decided (2026-10-17) that the vault is the single source of truth
for what a customer signed: Settings edits the note's `macc_*` properties
through the Entities plugin, and the operator can edit them in Obsidian too.
This plugin's own data keeps the signed value only for a customer with no
Customer note, or while the Entities plugin is missing or older than 1.3.
"""
from __future__ import annotations

SERVICE = "entities.customers"


class CommitmentNotes:
    def __init__(self, api) -> None:
        self._api = api

    def _service(self):
        service = self._api.get_service(SERVICE)
        # Entities before 1.3 has the service without a commitment on its notes.
        return service if service is not None and hasattr(service, "set_commitment") else None

    def available(self) -> bool:
        return self._service() is not None

    def read(self, customer_stem: str) -> dict | None:
        """The note's commitment as Entities reads it -- lenient, so a field the
        operator left blank in Obsidian comes back empty rather than failing."""
        service = self._service()
        return service.commitment(customer_stem) if service else None

    def write(self, customer_stem: str, commitment: dict | None) -> dict | None:
        service = self._service()
        if service is None:
            raise RuntimeError("the Entities plugin 1.3 or later is needed to keep a signed value on a Customer note")
        return service.set_commitment(customer_stem, commitment)
