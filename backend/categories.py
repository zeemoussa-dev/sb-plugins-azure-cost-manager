"""What a month's spend went on, at the level the operator plans by: GPU by SKU,
Azure OpenAI PTU against tokens, Marketplace, and the rest of Azure -- each GPU
and AI line split by how it was bought (pay-as-you-go, reservation, savings plan).

Read from Cost Management's meter detail (`MeterSubCategory` x `PricingModel`):
GPU virtual machines are named by series (`NDsr H100 v5 Series`), and an Azure
OpenAI reservation is provisioned throughput (checked 2026-10-16: a month's
`Azure OpenAI` x `Reservation` equalled its PTU reservations to the dollar).
"""
from __future__ import annotations

import re

# Longest first, so A100 is not read as A10 and MI300X not as MI300.
_GPU_SKU = re.compile(r"(GB300|GB200|B200|H200|H100|A100|A10|L40S|L40|MI300X|MI300|MI200|V100|T4|M60|K80)",
                      re.IGNORECASE)
_GPU_SERIES = re.compile(r"^N[A-Z]*", re.IGNORECASE)
OPENAI = "Azure OpenAI"

PRICING_LABELS = {"OnDemand": "Pay-as-you-go", "Reservation": "Reservation", "SavingsPlan": "Savings plan",
                  "Spot": "Spot"}

AZURE_OTHER = "Azure (other)"
MARKETPLACE = "Marketplace"
OPENAI_PTU = "Azure OpenAI PTU"
OPENAI_TOKENS = "Azure OpenAI pay-as-you-go"


def classify(meter_subcategory: str, pricing_model: str) -> str | None:
    """The plan line a meter belongs to, or None for ordinary Azure."""
    if meter_subcategory == OPENAI:
        return OPENAI_PTU if pricing_model == "Reservation" else OPENAI_TOKENS
    if _GPU_SERIES.match(meter_subcategory or ""):
        sku = _GPU_SKU.search(meter_subcategory)
        if sku:
            return f"GPU {sku.group(1).upper()}"
        if re.match(r"^N[CDV]", meter_subcategory, re.IGNORECASE):
            return "GPU (other N-series)"
    return None


def detail(meters: dict[str, float]) -> list[dict]:
    """GPU and AI lines of one month: `[{category, pricing, cost}]`."""
    lines: dict[tuple[str, str], float] = {}
    for key, cost in meters.items():
        meter_subcategory, _, pricing_model = key.partition("|")
        category = classify(meter_subcategory, pricing_model)
        if category:
            pricing = PRICING_LABELS.get(pricing_model, pricing_model or "Other")
            lines[(category, pricing)] = lines.get((category, pricing), 0.0) + cost
    return [{"category": category, "pricing": pricing, "cost": round(cost, 2)}
            for (category, pricing), cost in sorted(lines.items(), key=lambda item: -item[1])]


def mix(total: float, meters: dict[str, float], marketplace: float) -> dict[str, float]:
    """A month split into plan lines that add up to its measured `total`: the
    GPU and AI lines from the meters, Marketplace as measured, and everything else
    as Azure (other) -- which therefore also carries any credit subtracted."""
    lines: dict[str, float] = {}
    for item in detail(meters):
        lines[item["category"]] = lines.get(item["category"], 0.0) + item["cost"]
    if marketplace:
        lines[MARKETPLACE] = marketplace
    lines[AZURE_OTHER] = total - sum(lines.values())
    return {name: round(cost, 2) for name, cost in lines.items() if round(cost, 2) != 0}
