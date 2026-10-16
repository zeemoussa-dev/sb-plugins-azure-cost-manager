"""Azure Cost Manager -- a Second Brain plugin (`ADR-022`).

Customers' Azure agreements and their consumption, synced from Azure Cost
Management with the operator's own `az login` into local data, and analysed
per customer -- a customer being a group of enrollments, with the value it
signed for: month-over-month trend, top services, anomalies, burn-down against
the signed value, and forecast.

Everything it needs from the framework arrives through the Plugin API handed to
`register`; this package imports nothing from the framework itself.
"""
from __future__ import annotations

from .azure_token import AzureCliToken
from .billing_client import BillingClient
from .consumption_service import ConsumptionService
from .consumption_store import DATA_FILES, ConsumptionStore
from .consumption_sync import ConsumptionSync
from .customers import AccountDirectory, CustomerBook
from .routes import build_router


def register(api) -> None:
    for data_file in DATA_FILES:
        api.register_seed_data_file(data_file)
    token = AzureCliToken()
    store = ConsumptionStore(api)
    directory = AccountDirectory(lambda: BillingClient(token).list_billing_accounts())
    book = CustomerBook(store, directory)
    sync = ConsumptionSync(store, directory, lambda: BillingClient(token))
    api.register_router(build_router(ConsumptionService(store, book), book, directory, sync, token))
