"""What each subscription looks like it is used for, for Solution Sellers
(operator, 2026-10-23: "Azure services don't map into solutions ... if the
customer has this service, this means they might be building a data warehouse").

A subscription's footprint -- its last closed months' cost by service, by meter
subcategory and by resource group -- is read against a catalog of patterns. A
pattern names what it requires (every group must match), what supports it, and
pitches: the piece the customer runs nowhere, said as what to sell.

A signal is `service:<exact ServiceName>`, `meter:<words in a meter subcategory>`
or `name:<word>` in the subscription's or a resource group's name. Rules first;
Compass is to place what they cannot (operator's choice, 2026-10-23).
"""
from __future__ import annotations

import re

from . import solution_plays

AI, DATA, INFRA, SECURITY, APPS = (solution_plays.AI, solution_plays.DATA, solution_plays.INFRA,
                                   solution_plays.SECURITY, solution_plays.APPS)
# Below this a month a service is residue -- a test, a leftover disk -- not a sign of a solution.
MIN_MONTHLY = 25.0
SIGNAL_KINDS = ("service", "meter", "name")
STRONG = "strong"
LIKELY = "likely"

GENAI_MODELS = ["service:Foundry Models", "meter:Azure OpenAI", "meter:Compass by Core42"]
WAREHOUSES = ["service:Microsoft Fabric", "service:Azure Databricks", "service:Azure Synapse Analytics",
              "meter:Fabric Capacity", "meter:Dedicated SQL Pool", "service:HDInsight"]
SEARCH = ["service:Azure Cognitive Search", "service:Azure AI Search"]
PAAS_COMPUTE = ["service:Azure Kubernetes Service", "service:Azure Container Apps", "service:Azure App Service",
                "service:Functions"]

DEFAULT_PATTERNS: list[dict] = [
    {"id": "lakehouse", "name": "Data lakehouse / warehouse", "play": DATA,
     "description": "A warehouse or lakehouse engine, usually fed by pipelines over a data lake.",
     "requires": [WAREHOUSES],
     "supports": ["service:Azure Data Factory v2", "meter:Hierarchical Namespace", "meter:Data Lake",
                  "service:Microsoft Purview", "service:Azure Purview", "service:Power BI Embedded",
                  "meter:Informatica"],
     "names": ["dwh", "warehouse", "lake", "lakehouse", "datalake", "analytics", "edw", "bi", "databricks",
               "fabric", "synapse", "data"],
     "pitches": [
         {"missing": ["service:Microsoft Purview", "service:Azure Purview"],
          "pitch": "Data governance: Microsoft Purview to catalogue and govern the data estate"},
         {"missing": GENAI_MODELS + SEARCH,
          "pitch": "AI on their data: Azure OpenAI or Compass with AI Search over the lakehouse"},
         {"missing": ["service:Power BI Embedded", "service:Microsoft Fabric"],
          "pitch": "A BI layer: Power BI on Fabric over the warehouse"}]},
    {"id": "data-integration", "name": "Data integration (pipelines)", "play": DATA,
     "description": "Data pipelines with nowhere in Azure to land the data for analytics.",
     "requires": [["service:Azure Data Factory v2", "meter:Informatica"]], "unless": ["lakehouse"],
     "supports": ["meter:Hierarchical Namespace"], "names": ["etl", "ingest", "integration", "pipeline", "adf"],
     "pitches": [{"missing": WAREHOUSES, "pitch": "Where the data lands: a lakehouse on Fabric or Databricks"}]},
    {"id": "streaming", "name": "Real-time data and streaming", "play": DATA,
     "description": "Events ingested and analysed as they arrive.",
     "requires": [["service:Event Hubs", "meter:Aiven"],
                  ["service:Stream Analytics", "service:Azure Data Explorer", "service:Azure Databricks",
                   "service:Microsoft Fabric"]],
     "supports": [], "names": ["stream", "streaming", "realtime", "telemetry", "events", "kafka"],
     "pitches": [{"missing": ["service:Azure Data Explorer", "service:Microsoft Fabric"],
                  "pitch": "Real-time analytics: Fabric Real-Time Intelligence (Eventhouse)"}]},
    {"id": "operational-db", "name": "Operational databases", "play": DATA,
     "description": "Application databases: SQL, PostgreSQL, MySQL, Cosmos DB and partner databases.",
     "requires": [["service:SQL Database", "service:SQL Managed Instance", "service:Azure Database for PostgreSQL",
                   "service:Azure Database for MySQL", "service:Azure Cosmos DB",
                   "service:Azure Managed Instance for Apache Cassandra", "meter:Oracle", "meter:MongoDB"]],
     "supports": ["service:Redis Cache"], "names": ["db", "sql", "database", "postgres", "mysql", "cosmos"],
     "pitches": [{"missing": WAREHOUSES,
                  "pitch": "Analytics on operational data: Fabric mirroring of these databases"}]},
    {"id": "energy-data", "name": "Energy data platform (OSDU)", "play": DATA,
     "description": "Azure Data Manager for Energy.", "requires": [["service:Energy Data Manager"]],
     "supports": [], "names": ["osdu", "energy", "subsurface"], "pitches": []},
    {"id": "genai", "name": "Generative AI application", "play": AI,
     "description": "Calls to large language models, often with retrieval and an app in front.",
     "requires": [GENAI_MODELS],
     "supports": SEARCH + ["service:API Management", "service:Azure App Service", "service:Azure Container Apps",
                           "service:Azure Cosmos DB", "service:Foundry Tools"],
     "names": ["ai", "gpt", "openai", "llm", "genai", "rag", "chat", "bot", "copilot", "agent", "agents",
               "assistant", "foundry"],
     "pitches": [
         {"missing": SEARCH, "pitch": "Grounding: Azure AI Search for retrieval (RAG) over their own content"},
         {"missing": ["service:API Management"],
          "pitch": "An AI gateway: API Management in front of the models (quotas, logging, failover)"},
         {"missing": ["meter:Compass by Core42"],
          "pitch": "Sovereign models: Compass by Core42 for in-country inference"}]},
    {"id": "copilot-agents", "name": "Copilot Studio agents", "play": AI,
     "description": "Low-code agents built in Copilot Studio.",
     "requires": [["service:Microsoft Copilot Studio", "meter:Copilot Credit"]], "supports": [], "names": [],
     "pitches": [{"missing": GENAI_MODELS, "pitch": "Custom agents and models on Azure AI Foundry"}]},
    {"id": "ml-platform", "name": "Machine learning platform", "play": AI,
     "description": "Model training and MLOps.",
     "requires": [["service:Azure Machine Learning", "meter:Dataiku"]], "supports": [],
     "names": ["ml", "mlops", "datascience", "model", "models"],
     "pitches": [{"missing": GENAI_MODELS, "pitch": "Generative AI next to their ML: Azure AI Foundry models"}]},
    {"id": "gpu", "name": "GPU training / inference", "play": AI,
     "description": "GPU virtual machines.",
     "requires": [["meter:H100", "meter:H200", "meter:A100", "meter:A10_", "meter:NDsr", "meter:NCads",
                   "meter:NVads", "meter:NDasr", "meter:NCas", "meter:MI300", "meter:NC Series", "meter:ND Series",
                   "meter:NV Series"]],
     "supports": ["service:Azure Machine Learning"], "names": ["gpu", "training", "inference", "hpc"],
     "pitches": [
         {"missing": ["service:Azure Machine Learning", "service:Foundry Models"],
          "pitch": "Run the GPUs as a platform: Azure Machine Learning or AI Foundry"},
         {"missing": ["meter:Compass by Core42"],
          "pitch": "Managed inference: Compass by Core42 instead of self-hosted GPUs"}]},
    {"id": "ai-services", "name": "AI services (documents, speech, vision)", "play": AI,
     "description": "Prebuilt AI: Document Intelligence, Speech, Translator, Vision, Language.",
     "requires": [["meter:Document Intelligence", "meter:Speech", "meter:Translator", "meter:Computer Vision",
                   "meter:Language", "service:Foundry Tools", "service:Cognitive Services"]],
     "supports": [], "names": ["ocr", "document", "speech", "vision"],
     "pitches": [{"missing": GENAI_MODELS, "pitch": "Generative AI over the same documents: Azure OpenAI or Compass"}]},
    {"id": "cloud-native", "name": "Cloud-native / containers", "play": APPS,
     "description": "Applications on Kubernetes or Container Apps.",
     "requires": [["service:Azure Kubernetes Service", "service:Azure Container Apps", "meter:OpenShift"]],
     "supports": ["service:Container Registry", "service:Key Vault", "service:API Management"],
     "names": ["aks", "k8s", "kube", "kubernetes", "container", "containers", "microservices"],
     "pitches": [
         {"missing": ["meter:Defender for Containers"],
          "pitch": "Container security: Microsoft Defender for Containers"},
         {"missing": ["service:API Management"], "pitch": "API Management in front of the services"}]},
    {"id": "web-apps", "name": "Web and API applications (PaaS)", "play": APPS,
     "description": "App Service and Functions, usually with a database behind.",
     "requires": [["service:Azure App Service", "service:Functions"]], "unless": ["genai"],
     "supports": ["service:SQL Database", "service:Azure Cosmos DB", "service:Redis Cache",
                  "service:Azure Front Door Service", "service:API Management"],
     "names": ["web", "portal", "website", "api", "frontend", "backend"],
     "pitches": [
         {"missing": ["service:Azure Front Door Service", "service:Application Gateway"],
          "pitch": "A secure global entry: Front Door with WAF"},
         {"missing": GENAI_MODELS, "pitch": "AI in the app: Azure OpenAI or Compass behind the web front"}]},
    {"id": "integration", "name": "Integration and messaging", "play": APPS,
     "description": "APIs, workflows and messaging between systems.",
     "requires": [["service:Logic Apps", "service:Service Bus", "service:API Management", "service:Event Grid"]],
     "supports": ["service:Functions"], "names": ["integration", "esb", "apim", "api", "messaging"],
     "pitches": []},
    {"id": "devops", "name": "DevOps and engineering", "play": APPS,
     "description": "GitHub, Azure DevOps and developer environments.",
     "requires": [["service:GitHub", "service:Azure DevOps", "service:Microsoft Dev Box"]], "supports": [],
     "names": ["devops", "cicd", "build", "github"], "pitches": []},
    {"id": "iot", "name": "IoT solution", "play": APPS,
     "description": "Connected devices sending telemetry.",
     "requires": [["service:IoT Hub"]], "supports": ["service:Event Hubs", "service:Stream Analytics",
                                                      "service:Azure Maps"],
     "names": ["iot", "device", "devices", "sensor", "sensors"],
     "pitches": [{"missing": ["service:Azure Data Explorer", "service:Microsoft Fabric"],
                  "pitch": "Analytics on device telemetry: Fabric Real-Time Intelligence"}]},
    {"id": "sap", "name": "SAP on Azure", "play": INFRA,
     "description": "SAP workloads: M-series VMs, NetApp Files, or SAP in the names.",
     "requires": [["name:sap", "name:hana", "name:s4", "name:s4hana", "meter:M-Series", "meter:Mv2", "meter:Msv2",
                   "meter:Mdsv2", "meter:Mbsv3", "meter:Mdsv3", "meter:SAP"],
                  ["service:Virtual Machines", "service:Azure NetApp Files"]],
     "supports": ["service:Azure NetApp Files", "service:Azure Site Recovery"], "names": [],
     "pitches": [{"missing": WAREHOUSES, "pitch": "SAP data into analytics: Fabric or Databricks over SAP"}]},
    {"id": "avs", "name": "VMware (Azure VMware Solution)", "play": INFRA,
     "description": "VMware workloads moved as they are.", "requires": [["meter:Azure VMware Solution"]],
     "supports": [], "names": ["avs", "vmware"],
     "pitches": [{"missing": PAAS_COMPUTE, "pitch": "Modernisation: move AVS workloads to native Azure services"}]},
    {"id": "avd", "name": "Virtual desktop (AVD)", "play": INFRA,
     "description": "Azure Virtual Desktop: session hosts on VMs.",
     "requires": [["service:Windows Virtual Desktop", "name:avd", "name:wvd", "name:vdi"]], "supports": [],
     "names": ["desktop", "hostpool"], "pitches": []},
    {"id": "network-hub", "name": "Network hub / landing zone", "play": INFRA,
     "description": "Shared connectivity: firewalls, gateways, ExpressRoute.",
     "requires": [["service:Azure Firewall", "service:VPN Gateway", "service:ExpressRoute", "service:Virtual WAN",
                   "meter:Fortinet", "meter:Palo Alto", "meter:Check Point", "meter:Infoblox"]],
     "supports": ["service:Azure DDOS Protection", "service:Azure Bastion", "service:Azure DNS"],
     "names": ["hub", "connectivity", "network", "networking", "lz", "landingzone", "landing", "shared"],
     "pitches": [{"missing": ["service:Azure DDOS Protection"], "pitch": "DDoS Protection on the hub"}]},
    {"id": "backup-dr", "name": "Backup and disaster recovery", "play": INFRA,
     "description": "Backup vaults, replication and partner backup.",
     "requires": [["service:Backup", "service:Azure Site Recovery", "meter:Rubrik", "meter:Commvault",
                   "meter:Veeam", "meter:Cloud Backup"]],
     "supports": [], "names": ["backup", "dr", "recovery", "bcdr"],
     "pitches": [{"missing": ["service:Azure Site Recovery"],
                  "pitch": "Disaster recovery: Azure Site Recovery to a second region"}]},
    {"id": "soc", "name": "Security operations (SIEM / SOC)", "play": SECURITY,
     "description": "Microsoft Sentinel over Log Analytics.",
     "requires": [["service:Sentinel", "meter:Sentinel"]],
     "supports": ["service:Log Analytics", "service:Microsoft Defender for Cloud", "meter:Darktrace"],
     "names": ["soc", "siem", "sentinel", "security", "sec"],
     "pitches": [
         {"missing": ["service:Microsoft Security Copilot"], "pitch": "Security Copilot for the SOC analysts"},
         {"missing": ["service:Microsoft Defender for Cloud"],
          "pitch": "Defender for Cloud: posture and workload protection"}]},
    {"id": "posture", "name": "Cloud security posture (Defender)", "play": SECURITY,
     "description": "Microsoft Defender for Cloud plans.",
     "requires": [["service:Microsoft Defender for Cloud"]], "supports": [], "names": [],
     "pitches": [{"missing": ["service:Sentinel", "meter:Sentinel"],
                  "pitch": "A SIEM: Microsoft Sentinel over the Defender signals"}]},
    {"id": "iaas", "name": "Virtual machines (IaaS)", "play": INFRA,
     "description": "Mostly plain virtual machines; shown only when nothing more specific fits.",
     "requires": [["service:Virtual Machines"]], "fallback": True, "supports": ["service:Backup"], "names": [],
     "pitches": [
         {"missing": PAAS_COMPUTE, "pitch": "Modernisation: move these VMs to PaaS or containers"},
         {"missing": ["service:Backup", "meter:Rubrik", "meter:Commvault", "meter:Veeam"],
          "pitch": "Backup for these virtual machines"},
         {"missing": ["service:Microsoft Defender for Cloud"], "pitch": "Defender for Servers"}]},
]

ENVIRONMENTS = [("Production", {"prod", "production", "prd", "live"}),
                ("Test", {"test", "tst", "qa", "uat", "staging", "stg", "preprod", "nonprod"}),
                ("Development", {"dev", "development"}),
                ("Sandbox", {"sandbox", "sbx", "poc", "lab", "demo", "pilot"})]


class PatternError(ValueError):
    pass


def _tokens(*names: str) -> set[str]:
    """The words in names: `rg-DataLake-prod01` -> datalake, data, lake, prod01, prod."""
    found: set[str] = set()
    for name in names:
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "")
        for word in re.split(r"[^A-Za-z0-9]+", name or "") + re.split(r"[^A-Za-z0-9]+", spaced):
            word = word.lower()
            if word:
                found.add(word)
                found.add(word.rstrip("0123456789"))
    return found - {""}


def _signal(signal: str) -> tuple[str, str]:
    kind, _, value = signal.partition(":")
    if kind not in SIGNAL_KINDS or not value.strip():
        raise PatternError(f"{signal!r}: a signal is service:<name>, meter:<words> or name:<word>")
    return kind, value.strip()


def validated(patterns) -> list[dict]:
    """The operator's catalog, checked: every pattern has an id, a name, a play and
    at least one required group; every signal is well formed."""
    if not isinstance(patterns, list) or not patterns:
        raise PatternError("the catalog is a non-empty list of patterns")
    seen: set[str] = set()
    checked = []
    for position, pattern in enumerate(patterns, start=1):
        if not isinstance(pattern, dict):
            raise PatternError(f"pattern {position} is not an object")
        pattern_id = str(pattern.get("id") or "").strip()
        if not pattern_id or pattern_id in seen:
            raise PatternError(f"pattern {position} needs an id of its own")
        seen.add(pattern_id)
        if not str(pattern.get("name") or "").strip():
            raise PatternError(f"{pattern_id}: a name is needed")
        if pattern.get("play") not in solution_plays.PLAYS:
            raise PatternError(f"{pattern_id}: play is one of {', '.join(solution_plays.PLAYS)}")
        requires = pattern.get("requires")
        if not isinstance(requires, list) or not requires or not all(isinstance(group, list) and group
                                                                     for group in requires):
            raise PatternError(f"{pattern_id}: requires is a list of non-empty lists of signals")
        for signal in [s for group in requires for s in group] + list(pattern.get("supports") or []) + [
                s for pitch in pattern.get("pitches") or [] for s in pitch.get("missing") or []]:
            _signal(str(signal))
        for pitch in pattern.get("pitches") or []:
            if not str(pitch.get("pitch") or "").strip() or not pitch.get("missing"):
                raise PatternError(f"{pattern_id}: each pitch has a pitch text and the signals it is missing")
        checked.append({"id": pattern_id, "name": str(pattern["name"]).strip(), "play": pattern["play"],
                        "description": str(pattern.get("description") or ""),
                        "requires": requires, "supports": list(pattern.get("supports") or []),
                        "names": [str(word).lower() for word in pattern.get("names") or []],
                        "unless": list(pattern.get("unless") or []), "fallback": bool(pattern.get("fallback")),
                        "pitches": list(pattern.get("pitches") or [])})
    return checked


def patterns(overrides: list[dict] | None) -> list[dict]:
    return validated(overrides) if overrides else validated(DEFAULT_PATTERNS)


class _Estate:
    """One subscription's (or a whole customer's) signals, monthly."""

    def __init__(self, services: dict[str, float], meters: dict[str, float], names: list[str], months: int) -> None:
        self.services = {name: cost / months for name, cost in services.items() if cost / months >= MIN_MONTHLY}
        self.meters = {name: cost / months for name, cost in meters.items() if cost / months >= MIN_MONTHLY}
        self.words = _tokens(*names)

    def matches(self, signal: str) -> list[tuple[str, float | None]]:
        kind, value = _signal(signal)
        if kind == "service":
            return [(value, self.services[value])] if value in self.services else []
        if kind == "meter":
            wanted = value.lower()
            return [(name, cost) for name, cost in self.meters.items() if wanted in name.lower()]
        word = value.lower()
        return [(f"named '{word}'", None)] if word in self.words else []

    def has_any(self, signals: list[str]) -> bool:
        return any(self.matches(signal) for signal in signals)


def _evidence(found: list[tuple[str, float | None]]) -> list[dict]:
    unique: dict[str, float | None] = {}
    for name, cost in found:
        unique[name] = cost
    return [{"name": name, "monthly": round(cost, 2) if cost is not None else None}
            for name, cost in sorted(unique.items(), key=lambda item: -(item[1] or 0))]


def classify(estate: _Estate, catalog: list[dict]) -> list[dict]:
    """The patterns a subscription fits, the strongest evidence first."""
    fitted: dict[str, dict] = {}
    for pattern in catalog:
        if pattern["fallback"]:
            continue
        groups = [[hit for signal in group for hit in estate.matches(signal)] for group in pattern["requires"]]
        if not all(groups):
            continue
        supports = [hit for signal in pattern["supports"] for hit in estate.matches(signal)]
        named = sorted(word for word in pattern["names"] if word in estate.words)
        fitted[pattern["id"]] = {
            "id": pattern["id"], "name": pattern["name"], "play": pattern["play"],
            "confidence": STRONG if (len(supports) >= 2 or named or len(groups) > 1) else LIKELY,
            "evidence": _evidence([hit for group in groups for hit in group] + supports),
            "named": named}
    for pattern_id in list(fitted):
        pattern = next(p for p in catalog if p["id"] == pattern_id)
        if any(other in fitted for other in pattern["unless"]):
            del fitted[pattern_id]
    if not fitted:
        for pattern in catalog:
            if not pattern["fallback"]:
                continue
            groups = [[hit for signal in group for hit in estate.matches(signal)] for group in pattern["requires"]]
            if all(groups):
                fitted[pattern["id"]] = {"id": pattern["id"], "name": pattern["name"], "play": pattern["play"],
                                         "confidence": LIKELY, "named": [],
                                         "evidence": _evidence([hit for group in groups for hit in group])}
    return sorted(fitted.values(), key=lambda found: (found["confidence"] != STRONG,
                                                      -sum(item["monthly"] or 0 for item in found["evidence"])))


def environment(*names: str) -> str | None:
    words = _tokens(*names)
    for label, markers in ENVIRONMENTS:
        if words & markers:
            return label
    return None


def _footprints(entries: dict[str, dict]) -> tuple[dict[str, dict], dict | None]:
    """Every enrollment's subscriptions, and the window they were read over."""
    subscriptions: dict[str, dict] = {}
    window = None
    for entry in entries.values():
        footprint = entry.get("footprint") or {}
        if not footprint.get("subscriptions"):
            continue
        if window is None or footprint.get("last_month", "") > window["last_month"]:
            window = {"first_month": footprint.get("first_month"), "last_month": footprint.get("last_month"),
                      "months": footprint.get("months") or 1, "fetched_at": footprint.get("fetched_at")}
        for name, found in footprint["subscriptions"].items():
            key = name if name not in subscriptions else f"{name} ({len(subscriptions)})"
            subscriptions[key] = {**found, "months": footprint.get("months") or 1}
    return subscriptions, window


def customer_view(entries: dict[str, dict], catalog: list[dict]) -> dict:
    """Each subscription's solutions, the customer's solutions and the pitches."""
    subscriptions, window = _footprints(entries)
    by_id = {pattern["id"]: pattern for pattern in catalog}
    everything = _Estate(
        {name: cost for found in subscriptions.values() for name, cost in (found.get("services") or {}).items()},
        {name: cost for found in subscriptions.values() for name, cost in (found.get("meters") or {}).items()},
        [], max(1, (window or {}).get("months") or 1))
    rows = []
    for name, found in subscriptions.items():
        months = found.get("months") or 1
        groups = list((found.get("resource_groups") or {}))
        estate = _Estate(found.get("services") or {}, found.get("meters") or {}, [name] + groups, months)
        monthly = sum((found.get("services") or {}).values()) / months
        if monthly < MIN_MONTHLY:
            continue
        top = sorted((found.get("services") or {}).items(), key=lambda item: -item[1])[:5]
        rows.append({"subscription": name, "monthly": round(monthly, 2),
                     "environment": environment(name, *groups),
                     "solutions": classify(estate, catalog),
                     "top_services": [{"name": service, "monthly": round(cost / months, 2)} for service, cost in top],
                     "resource_groups": [group for group, _ in sorted((found.get("resource_groups") or {}).items(),
                                                                      key=lambda item: -item[1])[:5]]})
    rows.sort(key=lambda row: -row["monthly"])
    summary: dict[str, dict] = {}
    for row in rows:
        for solution in row["solutions"]:
            item = summary.setdefault(solution["id"], {"id": solution["id"], "name": solution["name"],
                                                       "play": solution["play"], "subscriptions": 0, "monthly": 0.0})
            item["subscriptions"] += 1
            item["monthly"] = round(item["monthly"] + row["monthly"], 2)
    pitches = []
    for solution_id, item in summary.items():
        for pitch in by_id[solution_id]["pitches"]:
            if not everything.has_any(pitch["missing"]):
                pitches.append({"solution": item["name"], "play": item["play"], "pitch": pitch["pitch"],
                                "subscriptions": [row["subscription"] for row in rows
                                                  if any(s["id"] == solution_id for s in row["solutions"])]})
    unclassified = [row for row in rows if not row["solutions"]]
    return {"window": window, "synced": window is not None, "subscriptions": rows,
            "solutions": sorted(summary.values(), key=lambda item: -item["monthly"]), "pitches": pitches,
            "unclassified": {"count": len(unclassified), "monthly": round(sum(r["monthly"] for r in unclassified), 2)}}


def across(views: list[tuple[dict, dict]]) -> dict:
    """`views`: (customer, its customer_view). Who runs which solution, every pitch,
    and the largest subscriptions nothing placed."""
    by_solution: dict[str, dict] = {}
    rows, pitches, unplaced, placed = [], [], [], []
    window = None
    for customer, view in views:
        if not view["synced"]:
            continue
        if window is None or (view["window"] or {}).get("last_month", "") > window.get("last_month", ""):
            window = view["window"]
        for item in view["solutions"]:
            found = by_solution.setdefault(item["id"], {"id": item["id"], "name": item["name"], "play": item["play"],
                                                        "customers": [], "subscriptions": 0, "monthly": 0.0})
            found["customers"].append(customer["name"])
            found["subscriptions"] += item["subscriptions"]
            found["monthly"] = round(found["monthly"] + item["monthly"], 2)
        pitches.extend({"customer": customer["name"], "customer_id": customer["id"], **pitch}
                       for pitch in view["pitches"])
        unplaced.extend({"customer": customer["name"], "customer_id": customer["id"], **row}
                        for row in view["subscriptions"] if not row["solutions"])
        placed.extend({"customer": customer["name"], "customer_id": customer["id"], **row}
                      for row in view["subscriptions"])
        rows.append({"id": customer["id"], "name": customer["name"],
                     "monthly": round(sum(row["monthly"] for row in view["subscriptions"]), 2),
                     "subscriptions": len(view["subscriptions"]),
                     "solutions": [item["name"] for item in view["solutions"]],
                     "pitches": len(view["pitches"]), "unclassified": view["unclassified"]})
    return {"window": window,
            "by_solution": sorted(by_solution.values(), key=lambda item: -item["monthly"]),
            "customers": sorted(rows, key=lambda row: -row["monthly"]), "pitches": pitches,
            "subscriptions": sorted(placed, key=lambda row: -row["monthly"]),
            "unclassified": sorted(unplaced, key=lambda row: -row["monthly"])[:200]}
