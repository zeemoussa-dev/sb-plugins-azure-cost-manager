"""Tracking billing accounts, refreshing them from Azure, and answering from the cache.

Phase 1 is display only (`PLAN.md`): nothing here writes to the vault.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

from . import consumption_analysis, months
from .billing_client import COST_TYPES, AzureApiError, BillingClient
from .consumption_store import ConsumptionStore

HISTORY_MONTHS = 12
# The current month moves daily; older than this and the screen offers a refresh.
STALE_AFTER = timedelta(hours=24)

ENTERPRISE_AGREEMENT = "EnterpriseAgreement"
CUSTOMER_AGREEMENT = "MicrosoftCustomerAgreement"


class AccountNotTracked(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConsumptionService:
    def __init__(self, store: ConsumptionStore, client_factory: Callable[[], BillingClient],
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = _now) -> None:
        self._store = store
        self._client_factory = client_factory
        self._client: BillingClient | None = None
        self._today = today
        self._now = now

    def _azure(self) -> BillingClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def visible_billing_accounts(self) -> list[dict]:
        tracked = {account["name"] for account in self._store.tracked_accounts()}
        return [{**account, "tracked": account["name"] in tracked}
                for account in self._azure().list_billing_accounts()]

    def tracked_accounts(self) -> list[dict]:
        listed = []
        for account in self._store.tracked_accounts():
            cached = self._store.cached(account["name"])
            listed.append({**account, "fetched_at": cached.get("fetched_at"),
                           "stale": self._is_stale(cached)})
        return listed

    def set_tracked(self, account_names: list[str]) -> list[dict]:
        """Replaces the tracked set with these accounts, as Azure names them now.
        A link to a Customer (Phase 2) survives on accounts that stay tracked."""
        visible = {account["name"]: account for account in self._azure().list_billing_accounts()}
        unknown = [name for name in account_names if name not in visible]
        if unknown:
            raise AccountNotTracked(f"not a billing account this sign-in can see: {', '.join(unknown)}")
        previous = {account["name"]: account for account in self._store.tracked_accounts()}
        accounts = [{"name": name,
                     "display_name": visible[name]["display_name"],
                     "agreement_type": visible[name]["agreement_type"],
                     "customer": (previous.get(name) or {}).get("customer")}
                    for name in dict.fromkeys(account_names)]
        self._store.save_tracked_accounts(accounts)
        self._store.forget_untracked({account["name"] for account in accounts})
        return self.tracked_accounts()

    def _require_tracked(self, account_name: str) -> dict:
        account = self._store.tracked_account(account_name)
        if account is None:
            raise AccountNotTracked(f"{account_name!r} is not a tracked billing account")
        return account

    def _is_stale(self, cached: dict) -> bool:
        fetched_at = cached.get("fetched_at")
        return not fetched_at or self._now() - datetime.fromisoformat(fetched_at) > STALE_AFTER

    def refresh(self, account_name: str) -> dict:
        account = self._require_tracked(account_name)
        cached = self._store.cached(account_name)
        current_month = months.month_of(self._today())
        wanted = months.span(months.shift(current_month, -(HISTORY_MONTHS - 1)), current_month)
        fetched_at = self._now().isoformat()
        errors: dict[str, str] = {}

        to_fetch = self._store.months_to_fetch(cached, wanted)
        if to_fetch:
            by_type = {cost_type: self._azure().query_monthly_cost(account_name, cost_type,
                                                                   to_fetch[0], to_fetch[-1])
                       for cost_type in COST_TYPES}
            for month in to_fetch:
                cached["months"][month] = {
                    "fetched_at": fetched_at,
                    "actual": [row for row in by_type["ActualCost"] if row["month"] == month],
                    "amortized": [row for row in by_type["AmortizedCost"] if row["month"] == month],
                }
        cached["months"] = {month: entry for month, entry in cached["months"].items() if month in wanted}

        # The commitment and the forecast are worth having, not worth failing for:
        # many accounts have no commitment, and forecast is refused on some scopes.
        try:
            cached["commitment"] = self._commitment(account)
        except AzureApiError as exc:
            cached["commitment"] = None
            errors["commitment"] = str(exc)
        try:
            cached["forecast"] = self._azure().forecast_monthly(
                account_name, current_month, f"{self._today().year:04d}-12")
        except AzureApiError as exc:
            cached["forecast"] = None
            errors["forecast"] = str(exc)

        cached["fetched_at"] = fetched_at
        cached["errors"] = errors
        self._store.save_cached(account_name, cached)
        return self.analysis(account_name)

    def _commitment(self, account: dict) -> dict | None:
        if account["agreement_type"] == ENTERPRISE_AGREEMENT:
            return {"kind": "ea-prepayment", "balance": self._azure().enterprise_agreement_balance(account["name"])}
        if account["agreement_type"] == CUSTOMER_AGREEMENT:
            lots = self._azure().consumption_commitment_lots(account["name"])
            return {"kind": "macc", "lots": lots} if lots else None
        return None

    def analysis(self, account_name: str) -> dict:
        account = self._require_tracked(account_name)
        cached = self._store.cached(account_name)
        return {
            "account": account,
            "fetched_at": cached.get("fetched_at"),
            "stale": self._is_stale(cached),
            "errors": cached.get("errors") or {},
            **consumption_analysis.analyse(cached, self._today()),
        }

    def consumption(self, account_name: str, first_month: str | None, last_month: str | None,
                    group_by: str, cost_type: str) -> dict:
        """Spend per month per `service` or `subscription`, straight from the cache."""
        self._require_tracked(account_name)
        if group_by not in ("service", "subscription"):
            raise ValueError("group must be 'service' or 'subscription'")
        if cost_type not in ("actual", "amortized"):
            raise ValueError("cost must be 'actual' or 'amortized'")
        cached_months = self._store.cached(account_name).get("months") or {}
        selected = [month for month in sorted(cached_months)
                    if (not first_month or month >= first_month) and (not last_month or month <= last_month)]
        rows = []
        for month in selected:
            totals: dict[str, float] = {}
            for row in cached_months[month].get(cost_type) or []:
                totals[row[group_by]] = totals.get(row[group_by], 0.0) + row["cost"]
            rows.extend({"month": month, group_by: name, "cost": round(cost, 2)}
                        for name, cost in sorted(totals.items(), key=lambda item: -item[1]))
        return {"account": account_name, "group": group_by, "cost": cost_type, "rows": rows}
