"""The seller's Compass features beyond the brief.

Worth pinning: a figure a seller sees is the plugin's, never the model's (an
action's value is the Solution note's sizing, a draft's value the size chosen,
a sizing the bill times the factor); an answer about an unknown customer, report
or block is dropped; an explanation is kept per item and data; a question is
answered only from the reports Compass chose to read.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from backend import advisor, compass, use_cases
from backend.advisor_service import Advisor
from backend.consumption_service import ConsumptionService
from backend.consumption_store import ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

SIZING = {"rows": [{"block": "Models", "service": "Azure OpenAI", "small": 100.0, "medium": 1000.0, "large": 5000.0,
                    "basis": "tokens"},
                   {"block": "Search", "service": "AI Search", "small": 50.0, "medium": 250.0, "large": 1000.0,
                    "basis": "S1"}],
          "totals": {"small": 150.0, "medium": 1250.0, "large": 6000.0}}


def test_an_action_keeps_only_known_customers_and_the_notes_sizing():
    facts = {"customers": [{"customer_id": "c", "customer": "Contoso", "last_month": 9000,
                            "pitches": [{"pitch": "Use Compass", "solution": "GenAI", "sized_monthly": [150, 1250, 6000]}]}]}
    reply = json.dumps([{"customer_id": "c", "action": "Pitch Compass", "why": "GenAI without Compass", "urgency": "now",
                         "pitch": "Use Compass", "value": 99999999},
                        {"customer_id": "ghost", "action": "x"}])

    found = advisor.check_actions(reply, facts)

    assert len(found) == 1 and found[0]["sized_monthly"] == [150, 1250, 6000] and "value" not in found[0]


def test_a_draft_takes_its_value_from_the_size_chosen():
    reply = json.dumps({"title": "Contoso GenAI", "summary": "s", "size": "large", "next_steps": ["a"],
                        "email_subject": "Hi", "email_body": "Body", "expected_monthly": 1})
    found = advisor.check_draft(reply, {"sizing": SIZING, "pitch": "p"})
    assert found["expected_monthly"] == 6000.0 and found["size"] == "large"


def test_a_sizing_is_the_bill_times_the_factor_whatever_the_model_says():
    reply = json.dumps({"blocks": [{"block": "Models", "size": "large", "factor": 2, "reason": "2x users"},
                                   {"block": "Search", "size": "huge", "factor": 999}, {"block": "Ghost", "size": "small"}],
                        "assumptions": ["500 users"], "questions": ["How many documents?"]})
    found = advisor.check_sizing(reply, SIZING)
    assert [(row["block"], row["size"], row["factor"], row["monthly"]) for row in found["rows"]] == [
        ("Models", "large", 2.0, 10000.0), ("Search", "medium", 10.0, 2500.0)]
    assert found["total"] == 12500.0


def test_a_plan_keeps_only_known_reports():
    reply = '```json\n{"calls": [{"tool": "growth", "args": {"direction": "declining"}}, {"tool": "rm -rf", "args": {}}]}\n```'
    assert advisor.check_plan(reply) == [{"tool": "growth", "args": {"direction": "declining"}}]


def test_a_marketplace_answer_is_kept_only_for_products_asked_about():
    reply = json.dumps([{"key": "a", "category": "Security", "what": "A firewall", "compass_alternative": False},
                        {"key": "b", "category": "Nonsense"}, {"key": "z", "category": "Security"}])
    assert advisor.check_marketplace(reply, {"a", "b"}) == {
        "a": {"category": "Security", "what": "A firewall", "compass_alternative": False},
        "b": {"category": "Other", "what": "", "compass_alternative": False}}


class FakeLlm:
    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.asked: list = []

    def available(self) -> bool:
        return True

    def complete(self, messages, *, timeout):
        self.asked.append(messages)
        return self.replies.pop(0)


def advisor_with(fake_api, replies):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    months = {month: {"actual": {"service": {"VM": cost, "SQL": 50.0}, "subscription": {"Prod": cost + 50},
                                 "pairs": {"Prod": {"VM": cost, "SQL": 50.0}}}, "meters": {}}
              for month, cost in (("2026-07", 100.0), ("2026-08", 110.0), ("2026-09", 300.0))}
    store.save_account("1", {"months": months})
    llm = FakeLlm(replies)
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                                 now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc), llm=llm)
    state: dict = {}
    answers = compass.Answers(lambda: state, state.update, lambda: datetime(2026, 10, 23, tzinfo=timezone.utc))
    return Advisor(service, answers, llm), llm, book.list()[0]["id"]


def test_an_explanation_is_kept_for_the_item_and_its_data(fake_api):
    found, llm, customer_id = advisor_with(fake_api, ["VM tripled in Prod. **Is it a migration?**"])

    assert found.explain(customer_id, "service", "VM")["kept"] is False
    written = found.explain(customer_id, "service", "VM", write=True)
    assert written["value"].startswith("VM tripled") and not written["stale"]
    facts = json.loads(llm.asked[0][1]["content"].split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    assert facts["by_month"][-1] == {"month": "2026-09", "cost": 300.0} and facts["made_of"][0]["name"] == "Prod"
    assert found.explain(customer_id, "service", "VM")["value"] == written["value"] and len(llm.asked) == 1


def test_a_question_is_answered_from_the_reports_compass_chose(fake_api):
    plan = json.dumps({"calls": [{"tool": "customers_with_but_without", "args": {"has": "VM", "lacks": "Sentinel"}}]})
    found, llm, _ = advisor_with(fake_api, [plan, "Contoso runs VMs without Sentinel."])

    answered = found.ask("Who runs VMs but not Sentinel?")

    assert answered["calls"][0]["rows"] == ["Contoso"] and answered["answer"].startswith("Contoso")
    assert "Contoso" in llm.asked[1][1]["content"]                      # the answer was written from the rows


def test_without_compass_a_feature_says_why(fake_api):
    found, _, customer_id = advisor_with(fake_api, [])
    found._llm = None
    with pytest.raises(compass.CompassUnavailable, match="api.llm"):
        found.explain(customer_id, "service", "VM", write=True)


def test_the_month_still_being_billed_is_marked_partial():
    drill = {"trend": [{"month": "2026-09", "cost": 300.0}, {"month": "2026-10", "cost": 100.0}]}
    facts = advisor.explain_facts(drill, "2026-10")
    assert "partial" not in facts["by_month"][0] and facts["by_month"][1]["partial"]



def test_the_sellers_answer_is_kept_and_handed_to_every_explanation(fake_api):
    found, llm, customer_id = advisor_with(fake_api, ["Guess. **Ask the customer:** why?",
                                                      "A migration from on-premises. **Next:** size the target."])
    found.explain(customer_id, "service", "VM", write=True)

    answered = found.explain(customer_id, "service", "VM", note="They are migrating the SAP estate this quarter")

    told = llm.asked[1][1]["content"]
    assert "migrating the SAP estate" in told and answered["value"].startswith("A migration")
    assert [note["said"] for note in answered["notes"]] == ["They are migrating the SAP estate this quarter"]
    assert found.explain(customer_id, "service", "VM")["notes"] == answered["notes"]   # kept with the item


def test_a_pitch_recommendation_names_a_catalog_solution_and_its_notes_sizing():
    facts = {"catalog": [{"id": "genai", "name": "GenAI", "play": "AI & ML", "sized_monthly": [150, 1250, 6000]}],
             "playbooks": [{"name": "GenAI on Compass", "covers": ["genai"]}]}
    reply = json.dumps([{"solution_id": "genai", "pitch": "Move inference to Compass", "why": "GPT spend grew",
                         "playbook": "GenAI on Compass", "confidence": "high", "value": 1},
                        {"solution_id": "made-up", "pitch": "Something"},
                        {"solution_id": "genai", "pitch": "Move inference to Compass"},
                        {"solution_id": "genai", "pitch": "Add AI Search", "playbook": "No such playbook"}])

    found = advisor.check_pitches(reply, facts)

    assert [item["pitch"] for item in found] == ["Move inference to Compass", "Add AI Search"]
    assert found[0]["sized_monthly"] == [150, 1250, 6000] and found[0]["playbook"] == "GenAI on Compass"
    assert found[1]["playbook"] is None and "value" not in found[0]


def test_a_recommended_pitch_can_be_drafted(fake_api):
    recommend = json.dumps([{"solution_id": "iaas", "pitch": "Modernise the VMs", "why": "VMs grew", "confidence": "high"}])
    draft = json.dumps({"title": "Contoso: modernise", "summary": "s", "size": "medium", "next_steps": [],
                        "email_subject": "Hi", "email_body": "Body"})
    found, _, customer_id = advisor_with(fake_api, [recommend, draft])

    recommended = found.pitches(customer_id, write=True)["value"]
    drafted = found.draft(customer_id, recommended[0]["pitch"])

    assert recommended[0]["solution"] == "Virtual machines (IaaS)" and drafted["title"] == "Contoso: modernise"


def test_the_customers_report_is_never_handed_the_sellers_view(fake_api):
    found, llm, customer_id = advisor_with(fake_api, ["## Where you stand\nCovered.",
                                                       json.dumps({"summary": "s", "moves": [], "reinvest": "r",
                                                                   "questions": []})])

    report = found.finops_report(customer_id, write=True)
    plan = found.finops_plan(customer_id, write=True)

    customer_facts = llm.asked[0][1]["content"]
    assert report["value"].startswith("## Where you stand") and plan["value"]["summary"] == "s"
    assert all(key not in customer_facts for key in ('"pitches"', '"seller_says"', '"commitment"'))
    assert '"seller_says"' in llm.asked[1][1]["content"]
    assert found.finops_plan(customer_id)["kept"] is True and len(llm.asked) == 2


USE_CASE_NOTE = {"name": "AML alert triage", "outcome": "o", "buyer": "b", "discovery_questions": []}


def test_publishing_links_the_pitch_to_its_note(fake_api, tmp_path, monkeypatch):
    found, _, customer_id = advisor_with(fake_api, [])
    industry_note = tmp_path / "Banking" / "Banking.md"
    industry_note.parent.mkdir(parents=True)
    industry_note.write_text("", encoding="utf-8")
    found._answers.put("pitches", customer_id, "stamp", [{"pitch": "Triage AML", "use_case": "AML alert triage"}])
    monkeypatch.setattr(found, "use_case", lambda *args, **kwargs: {
        "value": {"note": USE_CASE_NOTE}, "use_case_note": None, "industry": "Banking",
        "note_markdown": use_cases.markdown(USE_CASE_NOTE, "Banking", [], "2026-10-24")})
    monkeypatch.setattr(found._service, "industry_note_path", lambda name: str(industry_note))

    published = found.publish_use_case(customer_id, "Triage AML")

    assert published["use_case_note"] == "AML alert triage"
    assert (tmp_path / "Banking" / "Use Cases" / "AML alert triage.md").exists()
    assert found._answers.get("pitches", customer_id)["value"][0]["use_case_note"] == "AML alert triage"
    assert found._answers.get("pitches", customer_id)["fingerprint"] == "stamp"


class _OnePipeline:
    def __init__(self, rows):
        self.rows = rows

    def opportunities(self, customer):
        return self.rows


def test_a_snapshot_freezes_a_baseline_before_the_opportunity_could_move_anything(fake_api):
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [{"name": "1", "display_name": "Contoso",
                                                          "agreement_type": "EnterpriseAgreement"}]))
    book.save(None, {"name": "Contoso", "accounts": ["1"], "entity_customer": "Contoso"})
    store.save_account("1", {"months": {f"2026-{month:02d}": {"actual": {"service": {"VM": 100.0 * month, "SQL": 50.0}}}
                                        for month in range(1, 10)}})
    service = ConsumptionService(store, book, today=lambda: date(2026, 10, 25),
                                 now=lambda: datetime(2026, 10, 25, 9, tzinfo=timezone.utc))
    # Entered today, consuming since July: the H2 forecast's shape.
    service._pipeline = _OnePipeline([{"id": "o1", "stem": "Migration", "title": "Migration", "customer": "Contoso",
                                       "affiliate": None, "status": "Open", "stage": "Committed",
                                       "consumption_start": "2026-07", "expected_monthly_usd": 500,
                                       "plan": [{"month": "2026-07", "usd": 500}], "created": "2026-10-25",
                                       "technologies": ["vm"]}])

    snapshot = service.pipeline_snapshot()
    baseline = store.pipeline_snapshots()["baselines"]["o1"]

    assert snapshot["week_end"] == "2026-10-18" and snapshot["taken_late"] and snapshot["fitted_through"] == "2026-09"
    assert snapshot["opportunities"][0]["customer_id"] == book.list()[0]["id"]
    assert snapshot["opportunities"][0]["scope"] == ["VM"]
    assert baseline["fitted_through"] == "2026-06" and baseline["estimated"]
    assert list(baseline["scope_natural"]["by_month"])[0] == "2026-07"
    assert service.pipeline_snapshot() is not None and len(store.pipeline_snapshots()["snapshots"]) == 1
    service.pipeline_snapshot(force=True)
    assert store.pipeline_snapshots()["baselines"]["o1"] == baseline        # a baseline is never recomputed
