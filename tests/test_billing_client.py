"""The Azure calls, against a mock transport: shapes, paging, sign-in and throttling."""
from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from backend.azure_token import AzureCliToken, AzureSignInError
from backend.billing_client import AzureThrottled, BillingClient


class StubToken:
    def __init__(self) -> None:
        self.forgotten = 0

    def get(self) -> str:
        return "token"

    def forget(self) -> None:
        self.forgotten += 1


def client_answering(handler, token=None) -> BillingClient:
    return BillingClient(token or StubToken(), transport=httpx.MockTransport(handler), sleep=lambda _: None)


def query_page(rows, columns, next_link=None) -> dict:
    return {"properties": {"columns": [{"name": name} for name in columns], "rows": rows,
                           "nextLink": next_link}}


def test_query_rows_are_normalised_whichever_month_column_azure_uses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=query_page(
            [[1234.5, 20260901, "Storage", "Prod", "USD"]],
            ["Cost", "UsageDate", "ServiceName", "SubscriptionName", "Currency"]))

    rows = client_answering(handler).query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09")

    assert rows == [{"month": "2026-09", "service": "Storage", "subscription": "Prod",
                     "cost": 1234.5, "currency": "USD"}]


def test_query_follows_next_link_with_the_same_body():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        columns = ["totalCost", "BillingMonth", "ServiceName", "SubscriptionName", "Currency"]
        if "skiptoken" in str(request.url):
            return httpx.Response(200, json=query_page([[2, "2026-09-01T00:00:00", "B", "S", "USD"]], columns))
        return httpx.Response(200, json=query_page(
            [[1, "2026-09-01T00:00:00", "A", "S", "USD"]], columns,
            next_link="https://management.azure.com/x/query?api-version=2023-11-01&$skiptoken=abc"))

    rows = client_answering(handler).query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09")

    assert [row["service"] for row in rows] == ["A", "B"]
    assert bodies[0] == bodies[1]
    assert bodies[0]["timePeriod"] == {"from": "2026-09-01T00:00:00Z", "to": "2026-09-30T23:59:59Z"}


def test_a_401_forgets_the_token_and_tries_once_more():
    token, calls = StubToken(), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(401, json={"error": {"message": "expired"}})
        assert request.url.params["api-version"] == "2020-05-01"
        return httpx.Response(200, json={"value": [{"name": "123", "properties": {
            "displayName": "Contoso", "agreementType": "EnterpriseAgreement",
            "enrollmentDetails": {"startDate": "2022-04-14T00:00:00+00:00", "endDate": "2027-04-30T00:00:00+00:00"}}}]})

    accounts = client_answering(handler, token).list_billing_accounts()

    assert token.forgotten == 1
    assert accounts[0]["display_name"] == "Contoso"
    assert accounts[0]["agreement_type"] == "EnterpriseAgreement"
    assert (accounts[0]["term_start"], accounts[0]["term_end"]) == ("2022-04-14", "2027-04-30")


def test_a_throttle_of_under_a_minute_is_waited_out():
    waits, calls = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "42"})
        return httpx.Response(200, json=query_page([], ["Cost", "BillingMonth"]))

    client = BillingClient(StubToken(), transport=httpx.MockTransport(handler), sleep=waits.append)
    client.query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09")

    assert waits == [42]


def test_a_long_throttle_goes_back_to_the_operator():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "300"})

    with pytest.raises(AzureThrottled) as raised:
        client_answering(handler).query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09")

    assert raised.value.retry_after_seconds == 300


def test_a_missing_sign_in_tells_the_operator_to_run_az_login():
    def run_az(arguments):
        return subprocess.CompletedProcess(arguments, 1, "", "ERROR: Please run 'az login' to setup account.")

    with pytest.raises(AzureSignInError, match="az login"):
        AzureCliToken(run_az=run_az).get()


def test_the_cli_token_is_reused_until_close_to_expiry():
    calls = []

    def run_az(arguments):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(
            {"accessToken": "abc", "expires_on": 4102444800}), "")

    token = AzureCliToken(run_az=run_az)

    assert token.get() == token.get() == "abc"
    assert len(calls) == 1


def test_a_dropped_connection_is_tried_again():
    drops = [httpx.ConnectError("[WinError 10054] An existing connection was forcibly closed")] * 2

    def handler(request: httpx.Request) -> httpx.Response:
        if drops:
            raise drops.pop()
        return httpx.Response(200, json=query_page([], ["Cost", "UsageDate", "ServiceName", "SubscriptionName"]))

    assert client_answering(handler).query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09") == []


def test_a_network_that_stays_down_fails_the_request_not_the_sync():
    from backend.billing_client import AzureApiError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(AzureApiError, match="network failed 4 times"):
        client_answering(handler).query_monthly_cost("acct", "ActualCost", "2026-09", "2026-09")
