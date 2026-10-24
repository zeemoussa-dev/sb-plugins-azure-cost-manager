"""Industry knowledge and personas (operator, 2026-10-24).

Worth pinning: the industry is the Customer note's (or its parent's), read from the
Industry note's sections, and its absence is said, never guessed; a persona heads the
system prompt while the feature's task and rules stay under it; an edited persona makes
a kept answer stale; a pitch names an industry use case but its sizing stays the
Solution note's.
"""
from __future__ import annotations

import json

from backend import advisor, industry, personas


class FakeVault:
    """The Plugin API's vault, as far as `industry` reads it: the index and sections."""

    def __init__(self, notes: list[dict]) -> None:
        self._notes = notes

    def entries(self) -> list[dict]:
        return [{key: note[key] for key in ("stem", "path", "frontmatter")} for note in self._notes]

    def read_section(self, path: str, heading: str) -> str | None:
        note = next((note for note in self._notes if note["path"] == path), {})
        return (note.get("sections") or {}).get(heading)


def vault():
    return FakeVault([
        {"stem": "Bankfab", "path": "Customers/Bankfab/Bankfab.md",
         "frontmatter": {"type": "Customer", "industry": "[[Banking]]", "aliases": ["FAB"]}},
        {"stem": "Bankfab Securities", "path": "Customers/Bankfab/Affiliates/Bankfab Securities.md",
         "frontmatter": {"type": "Customer"}},
        {"stem": "Banking", "path": "Industries/Banking.md",
         "frontmatter": {"type": "Industry", "parent": "[[Financial Services]]"},
         "sections": {"Business drivers": "- **CBUAE FIT Programme** -- every bank has integration work.",
                      "Regulatory": "CBUAE Circular C 14/2021: confidential data stays in the UAE.",
                      "Key accounts": "- [[FAB]]: AED 1.40tn assets.\n- [[Emirates NBD]]: AED 1.16tn.\n"
                                      "- Microsoft Fabric partners."}},
        {"stem": "AML Alert Triage", "path": "Industries/Banking/Use Cases/AML Alert Triage.md",
         "frontmatter": {"type": "IndustryUseCase", "industry": "[[Banking]]", "name": "AML alert triage",
                         "outcome": "Fewer false positives per analyst", "solutions": ["[[GenAI Applications]]"]}},
    ])


class Api:
    def __init__(self, found):
        self.vault = found


def test_the_industry_is_the_customer_notes_and_an_affiliate_takes_its_parents():
    context = industry.IndustryContext(Api(vault()))

    found = context.of("Bankfab", "First Abu Dhabi Bank")
    affiliate = context.of("Bankfab Securities", "FAB Securities", parent_stem="Bankfab")

    assert found["industry"] == "Banking" and found["part_of"] == "Financial Services"
    assert "CBUAE" in found["regulation"] and found["this_customer_in_it"] == ["- FAB: AED 1.40tn assets."]
    assert found["use_cases"][0]["solutions"] == ["GenAI Applications"]
    assert affiliate["industry"] == "Banking"


def test_no_industry_is_said_and_recommended_never_guessed():
    context = industry.IndustryContext(Api(vault()))

    assert context.of("Nobody", "Nobody")["missing"].startswith("No industry is set")
    assert industry.linked_name(["[[Banking|Banks]]"]) == "Banking" and industry.linked_name("") is None


def test_a_persona_heads_the_prompt_and_the_task_stays_under_it():
    state: dict = {}
    found = personas.Personas(lambda: state, state.update)
    messages = [{"role": "system", "content": "Answer with JSON."}, {"role": "user", "content": "facts"}]

    found.save("analyst", "You are a banking analyst.")
    applied = personas.apply(messages, found.for_feature("explain"))

    assert applied[0]["content"] == "You are a banking analyst.\n\nAnswer with JSON." and applied[1] == messages[1]
    found.reset("analyst")
    assert found.for_feature("explain") == personas.PERSONAS["analyst"]["prompt"]


def test_every_feature_has_a_persona():
    assert set(personas.FEATURES.values()) <= set(personas.PERSONAS)


def test_a_pitch_names_its_use_case_and_keeps_the_notes_sizing():
    facts = {"catalog": [{"id": "genai", "name": "GenAI Applications", "play": "AI", "sized_monthly": [1, 2, 3]}],
             "playbooks": [], "industry": {"industry": "Banking",
                                           "use_cases": [{"use_case": "AML alert triage", "note": "AML Alert Triage"}]}}
    reply = json.dumps([{"solution_id": "genai", "use_case": "AML alert triage", "business_outcome": "Fewer false positives",
                         "business_owner": "Head of Financial Crime", "pitch": "Triage AML alerts with GenAI",
                         "why": "w", "confidence": "high", "sized_monthly": [999]}])

    found = advisor.check_pitches(reply, facts)[0]

    assert found["use_case_note"] == "AML Alert Triage" and found["business_owner"] == "Head of Financial Crime"
    assert found["sized_monthly"] == [1, 2, 3]
