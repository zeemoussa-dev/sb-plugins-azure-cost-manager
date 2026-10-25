"""Industry use cases: the drill-down and publishing one to the vault (operator, 2026-10-24).

Worth pinning: the note has the `industry-use-case` Template's frontmatter and sections
and is about the industry -- what Compass says about the customer is not in it; it is
written only as a new file beside the Industry note, never over one; publishing links
the pitch to the note, as a pitch matched from the vault would be.
"""
from __future__ import annotations

import json

import pytest

from backend import advisor, use_cases

NOTE = {"name": "AML alert triage", "outcome": "Fewer false positives per analyst", "buyer": "Head of Financial Crime",
        "summary": "Triage alerts with GenAI.", "business_outcome": "b", "who_owns_it": "w", "why_now": "CBUAE",
        "how_it_is_delivered": "Azure OpenAI over case data.", "value_and_kpis": "- Alerts closed per day",
        "discovery_questions": ["How many alerts a month?"], "core42_angle": "In-country inference."}


def test_a_use_case_note_has_the_templates_shape():
    text = use_cases.markdown(NOTE, "Banking", ["GenAI Applications"], "2026-10-24")

    assert text.startswith('---\ntype: "IndustryUseCase"\nname: "AML alert triage"\nindustry: "[[Banking]]"\n'
                           'solutions: ["[[GenAI Applications]]"]\n')
    assert [line[3:] for line in text.splitlines() if line.startswith("## ")] == list(use_cases.SECTIONS)
    assert "Built on: [[GenAI Applications]]." in text and "- How many alerts a month?" in text


def test_a_use_case_is_filed_beside_its_industry_note_and_never_overwritten(tmp_path):
    industry_note = tmp_path / "Financial Services" / "Banking" / "Banking.md"
    industry_note.parent.mkdir(parents=True)
    industry_note.write_text("---\n---\n", encoding="utf-8")

    written = use_cases.write_new(str(industry_note), "AML: alert triage?", "text")

    assert written.endswith("Use Cases\\AML alert triage.md") or written.endswith("Use Cases/AML alert triage.md")
    with pytest.raises(use_cases.UseCaseExists):
        use_cases.write_new(str(industry_note), "AML: alert triage?", "other")


def test_the_customer_part_stays_out_of_the_note():
    reply = json.dumps({"note": {**NOTE, "name": ""}, "for_this_customer": {"why_them": "FAB runs Foundry Models.",
                                                                            "first_step": "s", "questions": ["q"]}})

    found = advisor.check_use_case(reply, {"use_case": "AML alert triage"})

    assert found["note"]["name"] == "AML alert triage"
    assert "FAB" not in use_cases.markdown(found["note"], "Banking", [], "2026-10-24")
    assert found["for_this_customer"]["why_them"].startswith("FAB")


def test_the_expected_services_and_how_to_pitch_go_into_the_note():
    """2026-10-25: a seller sizes and positions from the services a use case needs."""
    reply = json.dumps({"note": {**NOTE, "expected_services": [
        {"service": "Azure OpenAI", "role": "drafts the triage", "core": True},
        {"service": "azure openai", "role": "dup"},
        {"service": "Azure AI Search", "role": "retrieval over cases", "core": False}],
        "how_to_pitch": {"opening": "Cut false positives.", "talk_track": ["Outcome first"],
                         "objections": [{"objection": "Data residency?", "answer": "In-country."}, {"objection": "x"}],
                         "proof_points": ["p"]}},
        "for_this_customer": {"why_them": "w", "how_to_pitch_them": "Start from their Foundry use."}})

    found = advisor.check_use_case(reply, {"use_case": "AML alert triage"})
    text = use_cases.markdown(found["note"], "Banking", [], "2026-10-24")

    assert [item["service"] for item in found["note"]["expected_services"]] == ["Azure OpenAI", "Azure AI Search"]
    assert found["note"]["expected_services"][1]["core"] is False
    assert found["note"]["how_to_pitch"]["objections"] == [{"objection": "Data residency?", "answer": "In-country."}]
    assert "| Azure AI Search | retrieval over cases | add-on |" in text
    assert "**Opening:** Cut false positives." in text and "- *Data residency?* -- In-country." in text
    assert found["for_this_customer"]["how_to_pitch_them"] == "Start from their Foundry use."


def test_expected_services_are_read_against_the_bill_and_go_into_the_opportunity():
    services = [{"service": "Azure Data Factory", "role": "ingest", "core": True},
                {"service": "Microsoft Purview", "role": "govern", "core": False}]

    status = use_cases.on_the_bill(services, {"Azure Data Factory v2": 1200.0, "Storage": 80.0})
    view = use_cases.customer_view({"note": {"name": "Lakehouse", "outcome": "One version of the numbers",
                                             "expected_services": services},
                                    "for_this_customer": {"why_them": "w", "how_to_pitch_them": "h", "questions": ["q"]}},
                                   status, "FAB")

    # Never "missing": a service can run under a name the rule does not know.
    assert status == {"Azure Data Factory": "running", "Microsoft Purview": "not seen"}
    assert "**Why FAB:** w" in view and "**How to pitch them:** h" in view
    assert "| Microsoft Purview | govern | add-on | not seen |" in view
