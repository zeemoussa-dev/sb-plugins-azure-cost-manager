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
from .sync_log import SyncLog, describe_request

API_ROOT = "https://management.azure.com"
# Pinned old on purpose: 2021-10-01 and later list no indirect EA enrollments for a
# partner's sign-in (checked live 2026-10-16: 135 accounts on 2020-05-01, 0 on
# 2024-04-01), and 2020-05-01 also returns each enrollment's term.
BILLING_API = "2020-05-01"
COST_MANAGEMENT_API = "2023-11-01"
CONSUMPTION_API = "2023-05-01"
TAGS_API = CONSUMPTION_API

# Cost Management throttles per sign-in and says how long to wait. A twelve-month
# query costs about twelve query units, so back-to-back queries are routinely told
# to wait 15-45 seconds (seen live 2026-10-16). Waits up to a minute are absorbed
# here; a longer one raises `AzureThrottled`, which the sync waits out itself.
_LONGEST_INLINE_WAIT_SECONDS = 60
_ATTEMPTS = 4
# A dropped connection or a timeout is tried again after each of these pauses; then
# the request fails as an `AzureApiError`, which the sync records for its window and
# moves past. A connection reset right after a throttle wait (WinError 10054) once
# stopped a whole Sync all at enrollment 26 of 38 (2026-10-18).
_NETWORK_RETRY_SECONDS = (2, 10, 30)

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
                 sleep: Callable[[float], None] = time.sleep, observe: SyncLog | None = None) -> None:
        self._token = token
        self._sleep = sleep
        self._observe = observe
        self._http = httpx.Client(base_url=API_ROOT, timeout=90, transport=transport)

    def _send(self, method: str, url: str, params: dict | None, body: dict | None) -> httpx.Response:
        """One HTTP exchange, told to the sync log when there is one -- a request that
        hangs is what a stuck sync looks like from outside."""
        if self._observe is None:
            return self._http.request(method, url, params=params, json=body,
                                      headers={"Authorization": f"Bearer {self._token.get()}"})
        what = describe_request(method, url, body)
        # A nextLink is absolute; a first request is a path under API_ROOT.
        page = url.startswith("http")
        self._observe.request_started(what)
        started = time.monotonic()
        try:
            response = self._http.request(method, url, params=params, json=body,
                                          headers={"Authorization": f"Bearer {self._token.get()}"})
        except Exception as exc:
            self._observe.request_finished(what, None, time.monotonic() - started, page,
                                           failure=f"failed: {type(exc).__name__} {exc}".strip())
            raise
        self._observe.request_finished(what, response.status_code, time.monotonic() - started, page)
        return response

    def _send_retrying(self, method: str, url: str, params: dict | None, body: dict | None) -> httpx.Response:
        for pause in (*_NETWORK_RETRY_SECONDS, None):
            try:
                return self._send(method, url, params, body)
            except httpx.TransportError as exc:
                failure = f"{type(exc).__name__} {exc}".strip()
                if pause is None:
                    raise AzureApiError(0, f"The network failed {len(_NETWORK_RETRY_SECONDS) + 1} times "
                                           f"in a row: {failure}") from exc
                if self._observe is not None:
                    self._observe.note(f"network: {failure}; trying again in {pause} s")
                self._sleep(pause)
        raise AssertionError("unreachable")

    def _request(self, method: str, url: str, *, params: dict | None = None,
                 body: dict | None = None) -> dict:
        for attempt in range(_ATTEMPTS):
            response = self._send_retrying(method, url, params, body)
            if response.status_code == 401 and attempt == 0:
                self._token.forget()
                continue
            if response.status_code == 429:
                wait = _retry_after(response)
                if wait > _LONGEST_INLINE_WAIT_SECONDS or attempt == _ATTEMPTS - 1:
                    raise AzureThrottled(wait)
                if self._observe is not None:
                    self._observe.wait(wait, "inline retry")
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

    def _grouped_monthly(self, account_name: str, cost_type: str, first_month: str, last_month: str,
                         dimensions: dict[str, str]) -> list[dict]:
        """One row per month x the two `dimensions` (row key -> Azure dimension).
        Cost Management accepts at most a year and two dimensions per query, so
        callers pass a window of twelve months or fewer."""
        body = {
            "type": cost_type,
            "timeframe": "Custom",
            "timePeriod": _time_period(first_month, last_month),
            "dataset": {
                "granularity": "Monthly",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": name} for name in dimensions.values()],
            },
        }
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/query"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        rows: list[dict] = []
        while True:
            properties = page.get("properties") or {}
            rows.extend(self._cost_rows(properties, dimensions))
            if not properties.get("nextLink"):
                return rows
            page = self._request("POST", properties["nextLink"], body=body)

    def query_monthly_cost(self, account_name: str, cost_type: str,
                           first_month: str, last_month: str) -> list[dict]:
        """`[{month, service, subscription, cost, currency}]`."""
        return self._grouped_monthly(account_name, cost_type, first_month, last_month,
                                     {"service": "ServiceName", "subscription": "SubscriptionName"})

    def query_monthly_meters(self, account_name: str, first_month: str, last_month: str,
                             cost_type: str = "ActualCost") -> list[dict]:
        """`[{month, meter_subcategory, pricing_model, cost, currency}]`: where GPU SKUs
        (`NDsr H100 v5 Series`) and Azure OpenAI reservations (PTU) can be told apart
        from everything else. Under `AmortizedCost` a reservation's usage carries its
        share of the purchase instead of costing nothing -- what coverage is read from."""
        return self._grouped_monthly(account_name, cost_type, first_month, last_month,
                                     {"meter_subcategory": "MeterSubCategory", "pricing_model": "PricingModel"})

    def query_by_subscription(self, account_name: str, first_month: str, last_month: str,
                              dimension: str) -> list[dict]:
        """`[{month, subscription, name, cost, currency}]`: actual cost by subscription
        and one other dimension (ServiceName, MeterSubCategory, ResourceGroupName) --
        what a subscription is used for."""
        return self._grouped_monthly(account_name, "ActualCost", first_month, last_month,
                                     {"subscription": "SubscriptionName", "name": dimension})

    def query_daily(self, account_name: str, first_day: str, last_day: str,
                    dimensions: dict[str, str]) -> list[dict]:
        """`[{day: "YYYY-MM-DD", cost, <key>: name ...}]`: actual cost per day by up to
        two `dimensions` (row key -> Azure dimension), for the This month report."""
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": f"{first_day}T00:00:00Z", "to": f"{last_day}T23:59:59Z"},
            "dataset": {"granularity": "Daily",
                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                        "grouping": [{"type": "Dimension", "name": name} for name in dimensions.values()]},
        }
        return self._daily_rows(account_name, body, dimensions)

    def query_daily_by_tag(self, account_name: str, first_day: str, last_day: str, tag_key: str) -> list[dict]:
        """`[{day, cost, value}]`: actual cost per day by one tag key's values; `value`
        is "Unassigned" for what does not carry the key."""
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": f"{first_day}T00:00:00Z", "to": f"{last_day}T23:59:59Z"},
            "dataset": {"granularity": "Daily",
                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                        "grouping": [{"type": "TagKey", "name": tag_key}]},
        }
        return self._daily_rows(account_name, body, {"value": "TagValue"})

    def _daily_rows(self, account_name: str, body: dict, dimensions: dict[str, str]) -> list[dict]:
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/query"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        rows: list[dict] = []
        while True:
            properties = page.get("properties") or {}
            columns = [column.get("name", "") for column in properties.get("columns") or []]
            cost_at = _column_index(columns, "totalCost", "Cost", "PreTaxCost")
            day_at = _column_index(columns, "UsageDate", "BillingMonth")
            at = {key: _column_index(columns, name) for key, name in dimensions.items()}
            if cost_at is not None and day_at is not None:
                for row in properties.get("rows") or []:
                    text = str(row[day_at])
                    day = f"{text[:4]}-{text[4:6]}-{text[6:8]}" if text.isdigit() else text[:10]
                    parsed = {"day": day, "cost": float(row[cost_at] or 0)}
                    for key, index in at.items():
                        parsed[key] = (row[index] if index is not None else None) or "Unassigned"
                    rows.append(parsed)
            if not properties.get("nextLink"):
                return rows
            page = self._request("POST", properties["nextLink"], body=body)

    def list_tag_keys(self, account_name: str) -> list[str]:
        """The tag keys used under an enrollment (Consumption API, so not Cost
        Management's throttling budget). 480 on one customer's enrollment."""
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.Consumption/tags"
        params: dict | None = {"api-version": TAGS_API}
        keys: list[str] = []
        while url:
            properties = self._request("GET", url, params=params).get("properties") or {}
            keys += [tag["key"] for tag in properties.get("tags") or [] if tag.get("key")]
            url, params = properties.get("nextLink"), None
        return sorted(set(keys))

    def query_monthly_by_tag(self, account_name: str, tag_key: str, first_month: str, last_month: str) -> list[dict]:
        """`[{month, value, cost}]`: an enrollment's actual cost by one tag key's
        values; `value` is "" for what does not carry the key."""
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": _time_period(first_month, last_month),
            "dataset": {"granularity": "Monthly",
                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                        "grouping": [{"type": "TagKey", "name": tag_key}]},
        }
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/query"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        rows: list[dict] = []
        while True:
            properties = page.get("properties") or {}
            columns = [column.get("name", "") for column in properties.get("columns") or []]
            cost_at = _column_index(columns, "totalCost", "Cost", "PreTaxCost")
            month_at = _column_index(columns, "BillingMonth", "UsageDate")
            value_at = _column_index(columns, "TagValue")
            if cost_at is not None and month_at is not None:
                rows += [{"month": _month_from_cell(row[month_at]), "cost": float(row[cost_at] or 0),
                          "value": (row[value_at] if value_at is not None else None) or ""}
                         for row in properties.get("rows") or []]
            if not properties.get("nextLink"):
                return rows
            page = self._request("POST", properties["nextLink"], body=body)

    @staticmethod
    def _cost_rows(properties: dict, dimensions: dict[str, str] | None = None) -> list[dict]:
        columns = [column.get("name", "") for column in properties.get("columns") or []]
        cost_at = _column_index(columns, "totalCost", "Cost", "PreTaxCost")
        month_at = _column_index(columns, "BillingMonth", "UsageDate")
        currency_at = _column_index(columns, "Currency", "BillingCurrency")
        if cost_at is None or month_at is None:
            return []
        dimension_at = {key: _column_index(columns, name) for key, name in (dimensions or {}).items()}
        rows = []
        for row in properties.get("rows") or []:
            parsed = {"month": _month_from_cell(row[month_at]), "cost": float(row[cost_at] or 0),
                      "currency": row[currency_at] if currency_at is not None else None}
            for key, index in dimension_at.items():
                parsed[key] = (row[index] if index is not None else None) or "Unassigned"
            rows.append(parsed)
        return rows

    def marketplace_charges(self, account_name: str, month: str) -> list[dict]:
        """An EA enrollment's Marketplace charges for one billing period, one row per
        charge: publisher, offer, plan, subscription, cost, quantity, and whether it
        recurs (SaaS) or is metered. Cost Management cannot name a Marketplace
        product at this scope (no publisher or offer dimension); this can. Its
        total matches the balance's Marketplace charges (checked 2026-10-17)."""
        period = month.replace("-", "")
        url = (f"{billing_account_scope(account_name)}/billingPeriods/{period}"
               "/providers/Microsoft.Consumption/marketplaces")
        rows = []
        for item in self._get_all(url, {"api-version": CONSUMPTION_API}):
            properties = item.get("properties") or {}
            rows.append({
                "publisher": (properties.get("publisherName") or "Unknown publisher").strip(),
                "offer": (properties.get("offerName") or "Unknown offer").strip(),
                "plan": (properties.get("planName") or "").strip(),
                "subscription": properties.get("subscriptionName") or properties.get("subscriptionGuid") or "",
                "cost": float(properties.get("pretaxCost") or 0),
                "quantity": float(properties.get("consumedQuantity") or 0),
                "unit": properties.get("unitOfMeasure") or "",
                "recurring": bool(properties.get("isRecurringCharge")),
            })
        return rows

    def billing_period_balance(self, account_name: str, month: str) -> dict:
        """An EA enrollment's balance for one billing period: what the month billed
        as usage, as Marketplace, and the credits applied against it. Matches the
        partner consumption export to the cent (checked 2026-10-16)."""
        period = month.replace("-", "")
        url = (f"{billing_account_scope(account_name)}/billingPeriods/{period}"
               "/providers/Microsoft.Consumption/balances")
        properties = self._request("GET", url, params={"api-version": CONSUMPTION_API}).get("properties") or {}
        return {
            "usage": float(properties.get("totalUsage") or 0),
            "marketplace": float(properties.get("azureMarketplaceServiceCharges") or 0),
            "credits": float(properties.get("adjustments") or 0),
            "credit_details": [{"name": detail.get("name"), "value": float(detail.get("value") or 0)}
                               for detail in properties.get("adjustmentDetails") or []],
            "billed_separately": float(properties.get("chargesBilledSeparately") or 0),
            "currency": properties.get("currency"),
        }

    def forecast_monthly(self, account_name: str, first_month: str, last_month: str,
                         azure_only: bool = False) -> list[dict]:
        """`[{month, cost}]` -- Azure's own forecast for months not yet billed. `azure_only`:
        Azure's own services, without Marketplace and SaaS -- the unfiltered forecast
        extrapolated FAB's one-off $10.3M Fortinet purchase into a $15.3M December."""
        dataset = {"granularity": "Monthly", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}
        if azure_only:
            dataset["filter"] = {"dimensions": {"name": "PublisherType", "operator": "In", "values": ["Azure"]}}
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": _time_period(first_month, last_month),
            "dataset": dataset,
            "includeActualCost": False,
            "includeFreshPartialCost": False,
        }
        url = f"{billing_account_scope(account_name)}/providers/Microsoft.CostManagement/forecast"
        page = self._request("POST", url, params={"api-version": COST_MANAGEMENT_API}, body=body)
        totals: dict[str, float] = {}
        for row in self._cost_rows(page.get("properties") or {}, {}):
            totals[row["month"]] = totals.get(row["month"], 0.0) + row["cost"]
        return [{"month": month, "cost": cost} for month, cost in sorted(totals.items())]
