"""The solution catalog read from the vault's Solution notes.

Worth pinning: a note's Pattern, Sizing and Architecture are read; a broken note
is left out and named; with no Solution note the shipped patterns apply.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend import solution_notes

GENAI = """Text first.

```json
{"requires": [["service:Foundry Models"]], "supports": [], "names": ["ai"],
 "pitches": [{"missing": ["service:API Management"], "pitch": "An AI gateway"}]}
```"""
SIZING = r"""| Building block | Service | Small | Medium | Large | Basis |
|---|---|---|---|---|---|
| Models | [[Azure OpenAI Service\|Azure OpenAI]] | $1,000 | $8,000 | $40,000 | tokens |
| Retrieval | [[Azure AI Search]] | 250 | 1,000 | — | S1 x1 / S1 x3 |"""


def vault_with(notes: dict[str, dict]) -> SimpleNamespace:
    def read_section(path, header):
        return notes[path]["sections"].get(header)
    return SimpleNamespace(
        entries=lambda: [{"path": path, "stem": path, "frontmatter": note["frontmatter"]} for path, note in notes.items()],
        read_section=read_section)


def test_a_solution_note_gives_its_pattern_sizing_and_diagram():
    api = SimpleNamespace(vault=vault_with({
        "GenAI": {"frontmatter": {"type": "Solution", "solution_id": "genai", "name": "GenAI app", "play": "AI & ML"},
                  "sections": {"Pattern": GENAI, "Summary": "Apps on LLMs.\n\nMore.", "Sizing": SIZING,
                               "Architecture": "```mermaid\nflowchart LR\nA-->B\n```"}},
        "Broken": {"frontmatter": {"type": "Solution", "solution_id": "x", "name": "Broken", "play": "AI & ML"},
                   "sections": {"Pattern": "no block here"}},
        "Other": {"frontmatter": {"type": "Technology"}, "sections": {}}}))

    found = solution_notes.SolutionNotes(api).catalog()

    assert found["source"] == "vault" and [pattern["id"] for pattern in found["patterns"]] == ["genai"]
    genai = found["patterns"][0]
    assert (genai["note"], genai["description"]) == ("GenAI", "Apps on LLMs.")
    assert genai["sizing"]["totals"] == {"small": 1250.0, "medium": 9000.0, "large": 40000.0}
    assert genai["sizing"]["rows"][0]["service"] == "Azure OpenAI"
    assert genai["architecture"].startswith("```mermaid")
    assert [note["error"] is not None for note in found["notes"]] == [True, False]   # Broken, GenAI


def test_with_no_solution_note_the_shipped_patterns_apply():
    found = solution_notes.SolutionNotes(SimpleNamespace(vault=vault_with({}))).catalog()
    assert found["source"] == "shipped" and len(found["patterns"]) > 20
