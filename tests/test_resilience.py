"""What keeps working when Azure or the CLI hiccups.

Worth pinning (operator, 2026-10-17: "the List of Billing Accounts Disappear I
can't link it to new Customer"): an hourly refresh that fails keeps the last
good list and tries again soon; only a first load with nothing to fall back on
reports the failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.customers import AccountDirectory

START = datetime(2026, 10, 17, 9, tzinfo=timezone.utc)
ACCOUNT = {"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement"}


def test_a_failed_refresh_keeps_the_last_good_list_and_retries_soon():
    clock = {"now": START}
    answers = [[dict(ACCOUNT)], RuntimeError("throttled"), [dict(ACCOUNT), {**ACCOUNT, "name": "2"}]]
    asked: list[int] = []

    def list_accounts():
        asked.append(1)
        answer = answers[len(asked) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    directory = AccountDirectory(list_accounts, now=lambda: clock["now"])
    assert [a["name"] for a in directory.accounts()] == ["1"]

    clock["now"] = START + timedelta(hours=1, minutes=1)
    assert [a["name"] for a in directory.accounts()] == ["1"]      # the refresh failed: last good list
    assert [a["name"] for a in directory.accounts()] == ["1"]      # and it is not asked again at once
    assert len(asked) == 2

    clock["now"] += timedelta(minutes=6)
    assert [a["name"] for a in directory.accounts()] == ["1", "2"]  # tried again five minutes on


def test_a_first_load_that_fails_says_so():
    def failing():
        raise RuntimeError("no sign-in")

    with pytest.raises(RuntimeError, match="no sign-in"):
        AccountDirectory(failing, now=lambda: START).accounts()


def test_the_customer_list_reads_sync_status_without_copying_months(fake_api):
    from backend.consumption_store import ConsumptionStore

    store = ConsumptionStore(fake_api)
    store.save_account("1", {"months": {"2026-09": {"actual": {"service": {"VM": 1.0}}}},
                             "synced_at": "2026-10-17T00:00:00+00:00", "errors": {"x": "boom"}})

    status = store.account_status("1")
    status["errors"]["y"] = "mine"

    assert status == {"synced_at": "2026-10-17T00:00:00+00:00", "errors": {"x": "boom", "y": "mine"}}
    assert store.account("1")["errors"] == {"x": "boom"}   # the caller's change does not reach the store
    assert store.account_status("missing") == {"synced_at": None, "errors": {}}


def test_a_sync_holds_cache_writes_and_writes_them_on_flush(fake_api):
    from backend.consumption_store import CACHE_WRITE_EVERY_SECONDS, CONSUMPTION_CACHE_FILE, ConsumptionStore

    writes: list[str] = []
    original = fake_api.data.write_text

    def counted(path, text):
        if path == CONSUMPTION_CACHE_FILE:
            writes.append(text)
        original(path, text)

    fake_api.data.write_text = counted
    clock = [0.0]
    store = ConsumptionStore(fake_api, clock=lambda: clock[0])
    store.save_account("1", {"months": {}})          # outside a sync: written at once
    assert len(writes) == 1

    with store.holding_writes():
        store.save_account("1", {"months": {}, "n": 1})
        store.save_account("1", {"months": {}, "n": 2})
        assert len(writes) == 1   # held: the last write was less than the interval ago
        clock[0] += CACHE_WRITE_EVERY_SECONDS
        store.save_account("1", {"months": {}, "n": 3})
        assert len(writes) == 2
        store.save_account("1", {"months": {}, "n": 4})
        store.flush()
        assert '"n":4' in writes[-1]   # compact JSON
    assert ConsumptionStore(fake_api).account("1")["n"] == 4
