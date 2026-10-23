"""A billed service's Technology note in the vault, for the seller to read when
drilling into it (operator, 2026-10-23: "the drill down links to services").

Cost Management names a service as it bills it ("Foundry Models", "Storage",
"Azure Data Factory v2"); the vault names a note after the product ("Azure OpenAI
Service", "Blob Storage"). A note is found by its title or file name, the same
with or without "Azure"/"Microsoft" in front, and then through the aliases below.
"""
from __future__ import annotations

import re
import threading
import time

NOTE_TYPES = {"AzureDoc", "Technology"}
CACHE_SECONDS = 300
# Billed service name -> the note's title, where the two differ by more than a prefix.
ALIASES = {
    "Foundry Models": "Azure OpenAI Service", "Azure OpenAI": "Azure OpenAI Service",
    "Foundry Tools": "Microsoft Foundry (formerly Azure AI Foundry)",
    "Cognitive Services": "Microsoft Foundry (formerly Azure AI Foundry)",
    "Azure Cognitive Search": "Azure AI Search",
    "Storage": "Blob Storage", "Azure Data Factory v2": "Azure Data Factory",
    "Virtual Machine Licenses": "Virtual Machines", "Virtual Machines Licenses": "Virtual Machines",
    "Specialized Compute": "Azure VMware Solution", "Backup": "Azure Backup",
    "Sentinel": "Microsoft Sentinel", "Functions": "Azure Functions", "Azure App Service": "App Service",
    "Azure Container Apps": "Container Apps", "Redis Cache": "Azure Cache for Redis",
    "SQL Database": "Azure SQL Database", "SQL Managed Instance": "Azure SQL Managed Instance",
    "Event Hubs": "Azure Event Hubs", "Service Bus": "Azure Service Bus", "Logic Apps": "Azure Logic Apps",
    "Event Grid": "Azure Event Grid", "IoT Hub": "Azure IoT Hub", "Stream Analytics": "Azure Stream Analytics",
    "HDInsight": "Azure HDInsight", "Azure Purview": "Microsoft Purview", "Energy Data Manager":
    "Azure Data Manager for Energy", "Windows Virtual Desktop": "Azure Virtual Desktop",
    "Azure DDOS Protection": "Azure DDoS Protection", "Azure Front Door Service": "Front Door",
    "Virtual WAN": "Azure Virtual WAN", "Azure Grafana Service": "Azure Managed Grafana",
    "SignalR": "Azure SignalR Service", "Microsoft Entra": "Microsoft Entra ID",
    "Azure Kubernetes Service": "Azure Kubernetes Service", "Container Registry": "Azure Container Registry",
}
_PREFIX = re.compile(r"^(azure|microsoft)\s+", re.IGNORECASE)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _PREFIX.sub("", name.strip()).lower()).strip()


class TechnologyNotes:
    def __init__(self, api, clock=time.monotonic) -> None:
        self._api = api
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: tuple[float, dict[str, str]] | None = None

    def _by_key(self) -> dict[str, str]:
        with self._lock:
            if self._kept and self._clock() - self._kept[0] < CACHE_SECONDS:
                return self._kept[1]
        vault = getattr(self._api, "vault", None)
        found: dict[str, str] = {}
        for entry in (vault.entries() if vault else []):
            frontmatter = entry.get("frontmatter") or {}
            if str(frontmatter.get("type") or "") not in NOTE_TYPES:
                continue
            for name in (frontmatter.get("title"), entry["stem"]):
                if name:
                    found.setdefault(_key(str(name)), entry["stem"])
        with self._lock:
            self._kept = (self._clock(), found)
        return found

    def notes(self) -> list[dict]:
        """Every Technology note: `{stem, title, category}`."""
        vault = getattr(self._api, "vault", None)
        found = []
        for entry in (vault.entries() if vault else []):
            frontmatter = entry.get("frontmatter") or {}
            if str(frontmatter.get("type") or "") in NOTE_TYPES:
                found.append({"stem": entry["stem"], "title": str(frontmatter.get("title") or entry["stem"]),
                              "category": frontmatter.get("category")})
        return sorted(found, key=lambda note: note["title"].lower())

    def note_for(self, service: str) -> str | None:
        """The stem of the note about a billed service, or None."""
        notes = self._by_key()
        return notes.get(_key(service)) or notes.get(_key(ALIASES.get(service, "")) or "\0")
