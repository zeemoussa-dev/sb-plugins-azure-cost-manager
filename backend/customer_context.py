"""What the vault says about a customer, for its brief: the Customer note's summary
and the latest notes that link to it (meetings, threads, captures).

Read through the Plugin API's index -- a note links to the customer by its
Customer note's stem -- never by walking folders.
"""
from __future__ import annotations

import re

NOTE_EXCERPT = 600
MESSAGE_EXCERPT = 450
MESSAGES_PER_THREAD = 2
CUSTOMER_EXCERPT = 1500
RECENT_NOTES = 6
MESSAGE_TYPE = "RawMessage"
# Conversations only: reference notes, entity hubs and single messages (read through
# their thread) are left out.
SKIPPED_TYPES = {"Solution", "Playbook", "AzureDoc", "Technology", "Insight", "Template", "Partner", "Person",
                 "Opportunity", "Customer", MESSAGE_TYPE}
# Outlook's banner on external mail says nothing about the conversation.
_BANNER = re.compile(r"^\s*\[CAUTION-EXTERNAL\][^\n]*\n?", re.IGNORECASE)


def _date(frontmatter: dict) -> str:
    for key in ("date", "start", "received", "sent", "created", "last_refreshed"):
        value = frontmatter.get(key)
        if value:
            return str(value)[:10]
    return ""


def _plain(text: str) -> str:
    return " ".join(_BANNER.sub("", text or "").split())


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

        def links(entry: dict) -> set[str]:
            return {str(target).lower() for target in entry.get("outgoing_wikilinks") or []}

        messages_by_thread: dict[str, list[dict]] = {}
        for entry in entries:
            if str((entry.get("frontmatter") or {}).get("type") or "") == MESSAGE_TYPE:
                for target in links(entry):
                    messages_by_thread.setdefault(target, []).append(entry)
        linked = [entry for entry in entries
                  if entry is not hub
                  and str((entry.get("frontmatter") or {}).get("type") or "") not in SKIPPED_TYPES
                  and wanted in links(entry)]
        linked.sort(key=lambda entry: _date(entry.get("frontmatter") or {}), reverse=True)
        recent = []
        for entry in linked[:RECENT_NOTES]:
            frontmatter = entry.get("frontmatter") or {}
            text = vault.read_section(entry["path"], "Summary") or ""
            if not text:
                # A thread captured before it was summarised holds its words in its message
                # notes, not in itself (checked on ADNOC's brief, 2026-10-23): the latest ones say
                # what it is about.
                messages = sorted(messages_by_thread.get(entry["stem"].lower(), []),
                                  key=lambda message: str((message.get("frontmatter") or {}).get("received") or ""),
                                  reverse=True)[:MESSAGES_PER_THREAD]
                parts = []
                for message in messages:
                    sent = message.get("frontmatter") or {}
                    _, body = vault.read_note(message["path"])
                    parts.append(f"{sent.get('sender') or 'Someone'} ({_date(sent)}): {_plain(body)[:MESSAGE_EXCERPT]}")
                text = " | ".join(parts)
            if not text:
                _, body = vault.read_note(entry["path"])
                text = _plain(body)
            recent.append({"note": entry["stem"], "type": frontmatter.get("type"), "date": _date(frontmatter),
                           "summary": text[:NOTE_EXCERPT * MESSAGES_PER_THREAD]})
        return {"customer_note": (summary or "")[:CUSTOMER_EXCERPT] or None, "recent": recent}
