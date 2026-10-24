"""An industry use case as a vault note (operator, 2026-10-24: "a drill-down with more
details -- those don't map to an existing solution, so generate a md file matching the
standard and publish it to the vault on the user's click").

A Compass pitch names an industry use case; when no use-case note exists for it, the
drill-down drafts one in the `industry-use-case` Template's shape and the seller may
publish it. It is filed under the industry, in a `Use Cases` folder beside the Industry
note: a use case is industry knowledge (an outcome, its owner, its regulation), while the
technology it runs on is the Solution note it links -- so the next pitch for any customer
in that industry finds it instead of drafting it again.

The note is about the industry, never one customer: what Compass says about the customer
itself stays in the drill-down. Written only as a new file; an existing note is never
overwritten.
"""
from __future__ import annotations

import os
import re

FOLDER = "Use Cases"
SECTIONS = ("Summary", "Business outcome", "Who owns it", "Why now", "How it is delivered", "Value and KPIs",
            "Discovery questions", "Core42 angle", "Sources")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class UseCaseExists(RuntimeError):
    pass


def file_name(name: str) -> str:
    """A use case's name as a file name: Windows' reserved characters taken out."""
    cleaned = " ".join(_UNSAFE.sub(" ", name).split()).strip(" .")
    if not cleaned:
        raise ValueError("the use case has no name to file it under")
    return cleaned[:120]


def _quoted(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tag(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def markdown(note: dict, industry: str, solutions: list[str], today: str) -> str:
    """The note: the Template's frontmatter, then its sections in order. `note` is
    `advisor.check_use_case`'s `note` part."""
    frontmatter = [
        ("type", _quoted("IndustryUseCase")), ("name", _quoted(note["name"])),
        ("industry", _quoted(f"[[{industry}]]")),
        ("solutions", "[" + ", ".join(_quoted(f"[[{name}]]") for name in solutions) + "]"),
        ("outcome", _quoted(note.get("outcome") or "")), ("buyer", _quoted(note.get("buyer") or "")),
        ("status", _quoted("draft")), ("last_refreshed", _quoted(today)),
        ("tags", "[" + ", ".join(_quoted(tag) for tag in ("kind/industry-use-case", f"industry/{_tag(industry)}")) + "]"),
    ]
    questions = "\n".join(f"- {item}" for item in note.get("discovery_questions") or [])
    built_on = ", ".join(f"[[{name}]]" for name in solutions)
    body = {
        "Summary": note.get("summary"),
        "Business outcome": note.get("business_outcome"),
        "Who owns it": note.get("who_owns_it"),
        "Why now": note.get("why_now"),
        "How it is delivered": "\n\n".join(part for part in (
            note.get("how_it_is_delivered"), f"Built on: {built_on}." if built_on else None) if part),
        "Value and KPIs": note.get("value_and_kpis"),
        "Discovery questions": questions,
        "Core42 angle": note.get("core42_angle"),
        "Sources": (f"- Drafted by Compass on {today} from the [[{industry}]] Industry note"
                    + (f" and the {built_on} Solution note{'s' if len(solutions) > 1 else ''}" if built_on else "")
                    + ". Review it before relying on it; set `status` to `reviewed` once you have."),
    }
    lines = ["---", *(f"{key}: {value}" for key, value in frontmatter), "---", ""]
    for section in SECTIONS:
        lines += [f"## {section}", "", (body.get(section) or "").strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def _long(path: str) -> str:
    # A use case's path runs Industries/<sector>/<industry>/Use Cases/<name>.md under a
    # deep OneDrive root: past Windows' 260 characters a plain open() fails.
    absolute = os.path.abspath(path)
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        return "\\\\?\\" + absolute
    return absolute


def write_new(industry_note_path: str, name: str, text: str) -> str:
    """Writes the note beside the Industry note, in its `Use Cases` folder, and returns
    its path. Never overwrites: a note already there is the seller's."""
    folder = os.path.join(os.path.dirname(industry_note_path), FOLDER)
    path = os.path.join(folder, file_name(name) + ".md")
    if os.path.exists(_long(path)):
        raise UseCaseExists(f"a use-case note called {file_name(name)} is already in the vault")
    os.makedirs(_long(folder), exist_ok=True)
    with open(_long(path), "x", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path
