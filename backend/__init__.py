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

import threading
from datetime import datetime, timezone

from .azure_token import AzureCliToken
from .billing_client import BillingClient
from .commitment_notes import CommitmentNotes
from .consumption_provider import SERVICE as CONSUMPTION_SERVICE, ConsumptionProvider
from .consumption_service import ConsumptionService
from .consumption_store import BRIEFS_FILE, COMPASS_ANSWERS_FILE, DATA_FILES, PLACEMENTS_FILE, ConsumptionStore
from .advisor_service import Advisor
from .compass import Answers
from .customer_context import CustomerContext
from .account_owners import AccountOwners
from .industry import IndustryContext
from .consumption_sync import RESUME_AFTER_SECONDS, ConsumptionSync
from .customers import AccountDirectory, CustomerBook
from .pipeline import Pipeline
from .portfolio_service import SERVICE as PORTFOLIO_SERVICE, PortfolioService
from .routes import build_router
from .solution_notes import SolutionNotes
from .technology_notes import TechnologyNotes
from .sync_log import SYNC_LOG_FILE, SyncLog


def _now() -> datetime:
    return datetime.now(timezone.utc)


def register(api) -> None:
    for data_file in (*DATA_FILES, SYNC_LOG_FILE, BRIEFS_FILE, PLACEMENTS_FILE, COMPASS_ANSWERS_FILE):
        api.register_seed_data_file(data_file)
    token = AzureCliToken()
    log = SyncLog(lambda: api.data.read_text(SYNC_LOG_FILE), lambda text: api.data.write_text(SYNC_LOG_FILE, text))
    store = ConsumptionStore(api)
    directory = AccountDirectory(lambda: BillingClient(token).list_billing_accounts())
    book = CustomerBook(store, directory, CommitmentNotes(api))
    pipeline = Pipeline(api)
    # Compass, where the framework offers it to plugins (`api.llm`, optional under API 12, ADR-063).
    service = ConsumptionService(store, book, pipeline=pipeline, solution_notes=SolutionNotes(api),
                                 technology_notes=TechnologyNotes(api), llm=getattr(api, "llm", None),
                                 customer_context=CustomerContext(api), industry_context=IndustryContext(api),
                                 account_owners=AccountOwners(api))
    sync = ConsumptionSync(store, directory, lambda: BillingClient(token, observe=log), customers=book.records,
                           after_customers=service.refresh_prices, log=log)
    answers = Answers(store.compass_answers, store.save_compass_answers, _now)
    advisor = Advisor(service, answers, getattr(api, "llm", None))
    api.register_router(build_router(service, book, directory, sync, token, pipeline, log, advisor))
    resume = threading.Timer(RESUME_AFTER_SECONDS, sync.resume_interrupted)
    resume.daemon = True
    resume.start()
    api.provide_service(PORTFOLIO_SERVICE, PortfolioService(service, book))
    api.provide_service(CONSUMPTION_SERVICE, ConsumptionProvider(service, book))
