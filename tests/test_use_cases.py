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

