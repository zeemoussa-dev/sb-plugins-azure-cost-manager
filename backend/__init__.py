"""Azure Cost Manager -- a Second Brain plugin (`ADR-022`).

Customers' Azure agreements (EA, MCA/MACC) and their monthly consumption, read
from Azure Cost Management with the operator's own `az login`, and analysed:
month-over-month trend, top services, anomalies, commitment burn-down and
forecast.

Phase 1 is display only (`PLAN.md`). Everything it needs from the framework
arrives through the Plugin API handed to `register`; this package imports
nothing from the framework itself.
"""
from __future__ import annotations

from .azure_token import AzureCliToken
from .billing_client import BillingClient
from .consumption_service import ConsumptionService
from .consumption_store import DATA_FILES, ConsumptionStore
from .routes import build_router


def register(api) -> None:
    for data_file in DATA_FILES:
        api.register_seed_data_file(data_file)
    token = AzureCliToken()
    service = ConsumptionService(ConsumptionStore(api), lambda: BillingClient(token))
    api.register_router(build_router(service, token))
