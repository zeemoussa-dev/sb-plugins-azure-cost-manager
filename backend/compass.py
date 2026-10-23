"""What every Compass feature shares (operator, 2026-10-23: "the rest of the features
LLM reasoning can help the sellers with").

- `ask`: one completion through the framework's `api.llm` (optional under API 12,
  `ADR-063`), or `CompassUnavailable` saying why not.
- `json_array` / `json_object`: the JSON asked for, out of a reply that may fence it.
- `Answers`: a reply kept with the fingerprint of the facts it was written from, so
  the same question about the same data is not asked twice.

The rule every feature follows: the plugin supplies every figure, Compass explains,
ranks and drafts, and what it returns is checked before it is shown.
"""
from __future__ import annotations

import hashlib
import json
import re


class CompassUnavailable(RuntimeError):
    """No model on this framework, or Compass is not configured."""


class CompassAnswerError(ValueError):
    """Compass answered, but not with what was asked for."""


def ask(llm, messages: list[dict[str, str]], timeout: float = 180.0) -> str:
    if llm is None:
        raise CompassUnavailable("This needs a framework that offers Compass to plugins (api.llm, ADR-063): "
                                 "update Second Brain")
    if not llm.available():
        raise CompassUnavailable("Compass is not configured on this install: Settings > System > Compass")
    return llm.complete(messages, timeout=timeout)


def fingerprint(facts) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _parsed(text: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise CompassAnswerError(f"Compass did not answer with the JSON asked for ({exc})") from exc


def json_array(reply: str) -> list:
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", reply, re.DOTALL)
    found = _parsed(fenced.group(1) if fenced else reply[reply.find("["):reply.rfind("]") + 1])
    if not isinstance(found, list):
        raise CompassAnswerError("Compass did not answer with a list")
    return found


def json_object(reply: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.DOTALL)
    found = _parsed(fenced.group(1) if fenced else reply[reply.find("{"):reply.rfind("}") + 1])
    if not isinstance(found, dict):
        raise CompassAnswerError("Compass did not answer with an object")
    return found


def json_block(facts) -> str:
    return "```json\n" + json.dumps(facts, indent=1, default=str) + "\n```"


class Answers:
    """Compass's kept answers: `kind -> key -> {fingerprint, value, at}`, in one data file."""

    def __init__(self, read, write, now) -> None:
        self._read = read
        self._write = write
        self._now = now

    def get(self, kind: str, key: str) -> dict | None:
        return ((self._read() or {}).get(kind) or {}).get(key)

    def put(self, kind: str, key: str, stamp: str, value) -> dict:
        state = self._read() or {}
        kept = {"fingerprint": stamp, "value": value, "at": self._now().isoformat()}
        state.setdefault(kind, {})[key] = kept
        self._write(state)
        return kept

    def current(self, kind: str, key: str, stamp: str) -> dict | None:
        kept = self.get(kind, key)
        return kept if kept and kept.get("fingerprint") == stamp else None
