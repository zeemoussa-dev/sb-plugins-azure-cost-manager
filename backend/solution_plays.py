"""Spend by solution play: each Azure service mapped to the play it belongs to
(operator, 2026-10-21: "GPU is AI & ML, Databricks and Fabric are Data, VNET is
Infra").

A default mapping ships here; the operator's own choices override it from
Settings and are kept in `SOLUTION_PLAYS_FILE`. A service no mapping names falls
into Unassigned, where Settings lists it to be mapped.

One service spans two plays: GPU virtual machines are billed as "Virtual
Machines" like any other VM, so the GPU share of a month -- read from the meter
detail, the way `categories` reads it -- moves from Infra to AI & ML.
"""
from __future__ import annotations

from . import categories

AI = "AI & ML"
DATA = "Data & Analytics"
INFRA = "Infra"
SECURITY = "Security"
APPS = "App Innovation"
MARKETPLACE = "Marketplace"
UNASSIGNED = "Unassigned"
PLAYS = [AI, DATA, INFRA, SECURITY, APPS, MARKETPLACE, UNASSIGNED]

# The service whose GPU meters are AI & ML rather than Infra.
GPU_HOST_SERVICE = "Virtual Machines"
# Software licenses for VMs: Microsoft's own (Windows Server, SQL Server, RHEL) and
# third-party Marketplace software billed the same way (FAB's Fortinet FortiFlex, $10.2M
# in six months, operator's check 2026-10-23).
LICENSE_SERVICES = ("Virtual Machine Licenses", "Virtual Machines Licenses")
# A meter subcategory shorter than this is too generic to match an offer's name.
SHORTEST_MATCH = 8

_DEFAULTS = {
    AI: ["Foundry Models", "Foundry Tools", "Cognitive Services", "Azure OpenAI", "Specialized Compute",
         "Azure Cognitive Search", "Microsoft Copilot Studio", "Azure Machine Learning", "Azure Bot Service",
         "MS Bing Services", "Azure AI Search", "Azure AI Services"],
    DATA: ["Microsoft Fabric", "Azure Databricks", "SQL Database", "SQL Managed Instance",
           "Azure Database for PostgreSQL", "Azure Database for MySQL", "Azure Cosmos DB", "Azure Synapse Analytics",
           "Azure Data Factory v2", "HDInsight", "Stream Analytics", "Azure Data Explorer", "Microsoft Purview",
           "Azure Purview", "Power BI", "Power BI Embedded", "Azure Managed Instance for Apache Cassandra",
           "Azure Arc Enabled Databases", "Energy Data Manager", "Redis Cache", "Insight and Analytics",
           "Microsoft Graph data connect", "Dataverse", "Data Box"],
    INFRA: ["Virtual Machines", "Virtual Machine Licenses", "Virtual Machines Licenses", "Storage", "Backup",
            "Azure Site Recovery", "Azure NetApp Files", "Virtual Network", "ExpressRoute", "VPN Gateway",
            "Load Balancer", "Bandwidth", "NAT Gateway", "Virtual WAN", "Azure DNS", "Azure Front Door Service",
            "Application Gateway", "Network Watcher", "Azure Bastion", "Azure Route Server", "Traffic Manager",
            "Content Delivery Network", "Azure Arc", "Windows Virtual Desktop", "Azure Monitor", "Log Analytics",
            "Automation", "Azure Update Manager", "Azure Grafana Service", "Cloud Services", "Routing",
            "Advanced Container Networking Services"],
    SECURITY: ["Sentinel", "Microsoft Defender for Cloud", "Azure DDOS Protection", "Azure Firewall",
               "Azure Firewall Manager", "Key Vault", "Microsoft Entra", "Microsoft Entra Domain Services",
               "Azure Active Directory B2C", "Azure Active Directory for External Identities",
               "Microsoft Security Copilot", "Microsoft Azure Payment HSM", "Trusted Signing"],
    APPS: ["Azure App Service", "Functions", "Azure Kubernetes Service", "Azure Container Apps",
           "Container Registry", "Container Instances", "API Management", "Azure API Center", "Logic Apps",
           "Service Bus", "Event Hubs", "Event Grid", "SignalR", "Web PubSub", "Notification Hubs",
           "App Configuration", "Azure DevOps", "GitHub", "Microsoft Dev Box", "Azure App Testing",
           "Microsoft Playwright Testing", "App Center", "Durable Task Scheduler", "Power Apps", "Power Automate",
           "Power Pages", "Syntex", "IoT Hub", "Azure Maps", "Media Services", "Email", "High Volume Email",
           "Voice", "Messaging", "Visual Studio Subscription", "Microsoft Graph Services"],
    MARKETPLACE: ["SaaS", "Azure Applications"],
    UNASSIGNED: ["Unassigned"],
}
DEFAULT_MAPPING: dict[str, str] = {service: play for play, services in _DEFAULTS.items() for service in services}


def mapping(overrides: dict[str, str] | None) -> dict[str, str]:
    """The defaults with the operator's own choices on top; a choice of a play that
    is no longer listed is ignored."""
    chosen = {service: play for service, play in (overrides or {}).items() if play in PLAYS}
    return {**DEFAULT_MAPPING, **chosen}


def play_of(service: str, plays: dict[str, str]) -> str:
    return plays.get(service, UNASSIGNED)


def gpu_cost(meters: dict[str, float]) -> float:
    """A month's GPU virtual machine spend, from its meter detail."""
    return sum(item["cost"] for item in categories.detail(meters or {}) if item["category"].startswith("GPU"))


def third_party_licenses(services: dict[str, float], meters: dict[str, float] | None,
                         offers: dict[str, float] | None, unseen_marketplace: float) -> float:
    """The part of a month's VM licenses that is Marketplace software: no more than the
    licenses, than the meters named like an invoiced Marketplace offer, or than the
    invoiced Marketplace Cost Management did not already show as SaaS."""
    licenses = sum(services.get(name, 0.0) for name in LICENSE_SERVICES)
    if licenses <= 0 or unseen_marketplace <= 0 or not offers:
        return 0.0
    names = [offer.lower() for offer in offers if offer]
    matched = 0.0
    for key, cost in (meters or {}).items():
        subcategory = key.split("|")[0].strip().lower()
        if len(subcategory) >= SHORTEST_MATCH and any(name.startswith(subcategory) for name in names):
            matched += cost
    return max(0.0, min(licenses, matched, unseen_marketplace))


def split(services: dict[str, float], meters: dict[str, float] | None, plays: dict[str, str],
          marketplace: float | None = None, offers: dict[str, float] | None = None) -> dict[str, float]:
    """One month's spend by service as spend by play. GPU virtual machines move from
    the VM service's play to AI & ML -- never more than that service cost.

    `marketplace`: the month's invoiced Marketplace, when there is one. On an EA
    enrollment Cost Management leaves Marketplace out (ADNOC, 2026-10: $28 against
    $373K invoiced), so the invoice's figure stands for the play instead.

    `offers`: the invoice's Marketplace offers by name. Third-party software billed as
    "Virtual Machine Licenses" is in the invoice too; it leaves the licenses' play so it
    is counted once, as Marketplace (FAB's Fortinet was counted twice)."""
    by_play: dict[str, float] = {}
    for service, cost in services.items():
        play = play_of(service, plays)
        by_play[play] = by_play.get(play, 0.0) + cost
    shown = by_play.get(MARKETPLACE, 0.0)
    moved = third_party_licenses(services, meters, offers, (marketplace or 0.0) - shown)
    if moved:
        license_play = play_of(LICENSE_SERVICES[0], plays)
        by_play[license_play] = by_play.get(license_play, 0.0) - moved
    if marketplace and marketplace > shown:
        by_play[MARKETPLACE] = marketplace
    elif moved:
        by_play[MARKETPLACE] = shown + moved
    host_play = play_of(GPU_HOST_SERVICE, plays)
    gpu = min(gpu_cost(meters or {}), max(services.get(GPU_HOST_SERVICE, 0.0), 0.0))
    if gpu and host_play != AI:
        by_play[host_play] = by_play.get(host_play, 0.0) - gpu
        by_play[AI] = by_play.get(AI, 0.0) + gpu
    return {play: round(cost, 2) for play, cost in by_play.items() if round(cost, 2) != 0}


def third_party_in_month(month: dict, plays: dict[str, str]) -> float:
    """A merged month's VM licenses that are Marketplace software, in actual cost."""
    services = (month.get("actual") or {}).get("service") or {}
    shown = sum(cost for service, cost in services.items() if play_of(service, plays) == MARKETPLACE)
    return third_party_licenses(services, month.get("meters"), month.get("marketplace_offers"),
                                ((month.get("measured") or {}).get("marketplace") or 0.0) - shown)


def split_month(month: dict, plays: dict[str, str], cost_kind: str = "amortized") -> dict[str, float]:
    """A merged month by play. Amortized by default (operator, 2026-10-23): a reservation or
    savings plan bought that month is otherwise a lump under "Unassigned" -- $1.41M in six
    months, gone when amortized -- instead of in the plays whose usage it pays for."""
    spend = (month.get(cost_kind) or {}).get("service") or {}
    if cost_kind == "amortized" and not spend:
        spend = (month.get("actual") or {}).get("service") or {}
    meters = (month.get("meters_amortized") if cost_kind == "amortized" else None) or month.get("meters")
    return split(spend, meters, plays, (month.get("measured") or {}).get("marketplace"), month.get("marketplace_offers"))


def settings_view(overrides: dict[str, str] | None, seen: dict[str, float]) -> dict:
    """What Settings shows: every service seen with its spend and play, whether the
    play is the default or the operator's, and the services nothing maps yet."""
    plays = mapping(overrides)
    rows = [{"service": service, "spend": round(cost, 2), "play": play_of(service, plays),
             "default": DEFAULT_MAPPING.get(service), "changed": service in (overrides or {})}
            for service, cost in sorted(seen.items(), key=lambda item: -item[1])]
    return {"plays": PLAYS, "services": rows,
            "unmapped": [row["service"] for row in rows if row["service"] not in plays],
            "gpu_rule": f"GPU virtual machines are billed as {GPU_HOST_SERVICE}; their share moves to {AI}."}
