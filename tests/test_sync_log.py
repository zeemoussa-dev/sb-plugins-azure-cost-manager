"""The sync activity log.

Worth pinning: a run the backend stopped is closed as interrupted at its last
event; requests, pages, waits and errors are counted per run; a run keeps only
its newest events; and the sync and the Azure client both write to it.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.billing_client import AzureThrottled, BillingClient
from backend.consumption_store import ConsumptionStore
from backend.consumption_sync import ConsumptionSync
from backend.customers import AccountDirectory, CustomerBook
from backend.sync_log import EVENTS_PER_RUN, RUNS_KEPT, SyncLog, describe_request

START = datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)


class Disk:
    def __init__(self, text: str | None = None) -> None:
        self.text = text

    def read(self) -> str | None:
        return self.text

    def write(self, text: str) -> None:
        self.text = text


def ticking():
    moments = iter(START + timedelta(seconds=second) for second in range(100_000))
    return lambda: next(moments)


def test_a_run_still_running_at_load_was_interrupted_at_its_last_event():
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    log.begin("adnoc:this-month")
    log.step({"account": "5771504", "this_month": True})
    last = log.events()["events"][-1]["at"]

    reloaded = SyncLog(disk.read, disk.write)

    run = reloaded.runs()[0]
    assert (run["outcome"], run["finished_at"]) == ("interrupted", last)
    assert reloaded.events()["events"][-1]["kind"] == "interrupted"
    assert json.loads(disk.text)["runs"][0]["outcome"] == "interrupted"


def test_a_run_counts_its_requests_pages_waits_and_errors():
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    log.begin("all")
    log.request_started("POST query")
    assert log.in_flight()["what"] == "POST query"
    log.request_finished("POST query", 200, 1.5, page=False)
    log.request_finished("next page", 200, 0.5, page=True)
    log.wait(30, "inline retry")
    log.error("1", "balance 2026-09: Azure answered 500")
    log.end()

    run = log.runs()[0]
    assert (run["requests"], run["pages"], run["throttle_waits"], run["waited_seconds"], run["errors"]) == (2, 1, 1, 30, 1)
    assert run["outcome"] == "finished with errors" and log.in_flight() is None
    assert [event["kind"] for event in log.events()["events"]] == ["request", "request", "wait", "error"]


def test_a_run_keeps_its_newest_events_and_the_log_its_newest_runs():
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    for run in range(RUNS_KEPT + 2):
        log.begin(f"run {run}")
        log.end()
    for request in range(EVENTS_PER_RUN + 10):
        log.request_finished(f"request {request}", 200, 0.1, page=False)

    assert len(log.runs()) == RUNS_KEPT and log.runs()[0]["scope"] == f"run {RUNS_KEPT + 1}"
    log.begin("long")
    for request in range(EVENTS_PER_RUN + 10):
        log.request_finished(f"request {request}", 200, 0.1, page=False)
    found = log.events(last=EVENTS_PER_RUN)
    assert found["dropped_events"] == 10 and found["events"][0]["text"].startswith("request 10 ")


def test_a_log_that_cannot_be_read_or_written_never_stops_the_sync():
    def broken(*_):
        raise FileNotFoundError("no such file")

    log = SyncLog(broken, broken)
    log.begin("all")
    log.end()

    assert log.runs()[0]["outcome"] == "finished"


def test_requests_are_described_short_enough_to_read_in_a_list():
    body = {"type": "ActualCost", "timePeriod": {"from": "2026-09-01T00:00:00Z", "to": "2026-10-18T23:59:59Z"},
            "dataset": {"granularity": "Daily", "grouping": [{"name": "ResourceGroupName"}]}}

    assert describe_request("POST", "/providers/Microsoft.Billing/billingAccounts/1/providers/"
                                    "Microsoft.CostManagement/query", body) == \
        "POST CostManagement/query ActualCost Daily by ResourceGroupName 2026-09-01..2026-10-18"
    assert describe_request("POST", "https://management.azure.com/x/query?$skiptoken=abc", body) == "next page"


def test_the_azure_client_tells_the_log_every_request_and_page():
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    log.begin("all")
    columns = [{"name": name} for name in ("Cost", "UsageDate", "ServiceName", "SubscriptionName", "Currency")]

    def handler(request: httpx.Request) -> httpx.Response:
        if "skiptoken" in str(request.url):
            return httpx.Response(200, json={"properties": {"columns": columns, "rows": []}})
        return httpx.Response(200, json={"properties": {"columns": columns, "rows": [],
                                                        "nextLink": "https://management.azure.com/q?$skiptoken=1"}})

    class Token:
        def get(self) -> str:
            return "token"

    client = BillingClient(Token(), transport=httpx.MockTransport(handler), sleep=lambda _: None, observe=log)
    client.query_monthly_cost("1", "ActualCost", "2026-09", "2026-09")

    run = log.runs()[0]
    assert (run["requests"], run["pages"]) == (2, 1)
    assert [event["text"].split(" → ")[0] for event in log.events()["events"]] == \
        ["POST CostManagement/query ActualCost Monthly by ServiceName,SubscriptionName 2026-09-01..2026-09-30",
         "next page"]


def test_the_sync_logs_its_run_steps_and_throttle_waits(fake_api):
    throttled = [True]

    class Azure:
        def query_daily(self, account, first_day, last_day, dimensions):
            if throttled.pop() if throttled else False:
                raise AzureThrottled(5)
            return []

    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement",
                                           "term_start": "2026-01-01", "term_end": "2028-12-31"}])
    CustomerBook(store, directory).save(None, {"name": "Contoso", "accounts": ["1"]})
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    sync = ConsumptionSync(store, directory, lambda: Azure(), today=lambda: date(2026, 10, 18), now=ticking(),
                           sleep=lambda _: None, log=log)

    sync.start_this_month()
    for thread in threading.enumerate():
        if thread.name == "azure-cost-manager-this-month":
            thread.join(5)

    run = log.runs()[0]
    assert (run["scope"], run["outcome"], run["throttle_waits"]) == ("all:this-month", "finished", 1)
    assert [event["kind"] for event in log.events()["events"]] == ["step", "wait"]
    assert sync.status()["step_started_at"] is None and "waiting_seconds" not in (sync.status()["current"] or {})


def test_a_refresh_that_finds_no_enrollments_says_so(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [])
    sync = ConsumptionSync(store, directory, lambda: None, today=lambda: date(2026, 10, 18), now=ticking(),
                           sleep=lambda _: None)

    sync.run_this_month("adnoc")

    assert "no enrollments found for adnoc" in sync.status()["errors"][0]["message"]


def _sync_with_log(fake_api, disk: Disk):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [])
    return ConsumptionSync(store, directory, lambda: None, today=lambda: date(2026, 10, 18), now=ticking(),
                           sleep=lambda _: None, log=SyncLog(disk.read, disk.write, now=ticking()))


def test_a_sync_cut_off_by_a_restart_starts_again_with_the_same_scope(fake_api, monkeypatch):
    disk = Disk()
    log = SyncLog(disk.read, disk.write, now=ticking())
    log.begin("adnoc:this-month")
    log.request_finished("POST query", 200, 1.0, page=False)   # it got somewhere, then the backend restarted
    sync = _sync_with_log(fake_api, disk)
    started: list[str | None] = []
    monkeypatch.setattr(sync, "start_this_month", lambda customer=None: started.append(customer) or {"started": True})

    sync.resume_interrupted()

    assert started == ["adnoc"]


def test_nothing_starts_again_after_a_clean_finish_or_a_failure(fake_api):
    for outcome in ("finished", "stopped"):
        disk = Disk()
        log = SyncLog(disk.read, disk.write, now=ticking())
        log.begin("all")
        log.end(outcome)

        assert _sync_with_log(fake_api, disk).resume_interrupted() is None


def test_a_resume_that_never_gets_anywhere_is_not_retried_forever(fake_api):
    from backend.consumption_sync import RESUMES_IN_A_ROW

    disk = Disk()
    for _ in range(RESUMES_IN_A_ROW + 1):
        SyncLog(disk.read, disk.write, now=ticking()).begin("all")   # each load closes the last as interrupted

    assert _sync_with_log(fake_api, disk).resume_interrupted() is None


def test_scopes_map_back_to_their_start_calls(fake_api, monkeypatch):
    sync = _sync_with_log(fake_api, Disk())
    calls: list[tuple] = []
    monkeypatch.setattr(sync, "start", lambda customer=None, profiles="none": calls.append(("start", customer, profiles)))
    monkeypatch.setattr(sync, "start_tags", lambda customer=None: calls.append(("tags", customer)))
    monkeypatch.setattr(sync, "start_this_month", lambda customer=None: calls.append(("month", customer)))

    for scope in ("all", "adnoc", "all+profiles", "profiles", "all:tags", "adnoc:this-month"):
        sync._start_scope(scope)

    assert calls == [("start", None, "none"), ("start", "adnoc", "none"), ("start", None, "also"),
                     ("start", None, "only"), ("tags", None), ("month", "adnoc")]
