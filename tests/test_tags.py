"""Cost by tag.

Worth pinning: a dimension is found under its many spellings (and not under
look-alikes); values are folded; untagged is what no spelling tagged; and the
sync queries only spellings an enrollment has, for recent months, once.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from backend import tags
from backend.consumption_store import ConsumptionStore
from backend.consumption_sync import ConsumptionSync
from backend.customers import AccountDirectory, CustomerBook

TODAY = date(2026, 10, 17)


def test_a_dimension_is_found_under_its_spellings_and_typos():
    keys = ["environment", "Environemnt", "x_Environment", " envirornment", "env", "projectname", "Project Name",
            "pojectname", "projectstartdate", "createdon", "created", "veeam01", "costcenter", "cost_centre",
            "Business Unit", "buisnessunit", "app", "applciation", "revision"]

    found = {key: tags.dimension_of(key) for key in keys}

    assert {key for key, dimension in found.items() if dimension == "Environment"} == \
        {"environment", "Environemnt", "x_Environment", " envirornment", "env"}
    assert {key for key, dimension in found.items() if dimension == "Project"} == {"projectname", "Project Name", "pojectname"}
    assert found["projectstartdate"] is None and found["createdon"] is None and found["veeam01"] is None
    assert found["revision"] is None   # two edits from "division", but it holds timestamps
    assert found["cost_centre"] == "Cost centre" and found["buisnessunit"] == "Business unit"
    assert found["applciation"] == "Application" and found["app"] == "Application"


def test_exact_spellings_come_first_and_at_most_four_are_queried():
    keys = ["envirornment", "environemnt", "env", "environment", "x_environment", "environmenttype"]

    assert tags.spellings(keys)["Environment"] == ["env", "environment", "x_environment", "environmenttype"]


def test_environment_values_are_folded():
    assert [tags.folded_value("Environment", value) for value in ("prd", "PROD", "Production", " dev ", "UAT", "dr", "")] \
        == ["Production", "Production", "Production", "Development", "Test", "DR", tags.UNTAGGED]
    assert tags.folded_value("Project", " Atlas ") == "Atlas"


def test_spellings_add_up_and_untagged_is_what_none_tagged():
    entries = {"1": {"tags": {"keys": ["environment", "env"], "by_key": {
        "environment": {"dimension": "Environment", "months": {"2026-09": {"prd": 100, "dev": 50, "npr": 0.0, "": 350}}},
        "env": {"dimension": "Environment", "months": {"2026-09": {"Prod": 30, "": 470}}},
    }}}}

    months = tags.dimension_by_month(entries, "Environment", {"2026-09": 500})

    assert months == {"2026-09": {tags.UNTAGGED: 320, "Production": 130, "Development": 50}}


def test_the_report_gives_coverage_for_the_last_closed_month():
    entries = {"1": {"tags": {"keys": ["Project Name"], "by_key": {
        "Project Name": {"dimension": "Project", "months": {"2026-09": {"Atlas": 300, "atlas ": 100, "": 600},
                                                           "2026-10": {"Atlas": 10, "": 90}}}}}}}

    found = tags.report(entries, {"2026-09": 1000, "2026-10": 100}, "2026-10")

    project = found["dimensions"][0]
    assert (project["dimension"], project["last_month"], project["coverage_pct"]) == ("Project", "2026-09", 40.0)
    assert project["months"]["2026-09"] == {tags.UNTAGGED: 600, "Atlas": 400}
    assert project["spellings"] == ["Project Name"]


def test_the_sync_queries_only_the_spellings_an_enrollment_has_once(fake_api):
    asked: list[tuple] = []

    class Azure:
        def list_tag_keys(self, account):
            return ["environment", "veeam01", "projectname"]

        def query_monthly_by_tag(self, account, key, first, last):
            asked.append((key, first, last))
            return [{"month": "2026-09", "value": "prd", "cost": 10.0}, {"month": "2026-09", "value": "", "cost": 5.0}]

    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    directory = AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement",
                                           "term_start": "2026-01-01", "term_end": "2028-12-31"}])
    CustomerBook(store, directory).save(None, {"name": "Contoso", "accounts": ["1"]})
    sync = ConsumptionSync(store, directory, lambda: Azure(), today=lambda: TODAY,
                           now=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc), sleep=lambda _: None)

    sync.run_tags()
    first_run = list(asked)
    sync.run_tags()
    same_day = asked[len(first_run):]
    next_day = ConsumptionSync(store, directory, lambda: Azure(), today=lambda: TODAY,
                               now=lambda: datetime(2026, 10, 18, 9, tzinfo=timezone.utc), sleep=lambda _: None)
    next_day.run_tags()

    assert sorted(first_run) == [("environment", "2026-04", "2026-10"), ("projectname", "2026-04", "2026-10")]
    assert same_day == []   # synced within the day: a restart resumes, it does not redo
    # A day on, settled months are not asked for again; only October, still open.
    assert sorted(asked[len(first_run):]) == [("environment", "2026-10", "2026-10"), ("projectname", "2026-10", "2026-10")]
    saved = store.account("1")["tags"]["by_key"]["environment"]
    assert saved["months"]["2026-09"] == {"prd": 10.0, "": 5.0} and saved["dimension"] == "Environment"


def test_a_key_stored_under_an_old_rule_is_judged_by_todays():
    entries = {"1": {"tags": {"keys": ["revision"], "by_key": {
        "revision": {"dimension": "Business unit", "months": {"2026-09": {"20260831-0517": 5}}}}}}}

    assert tags.dimension_by_month(entries, "Business unit", {"2026-09": 5}) == {}
