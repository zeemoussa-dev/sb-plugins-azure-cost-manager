"""The Azure Billing, Cost Management and Consumption calls -- raw I/O only.

Responses are normalised into plain rows here and nothing else: what a number
means (a trend, a burn-down) is `consumption_analysis`'s business.
"""
from __future__ import annotations

import time
from typing import Callable

import httpx

from . import months
from .azure_token import AzureCliToken

API_ROOT = "https://management.azure.com"
# Pinned old on purpose: 2021-10-01 and later list no indirect EA enrollments for a
# partner's sign-in (checked live 2026-10-16: 135 accounts on 2020-05-01, 0 on
# 2024-04-01), and 2020-05-01 also returns each enrollment's term.
BILLING_API = "2020-05-01"
COST_MANAGEMENT_API = "2023-11-01"
CONSUMPTION_API = "2023-05-01"

# Cost Management throttles per scope and says how long to wait. A twelve-month
# query costs about twelve of the scope's query units, and a refresh makes two, so
# on a large EA enrollment the second is routinely told to wait 15-45 seconds
# (seen live 2026-10-16). A refresh is something the operator clicked and is
# watching, so waits up to a minute are absorbed; longer goes back to them.
_LONGEST_INLINE_WAIT_SECONDS = 60
_ATTEMPTS = 4

COST_TYPES = ("ActualCost", "AmortizedCost")


class AzureApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class AzureThrottled(AzureApiError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(429, f"Azure Cost Management is throttling this scope; "
                              f"try again in {retry_after_seconds} seconds.")
        self.retry_after_seconds = retry_after_seconds


def billing_account_scope(account_name: str) -> str:
    return f"/providers/Microsoft.Billing/billingAccounts/{account_name}"


def _retry_after(response: httpx.Response) -> int:
    for header, value in response.headers.items():
        if header.lower().endswith("retry-after"):
            try:
                return max(1, int(float(value)))
            except ValueError:
                continue
    return 30


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        return f"Azure answered {response.status_code}: {error.get('message') or error.get('code')}"
    except ValueError:
        return f"Azure answered {response.status_code}."


def _time_period(first_month: str, last_month: str) -> dict:
    return {"from": f"{months.first_day(first_month).isoformat()}T00:00:00Z",
            "to": f"{months.last_day(last_month).isoformat()}T23:59:59Z"}


def _month_from_cell(value) -> str:
    """A Monthly query labels its rows `BillingMonth` ("2026-09-01T00:00:00") on
    some agreements and `UsageDate` (20260901) on others."""
    text = str(value)
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}"
    return text[:7]


def _column_index(columns: list[str], *candidates: str) -> int | None:
    lowered = [name.lower() for name in columns]
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered.index(candidate.lower())
    return None


def _day(value: str | None) -> str | None:
    return str(value)[:10] if value else None


class BillingClient:
    def __init__(self, token: AzureCliToken, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._token = token
        self._sleep = sleep
        self._http = httpx.Client(base_url=API_ROOT, timeout=90, transport=transport)

    def _request(self, method: str, url: str, *, params: dict | None = None,
                 body: dict | None = None) -> dict:
        for attempt in range(_ATTEMPTS):
            response = self._http.request(method, url, params=params, json=body,
                                          headers={"Authorization": f"Bearer {self._token.get()}"})
            if response.status_code == 401 and attempt == 0:
                self._token.forget()
                continue
            if response.status_code == 429:
                wait = _retry_after(response)
                if wait > _LONGEST_INLINE_WAIT_SECONDS or attempt == _ATTEMPTS - 1:
                    raise AzureThrottled(wait)
                self._sleep(wait)
                continue
            if response.status_code >= 400:
                raise AzureApiError(response.status_code, _error_message(response))
            return response.json() if response.content else {}
        raise AzureApiError(401, "Azure refused the sign-in twice -- run `az login` again.")

    def _get_all(self, url: str, params: dict) -> list[dict]:
        page = self._request("GET", url, params=params)
        items = list(page.get("value") or [])
        while page.get("nextLink"):
            page = self._request("GET", page["nextLink"])
            items.extend(page.get("value") or [])
        return items

    def list_billing_accounts(self) -> list[dict]:
        accounts = self._get_all("/providers/Microsoft.Billing/billingAccounts",
                                 {"api-version": BILLING_API})
        listed = []
        for account in accounts:
            if not account.get("name"):
                continue
            properties = account.get("properties") or {}
            enrollment = properties.get("enrollmentDetails") or {}
            listed.append({
                "name": account["name"],
                "display_name": properties.get("displayName") or account["name"],
                "agreement_type": properties.get("agreementType") or "Unknown",
                "account_type": properties.get("accountType"),
                "term_start": _day(enrollment.get("startDate")),
                "term_end": _day(enrollment.get("endDate")),
            })
        return listed

    def query_monthly_cost(self, account_name: str, cost_type: str,
                           first_month: str, last_month: str) -> list[dict]:
        """`[{month, service, subscription, cost, currency}]`, one per month x
        service x subscription. Cost Management accepts at most a year per query,
        so callers pass a window of twelve months or fewer."""
        body = {
            "type": cost_type,
            "timeframe": "Custom",
            "timePeriod": _time_period(first_month, last_month),
            "dataset": {
                "granularity": "Monthly",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"},
                             {"type": "Dimension", "name": "SubscriptionName"}],
            },
        }
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/query"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        rows: list[dict] = []
        while True:
            properties = page.get("properties") or {}
            rows.extend(self._cost_rows(properties))
            if not properties.get("nextLink"):
                return rows
            page = self._request("POST", properties["nextLink"], body=body)

    @staticmethod
    def _cost_rows(properties: dict) -> list[dict]:
        columns = [column.get("name", "") for column in properties.get("columns") or []]
        cost_at = _column_index(columns, "totalCost", "Cost", "PreTaxCost")
        month_at = _column_index(columns, "BillingMonth", "UsageDate")
        service_at = _column_index(columns, "ServiceName")
        subscription_at = _column_index(columns, "SubscriptionName")
        currency_at = _column_index(columns, "Currency", "BillingCurrency")
        if cost_at is None or month_at is None:
            return []
        return [{
            "month": _month_from_cell(row[month_at]),
            "service": (row[service_at] if service_at is not None else None) or "Unassigned",
            "subscription": (row[subscription_at] if subscription_at is not None else None) or "Unassigned",
            "cost": float(row[cost_at] or 0),
            "currency": row[currency_at] if currency_at is not None else None,
        } for row in properties.get("rows") or []]

    def forecast_monthly(self, account_name: str, first_month: str, last_month: str) -> list[dict]:
        """`[{month, cost}]` -- Azure's own forecast for months not yet billed."""
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": _time_period(first_month, last_month),
            "dataset": {"granularity": "Monthly",
                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}},
            "includeActualCost": False,
            "includeFreshPartialCost": False,
        }
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/forecast"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        totals: dict[str, float] = {}
        for row in self._cost_rows(page.get("properties") or {}):
            totals[row["month"]] = totals.get(row["month"], 0.0) + row["cost"]
        return [{"month": month, "cost": cost} for month, cost in sorted(totals.items())]

    def enterprise_agreement_balance(self, account_name: str) -> dict:
        """The current billing period's Azure Prepayment (monetary commitment)."""
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.Consumption/balances"
        properties = self._request("GET", url, params={"api-version": CONSUMPTION_API}).get("properties") or {}
        return {
            "beginning_balance": float(properties.get("beginningBalance") or 0),
            "new_purchases": float(properties.get("newPurchases") or 0),
            "utilized": float(properties.get("utilized") or 0),
            "ending_balance": float(properties.get("endingBalance") or 0),
            "service_overage": float(properties.get("serviceOverage") or 0),
            "currency": properties.get("currency"),
        }

    def consumption_commitment_lots(self, account_name: str) -> list[dict]:
        """The MACC lots on a Microsoft Customer Agreement."""
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.Consumption/lots"
        lots = self._get_all(url, {"api-version": CONSUMPTION_API,
                                   "$filter": "source eq 'ConsumptionCommitment'"})
        normalised = []
        for lot in lots:
            properties = lot.get("properties") or {}
            original = properties.get("originalAmount") or {}
            remaining = properties.get("closedBalance") or {}
            normalised.append({
                "original": float(original.get("value") or 0),
                "remaining": float(remaining.get("value") or 0),
                "currency": original.get("currency"),
                "start": _day(properties.get("startDate")),
                "end": _day(properties.get("expirationDate")),
                "status": properties.get("status"),
            })
        return normalised
