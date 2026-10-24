"""A customer's industry, as the vault knows it (operator, 2026-10-24: "create personas
with customer knowledge and industry-specific knowledge ... so Brief me is guidance of
what to look for, and solutions are industry solutions, not technical ones alone").

The Customer note names its industry in frontmatter -- `industry: "[[Banking]]"` -- and
an affiliate without one takes its parent's. The industry note (`type: Industry`, under
Work/Industries) says what drives the business, its typical use cases, its regulation
and how Core42 is positioned in it; an industry use-case note (`type: IndustryUseCase`)
names a business outcome and the Solution notes it is built on, so a business
recommendation still carries a Solution note's sizing.

No industry set is not an error: every feature works without it and says that setting
it is recommended. Read through the Plugin API's index, never by walking folders.
"""
from __future__ import annotations

import re

INDUSTRY_TYPE = "Industry"
USE_CASE_TYPE = "IndustryUseCase"
SECTIONS = {"what_it_is": "What this is", "business_drivers": "Business drivers",
            "typical_use_cases": "Typical use cases", "regulation": "Regulatory",
            "our_positioning": "Our positioning"}
SECTION_EXCERPT = 1400
USE_CASES_HANDED = 15
MISSING = ("No industry is set on this customer's Customer note. Recommended: add `industry: \"[[<industry>]]\"` "
           "naming a note under Work/Industries, for industry guidance.")
_LINK = re.compile(r"\[\[([^\]|#]+)")


def linked_name(value) -> str | None:
    """`"[[Banking]]"`, `"[[Banking|Banks]]"`, `"Banking"` or a list of them -> `"Banking"`."""
    if isinstance(value, list):
        value = next((item for item in value if item), None)
    if not value:
        return None
    text = str(value).strip()
    match = _LINK.search(text)
    return (match.group(1) if match else text).strip() or None


def _plain(text: str | None, limit: int = SECTION_EXCERPT) -> str | None:
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text or "")
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text).strip()
    return text[:limit] or None


class IndustryContext:
    def __init__(self, api) -> None:
        self._api = api

    def _vault(self):
        return getattr(self._api, "vault", None)

    def _entry(self, entries: list[dict], stem: str | None, kind: str | None = None) -> dict | None:
        if not stem:
            return None
        wanted = stem.lower()
        return next((entry for entry in entries if entry["stem"].lower() == wanted
                     and (kind is None or str((entry.get("frontmatter") or {}).get("type") or "") == kind)), None)

    def name_of(self, customer_stem: str | None, parent_stem: str | None = None,
                entries: list[dict] | None = None) -> str | None:
        """The industry the Customer note (or its parent's) names, or None."""
        vault = self._vault()
        if not vault:
            return None
        entries = entries if entries is not None else vault.entries()
        for stem in (customer_stem, parent_stem):
            hub = self._entry(entries, stem)
            name = linked_name((hub or {}).get("frontmatter", {}).get("industry")) if hub else None
            if name:
                return name
        return None

    def names_of(self, stems: dict[str, tuple[str | None, str | None]]) -> dict[str, str | None]:
        """Many customers' industries from one read of the index: id -> (stem, parent stem)."""
        vault = self._vault()
        if not vault:
            return {customer_id: None for customer_id in stems}
        entries = vault.entries()
        return {customer_id: self.name_of(stem, parent, entries) for customer_id, (stem, parent) in stems.items()}

    def industries(self) -> list[str]:
        vault = self._vault()
        if not vault:
            return []
        return sorted(entry["stem"] for entry in vault.entries()
                      if str((entry.get("frontmatter") or {}).get("type") or "") == INDUSTRY_TYPE)

    def of(self, customer_stem: str | None, customer_name: str, parent_stem: str | None = None) -> dict:
        """What Compass is handed about the customer's industry -- `{"industry": None,
        "missing": ...}` when none is set or its note is not in the vault."""
        vault = self._vault()
        if not vault:
            return {"industry": None, "missing": MISSING}
        entries = vault.entries()
        name = self.name_of(customer_stem, parent_stem, entries)
        if not name:
            return {"industry": None, "missing": MISSING}
        note = self._entry(entries, name, INDUSTRY_TYPE)
        if not note:
            return {"industry": name, "missing": f"The Customer note names the industry {name}, but there is no "
                                                 f"Industry note called {name} under Work/Industries."}
        found: dict = {"industry": name}
        parent = linked_name((note.get("frontmatter") or {}).get("parent"))
        if parent:
            found["part_of"] = parent
        for key, heading in SECTIONS.items():
            text = _plain(vault.read_section(note["path"], heading))
            if text:
                found[key] = text
        # The customer's own line in the industry's key accounts: how the industry sees it.
        accounts = vault.read_section(note["path"], "Key accounts") or ""
        # The industry note names an account the way people do -- "[[FAB]]", not "Bankfab" --
        # so the Customer note's aliases count, as whole words ("FAB" is not "fabric").
        hub = self._entry(entries, customer_stem) or {}
        aliases = (hub.get("frontmatter") or {}).get("aliases") or []
        names = {str(item).strip() for item in (customer_stem, customer_name,
                                                 *(aliases if isinstance(aliases, list) else [aliases])) if item}
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(item) for item in names) + r")\b", re.IGNORECASE) if names else None
        mine = [_plain(line, 600) for line in accounts.splitlines() if pattern and pattern.search(line)]
        if mine:
            found["this_customer_in_it"] = mine[:3]
        found["use_cases"] = self.use_cases(name, parent, entries)
        return found

    def use_cases(self, industry: str, parent: str | None = None, entries: list[dict] | None = None) -> list[dict]:
        """The industry's use-case notes (its parent's too): a business outcome and the
        Solution notes it is built on."""
        vault = self._vault()
        if not vault:
            return []
        entries = entries if entries is not None else vault.entries()
        wanted = {item.lower() for item in (industry, parent) if item}
        found = []
        for entry in entries:
            frontmatter = entry.get("frontmatter") or {}
            if str(frontmatter.get("type") or "") != USE_CASE_TYPE:
                continue
            if (linked_name(frontmatter.get("industry")) or "").lower() not in wanted:
                continue
            solutions = frontmatter.get("solutions") or []
            found.append({"use_case": str(frontmatter.get("name") or entry["stem"]), "note": entry["stem"],
                          "outcome": str(frontmatter.get("outcome") or frontmatter.get("description") or "")[:300],
                          "buyer": frontmatter.get("buyer"),
                          "solutions": [name for name in (linked_name(item) for item in
                                                          (solutions if isinstance(solutions, list) else [solutions]))
                                        if name]})
        return found[:USE_CASES_HANDED]


def short(found: dict | None) -> dict:
    """The industry in a few lines, for features that need its lens and not its detail."""
    found = found or {}
    if not found.get("industry"):
        return {"industry": None}
    return {key: value for key, value in {
        "industry": found["industry"], "part_of": found.get("part_of"),
        "business_drivers": (found.get("business_drivers") or "")[:700] or None,
        "regulation": (found.get("regulation") or "")[:500] or None,
    }.items() if value}
