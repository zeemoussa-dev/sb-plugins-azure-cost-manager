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
