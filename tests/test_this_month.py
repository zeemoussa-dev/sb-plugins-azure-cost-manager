"""This month so far.

Worth pinning: it compares the same number of days (Azure lags a day or two);
a workload is new only if it cost nothing last month and, for a service or
subscription, in the three closed months before; the projection scales the
month to date; and the sync asks for last month and this one by day.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from backend import this_month
from backend.consumption_store import ConsumptionStore
from backend.consumption_sync import ConsumptionSync, _aggregate_daily
from backend.customers import AccountDirectory, CustomerBook

TODAY = date(2026, 10, 18)


def daily(days: dict[str, dict[str, float]], groups: dict[str, dict[str, float]] | None = None) -> dict:
    return {"fetched_at": "2026-10-18T08:00:00+00:00", "first_day": "2026-09-01", "last_day": "2026-10-18",
            "service": days, "subscription": {day: {"Prod": sum(names.values())} for day, names in days.items()},
            "resource_group": groups or {}}


def test_pace_compares_the_same_days_and_projects_the_month():
    days = {**{f"2026-09-{d:02d}": {"VM": 100.0} for d in range(1, 31)},
            **{f"2026-10-{d:02d}": {"VM": 150.0} for d in range(1, 17)}}   # data to the 16th: Azure lags
    found = this_month.analyse({"1": {"daily": daily(days)}}, {}, TODAY)

    assert (found["through"], found["days_elapsed"]) == ("2026-10-16", 16)
    assert (found["month_to_date"], found["last_month_same_days"], found["pace_pct"]) == (2400, 1600, 50.0)
    assert found["projected_month_end"] == 150 * 31
    assert found["daily"][15] == {"day": 16, "this_month": 150, "last_month": 100,
                                  "this_month_to_date": 2400, "last_month_to_date": 1600}
    assert found["daily"][20]["this_month"] is None and found["daily"][30]["last_month"] is None


def test_a_workload_is_new_only_if_it_was_not_there_before():
    days = {"2026-09-05": {"VM": 100.0}, "2026-10-02": {"VM": 100.0, "Azure OpenAI": 900.0, "Storage": 50.0}}
    groups = {"2026-09-05": {"rg-core": 100.0}, "2026-10-02": {"rg-core": 100.0, "rg-genai-prod": 950.0}}
    merged = {"2026-07": {"actual": {"service": {"Storage": 20.0}, "subscription": {"Prod": 20.0}}}}

    found = this_month.analyse({"1": {"daily": daily(days, groups)}}, merged, TODAY)

    assert [(w["kind"], w["name"]) for w in found["new_workloads"]] == [
        ("resource_group", "rg-genai-prod"), ("service", "Azure OpenAI")]
    # Storage cost nothing last month but ran in July: a return, not a new workload.
    assert [row["name"] for row in found["dimensions"]["service"]["new"]] == ["Azure OpenAI"]


def test_tag_values_are_folded_untagged_left_out_and_new_values_flagged():
    days = {"2026-09-05": {"VM": 100.0}, "2026-10-02": {"VM": 300.0}}
    data = daily(days)
    data["tag:Project"] = {"2026-09-05": {"Atlas": 100.0, "Unassigned": 5.0},
                           "2026-10-02": {"atlas": 100.0, "Orion": 200.0, "Unassigned": 9.0}}
    data["tag:Environment"] = {"2026-09-05": {"prod": 100.0}, "2026-10-02": {"PRD": 300.0}}

    found = this_month.analyse({"1": {"daily": data}}, {}, TODAY)

    project = {row["name"]: row for row in found["dimensions"]["tag:Project"]["rows"]}
    assert set(project) == {"Atlas", "Orion"} and project["Orion"]["new"] and not project["Atlas"]["new"]
    assert found["dimensions"]["tag:Environment"]["rows"][0]["name"] == "Production"
    assert ("tag:Project", "Orion") in {(w["kind"], w["name"]) for w in found["new_workloads"]}
    assert "tag:Owner" not in found["dimensions"]   # no Owner tag fetched: no Owner grouping


def test_enrollments_the_refresh_never_reached_are_named():
    days = {"2026-10-02": {"VM": 100.0}}
    found = this_month.analyse({"1": {"daily": daily(days)}, "2": {"months": {}}}, {}, TODAY)

    assert found["missing_enrollments"] == ["2"] and found["month_to_date"] == 100


def test_without_a_refresh_it_says_so():
    assert this_month.analyse({"1": {"months": {}}}, {}, TODAY) == {"has_data": False}


def test_the_refresh_asks_for_last_month_and_this_one_by_day(fake_api):
    asked: list[tuple] = []

    class Azure:
        def query_daily(self, account, first_day, last_day, dimensions):
            asked.append((account, first_day, last_day, tuple(dimensions)))
            key = next(iter(dimensions))
            return [{"day": "2026-10-02", "cost": 5.0, **{k: f"{k}-a" for k in dimensions}},
                    {"day": "2026-10-02", "cost": 7.0, **{k: f"{k}-a" for k in dimensions}}] if key else []

    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement",
                                           "term_start": "2026-01-01", "term_end": "2028-12-31"}])
    CustomerBook(store, directory).save(None, {"name": "Contoso", "accounts": ["1"]})
    sync = ConsumptionSync(store, directory, lambda: Azure(), today=lambda: TODAY,
                           now=lambda: datetime(2026, 10, 18, tzinfo=timezone.utc), sleep=lambda _: None)

    sync.run_this_month()

    assert asked == [("1", "2026-09-01", "2026-10-18", ("service", "subscription")),
                     ("1", "2026-09-01", "2026-10-18", ("resource_group",))]
    saved = store.account("1")["daily"]
    assert saved["service"] == {"2026-10-02": {"service-a": 12.0}}
    assert saved["resource_group"] == {"2026-10-02": {"resource_group-a": 12.0}}


def test_daily_rows_are_added_up_per_day_and_name():
    rows = [{"day": "2026-10-01", "cost": 1.005, "service": "VM"}, {"day": "2026-10-01", "cost": 2.0, "service": "VM"}]

    assert _aggregate_daily(rows, ("service",)) == {"service": {"2026-10-01": {"VM": 3.0}}}


def _refresh_setup(fake_api, kept: dict | None, today: date = TODAY):
    asked: list[tuple] = []

    class Azure:
        def query_daily(self, account, first_day, last_day, dimensions):
            asked.append((first_day, tuple(dimensions)))
            return [{"day": last_day, "cost": 4.0, **{k: f"{k}-new" for k in dimensions}}]

    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement",
                                           "term_start": "2026-01-01", "term_end": "2028-12-31"}])
    CustomerBook(store, directory).save(None, {"name": "Contoso", "accounts": ["1"]})
    if kept:
        store.save_account("1", {"daily": kept})
    sync = ConsumptionSync(store, directory, lambda: Azure(), today=lambda: today,
                           now=lambda: datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc),
                           sleep=lambda _: None)
    return sync, store, asked


def test_a_refresh_asks_again_only_from_five_days_before_its_marker(fake_api):
    kept = {**daily({"2026-09-05": {"VM": 100.0}, "2026-10-02": {"VM": 1.0}, "2026-10-09": {"VM": 2.0}},
                    {"2026-09-05": {"rg-core": 100.0}}), "last_day": "2026-10-10"}
    sync, store, asked = _refresh_setup(fake_api, kept)

    sync.run_this_month()

    assert asked == [("2026-10-05", ("service", "subscription")), ("2026-10-05", ("resource_group",))]
    saved = store.account("1")["daily"]
    # Days before the refetch are kept; from it on, Azure's latest answer replaces them.
    assert saved["service"] == {"2026-09-05": {"VM": 100.0}, "2026-10-02": {"VM": 1.0},
                                "2026-10-18": {"service-new": 4.0}}
    assert (saved["first_day"], saved["last_day"]) == ("2026-09-01", "2026-10-18")


def test_into_a_new_month_the_window_moves_and_the_end_of_the_last_one_is_asked_again(fake_api):
    kept = {**daily({"2026-09-05": {"VM": 100.0}, "2026-10-20": {"VM": 7.0}}), "last_day": "2026-10-31"}
    sync, store, asked = _refresh_setup(fake_api, kept, today=date(2026, 11, 3))

    sync.run_this_month()

    assert {first for first, _ in asked} == {"2026-10-26"}
    saved = store.account("1")["daily"]
    assert saved["first_day"] == "2026-10-01" and "2026-09-05" not in saved["service"]
    assert saved["service"]["2026-10-20"] == {"VM": 7.0}
