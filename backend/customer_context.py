"""What the vault says about a customer, for its brief: the Customer note's summary
and the latest notes that link to it (meetings, threads, captures).

Read through the Plugin API's index -- a note links to the customer by its
Customer note's stem -- never by walking folders.
"""
from __future__ import annotations

NOTE_EXCERPT = 600
CUSTOMER_EXCERPT = 1500
RECENT_NOTES = 6
# Notes that are about a conversation or a document; templates and reference notes are left out.
SKIPPED_TYPES = {"Solution", "Playbook", "AzureDoc", "Technology", "Insight", "Template"}


def _date(frontmatter: dict) -> str:
    for key in ("date", "start", "received", "sent", "created", "last_refreshed"):
        value = frontmatter.get(key)
        if value:
            return str(value)[:10]
    return ""


class CustomerContext:
    def __init__(self, api) -> None:
        self._api = api

    def about(self, customer_stem: str | None) -> dict:
        """`{customer_note, recent}` -- empty when the customer has no Customer note."""
        vault = getattr(self._api, "vault", None)
        if not vault or not customer_stem:
            return {"customer_note": None, "recent": []}
        entries = vault.entries()
        wanted = customer_stem.lower()
        hub = next((entry for entry in entries if entry["stem"].lower() == wanted), None)
        summary = None
        if hub:
            summary = vault.read_section(hub["path"], "Summary")
            if not summary:
                _, body = vault.read_note(hub["path"])
                summary = body
        linked = [entry for entry in entries
                  if entry is not hub
                  and str((entry.get("frontmatter") or {}).get("type") or "") not in SKIPPED_TYPES
                  and wanted in {str(target).lower() for target in entry.get("outgoing_wikilinks") or []}]
        linked.sort(key=lambda entry: _date(entry.get("frontmatter") or {}), reverse=True)
        recent = []
        for entry in linked[:RECENT_NOTES]:
            frontmatter = entry.get("frontmatter") or {}
            text = vault.read_section(entry["path"], "Summary") or ""
            if not text:
                # A thread captured before it was summarised has only its body; its start
                # still says what it was about (checked on ADNOC, 2026-10-23).
                _, body = vault.read_note(entry["path"])
                text = " ".join((body or "").split())
            recent.append({"note": entry["stem"], "type": frontmatter.get("type"), "date": _date(frontmatter),
                           "summary": text[:NOTE_EXCERPT]})
        return {"customer_note": (summary or "")[:CUSTOMER_EXCERPT] or None, "recent": recent}
