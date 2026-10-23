"""The solution catalog, read from the vault (operator, 2026-10-23: "a Solutions
Guide as a new section of the vault" -- the Solution note is the source).

A Solution note (`type: Solution`, under `Work/Solutions/`) is written for the
seller to read and carries what the plugin matches with:

- frontmatter `solution_id`, `name`, `play`;
- `## Pattern`: one fenced JSON block -- `requires`, `supports`, `names`,
  `unless`, `fallback`, `pitches`, as in `solutions.DEFAULT_PATTERNS`;
- `## Sizing`: a table of building blocks with a small, medium and large
  monthly estimate -- the template bill a seller sizes the solution from;
- `## Architecture`: a ```mermaid diagram (operator, 2026-10-23: "add diagrams"),
  shown on the Solutions screens as the note has it.

A note that does not read is left out and named, never guessed at. With no
Solution note in the vault the shipped patterns apply.
"""
from __future__ import annotations

import json
import re
import threading
import time

from . import solutions

NOTE_TYPE = "Solution"
PLAYBOOK_TYPE = "Playbook"
# Every Solutions page reads every note; they change when someone edits one.
CACHE_SECONDS = 60
SIZES = ("small", "medium", "large")
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def _plain(cell: str) -> str:
    """`[[Azure AI Search|AI Search]]` -> `AI Search`."""
    return _WIKILINK.sub(lambda match: (match.group(2) or match.group(1)).strip(), cell).strip()


def _money(cell: str) -> float | None:
    digits = re.sub(r"[^0-9.]", "", cell.split("/")[0])
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def parse_sizing(text: str | None) -> dict | None:
    """The `## Sizing` table: `| Building block | Service | Small | Medium | Large | Basis |`."""
    if not text:
        return None
    rows = []
    for line in text.splitlines():
        # A wikilink's alias pipe is escaped inside an Obsidian table: `[[Note\|Alias]]`.
        cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if not line.strip().startswith("|") or len(cells) < 5 or set(cells[0]) <= set("-: "):
            continue
        if cells[0].lower() in ("building block", "block", "component"):
            continue
        amounts = [_money(cell) for cell in cells[2:5]]
        if all(amount is None for amount in amounts):
            continue
        rows.append({"block": _plain(cells[0]), "service": _plain(cells[1]),
                     **dict(zip(SIZES, amounts)), "basis": _plain(cells[5]) if len(cells) > 5 else ""})
    if not rows:
        return None
    return {"rows": rows, "totals": {size: round(sum(row[size] or 0 for row in rows), 2) for size in SIZES}}


def parse_pattern(text: str | None) -> dict:
    match = _FENCE.search(text or "")
    if not match:
        raise solutions.PatternError("its Pattern section has no ```json block")
    try:
        found = json.loads(match.group(1))
    except ValueError as exc:
        raise solutions.PatternError(f"its Pattern block is not valid JSON ({exc})") from exc
    if not isinstance(found, dict):
        raise solutions.PatternError("its Pattern block is not a JSON object")
    return found


def _summary(text: str | None) -> str:
    first = (text or "").strip().split("\n\n")[0]
    return _plain(first.replace("\n", " "))[:400]


class SolutionNotes:
    def __init__(self, api, clock=time.monotonic) -> None:
        self._api = api
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: tuple[float, dict] | None = None

    def catalog(self) -> dict:
        """`{patterns, source, notes}`: the patterns to match with, whether they came
        from the vault or shipped with the plugin, and each note as read."""
        with self._lock:
            if self._kept and self._clock() - self._kept[0] < CACHE_SECONDS:
                return self._kept[1]
        found = self._read()
        with self._lock:
            self._kept = (self._clock(), found)
        return found

    def playbooks(self) -> list[dict]:
        """The vault's Playbook notes (`type: Playbook`, under `Work/Sales/Playbooks/`):
        name, play, the solution ids they cover and their summary."""
        vault = getattr(self._api, "vault", None)
        found = []
        for entry in (vault.entries() if vault else []):
            frontmatter = entry.get("frontmatter") or {}
            if str(frontmatter.get("type") or "") != PLAYBOOK_TYPE:
                continue
            solutions_covered = frontmatter.get("solutions") or []
            found.append({"stem": entry["stem"], "name": frontmatter.get("name") or entry["stem"],
                          "play": frontmatter.get("play"), "status": frontmatter.get("status"),
                          "solutions": [str(item) for item in solutions_covered] if isinstance(solutions_covered, list) else [],
                          "summary": _summary(vault.read_section(entry["path"], "Summary"))})
        return sorted(found, key=lambda item: item["name"].lower())

    def _read(self) -> dict:
        vault = getattr(self._api, "vault", None)
        entries = [entry for entry in (vault.entries() if vault else [])
                   if str((entry.get("frontmatter") or {}).get("type") or "") == NOTE_TYPE]
        patterns, notes = [], []
        for entry in sorted(entries, key=lambda item: item["stem"].lower()):
            frontmatter = entry.get("frontmatter") or {}
            listed = {"stem": entry["stem"], "name": frontmatter.get("name") or entry["stem"],
                      "id": frontmatter.get("solution_id"), "status": frontmatter.get("status"), "error": None}
            try:
                pattern = parse_pattern(vault.read_section(entry["path"], "Pattern"))
                checked = solutions.validated([{**pattern, "id": frontmatter.get("solution_id"),
                                                "name": listed["name"], "play": frontmatter.get("play")}])[0]
                if any(existing["id"] == checked["id"] for existing in patterns):
                    raise solutions.PatternError(f"another note already uses solution_id {checked['id']!r}")
                checked.update(note=entry["stem"], description=_summary(vault.read_section(entry["path"], "Summary")),
                               sizing=parse_sizing(vault.read_section(entry["path"], "Sizing")),
                               architecture=vault.read_section(entry["path"], "Architecture"))
                patterns.append(checked)
            except solutions.PatternError as exc:
                listed["error"] = str(exc)
            notes.append(listed)
        if not patterns:
            return {"patterns": solutions.patterns(None), "source": "shipped", "notes": notes}
        return {"patterns": patterns, "source": "vault", "notes": notes}
