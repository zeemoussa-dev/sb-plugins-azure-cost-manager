"""What the sync did, step by step, kept on disk (operator, 2026-10-18: "I need to
know why it gets stuck sometimes").

Each run holds its own events: every step it started, every Azure request and
page with its status and duration, every throttle wait, every error. The status
alone showed one line for the step in progress and forgot it at the next restart.

A backend reload stops the sync thread without a word, so a run still marked
running when the plugin loads is closed as interrupted, at the time of its last
event -- the clue to what it was doing when it stopped.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

SYNC_LOG_FILE = "Azure-Cost-Manager/Sync-Log.json"
RUNS_KEPT = 12
# A full sync makes thousands of requests; the newest are what explain a stall.
EVENTS_PER_RUN = 1500
# Writing the whole log on every request would cost more than the request; a
# step change, wait, error or the run's end is written at once.
WRITE_EVERY_SECONDS = 5.0
# A run cut off longer ago than this is not started again on load: by then the
# operator has moved on, and the next Sync or weekly job brings the delta.
RESUME_WITHIN = timedelta(hours=12)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyncLog:
    def __init__(self, read: Callable[[], str | None], write: Callable[[str], None],
                 now: Callable[[], datetime] = _now, clock: Callable[[], float] = time.monotonic) -> None:
        self._write_text = write
        self._now = now
        self._clock = clock
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._in_flight: dict | None = None
        try:
            self._runs: list[dict] = (json.loads(read() or "{}") or {}).get("runs") or []
        except Exception:  # a missing or unreadable log starts empty
            self._runs = []
        interrupted = False
        for run in self._runs:
            if run.get("outcome") == "running":
                last = run["events"][-1]["at"] if run.get("events") else run["started_at"]
                run.update(outcome="interrupted", finished_at=last)
                run["events"].append({"at": last, "kind": "interrupted",
                                      "text": "The backend restarted or stopped; the run ended here."})
                interrupted = True
        if interrupted:
            self._save()

    # -- written by the sync -------------------------------------------------

    def begin(self, scope: str) -> None:
        with self._lock:
            self._runs.append({"id": self._now().strftime("%Y%m%dT%H%M%S%f"), "scope": scope,
                               "started_at": self._now().isoformat(), "finished_at": None, "outcome": "running",
                               "requests": 0, "pages": 0, "throttle_waits": 0, "waited_seconds": 0,
                               "errors": 0, "dropped_events": 0, "events": []})
            del self._runs[:-RUNS_KEPT]
            self._in_flight = None
        self._save()

    def end(self, outcome: str = "finished") -> None:
        with self._lock:
            run = self._current()
            if run is None:
                return
            run.update(outcome="finished with errors" if outcome == "finished" and run["errors"] else outcome,
                       finished_at=self._now().isoformat())
            self._in_flight = None
        self._save()

    def step(self, current: dict) -> None:
        self._add("step", _describe_step(current), urgent=True, account=current.get("account"))

    def error(self, account: str | None, message: str) -> None:
        self._add("error", message, urgent=True, account=account, count="errors")

    def wait(self, seconds: float, where: str) -> None:
        with self._lock:
            run = self._current()
            if run is not None:
                run["throttle_waits"] += 1
                run["waited_seconds"] += round(seconds)
        self._add("wait", f"Azure throttled; waiting {round(seconds)} s ({where})", urgent=True)

    def note(self, text: str, account: str | None = None) -> None:
        """Something the sync decided, such as skipping an enrollment that is fresh."""
        self._add("note", text, account=account)

    # -- written by the Azure client -----------------------------------------

    def request_started(self, what: str) -> None:
        with self._lock:
            self._in_flight = {"what": what, "since": self._now().isoformat()}

    def request_finished(self, what: str, status: int | None, seconds: float, page: bool,
                         failure: str | None = None) -> None:
        with self._lock:
            self._in_flight = None
            run = self._current()
            if run is not None:
                run["requests"] += 1
                run["pages"] += 1 if page else 0
        outcome = failure or f"{status}"
        self._add("request", f"{what} → {outcome} in {seconds:.1f} s",
                  urgent=bool(failure) or (status or 0) >= 400, seconds=round(seconds, 2), status=status)

    # -- read by the page ----------------------------------------------------

    def interrupted_scope(self, within: timedelta = RESUME_WITHIN) -> str | None:
        """The scope of the newest run, when a restart cut it off within `within`.
        Not only a run this load closed: a load can close it and be reloaded itself
        before the resume fires (a refused plugin, an install), and the next load
        must still see it."""
        with self._lock:
            run = self._runs[-1] if self._runs else None
            if not run or run.get("outcome") != "interrupted" or not run.get("finished_at"):
                return None
            if self._now() - datetime.fromisoformat(run["finished_at"]) > within:
                return None
            return run.get("scope")

    def fruitless_in_a_row(self, scope: str) -> int:
        """How many of the newest runs are `scope`, cut off by a restart before they
        asked Azure anything. A resume that never gets anywhere must not be retried
        forever; one that makes progress between restarts may go on."""
        with self._lock:
            count = 0
            for run in reversed(self._runs):
                if run.get("scope") != scope or run.get("outcome") != "interrupted" or run.get("requests"):
                    break
                count += 1
            return count

    def in_flight(self) -> dict | None:
        with self._lock:
            return dict(self._in_flight) if self._in_flight else None

    def runs(self) -> list[dict]:
        """Newest first, without their events."""
        with self._lock:
            return [{key: value for key, value in run.items() if key != "events"} | {"events": len(run["events"])}
                    for run in reversed(self._runs)]

    def events(self, run_id: str | None = None, last: int = 200) -> dict | None:
        with self._lock:
            run = next((run for run in self._runs if run["id"] == run_id), None) if run_id else \
                (self._runs[-1] if self._runs else None)
            if run is None:
                return None
            return {key: value for key, value in run.items() if key != "events"} | {"events": run["events"][-last:]}

    # ------------------------------------------------------------------------

    def _current(self) -> dict | None:
        return self._runs[-1] if self._runs and self._runs[-1]["outcome"] == "running" else None

    def _add(self, kind: str, text: str, urgent: bool = False, count: str | None = None, **fields) -> None:
        with self._lock:
            run = self._current()
            if run is None:
                return
            if count:
                run[count] += 1
            run["events"].append({"at": self._now().isoformat(), "kind": kind, "text": text,
                                  **{key: value for key, value in fields.items() if value is not None}})
            if len(run["events"]) > EVENTS_PER_RUN:
                run["dropped_events"] += len(run["events"]) - EVENTS_PER_RUN
                del run["events"][:-EVENTS_PER_RUN]
            due = urgent or self._clock() - self._last_write >= WRITE_EVERY_SECONDS
        if due:
            self._save()

    def _save(self) -> None:
        with self._lock:
            text = json.dumps({"runs": self._runs}, indent=0)
            self._last_write = self._clock()
        try:
            self._write_text(text)
        except Exception:
            pass  # the log explains the sync; it must never be what stops it


def _describe_step(current: dict) -> str:
    who = current.get("display_name") or current.get("account") or ""
    span = current.get("first_month")
    if span and current.get("last_month") and current["last_month"] != span:
        span = f"{span}..{current['last_month']}"
    what = ("this month by day" if current.get("this_month") else "pricing" if current.get("pricing")
            else f"tag {current['tag']}" if current.get("tag") else "tag keys" if current.get("tags")
            else "amortized meters" if current.get("amortized_meters") else "balance" if current.get("balances")
            else "Marketplace" if current.get("marketplace") else "consumption")
    return " · ".join(part for part in (who, what, span) if part)


def describe_request(method: str, url: str, body: dict | None) -> str:
    """Short enough to read in a list: the API and, for a cost query, its shape."""
    if "skiptoken" in url.lower() or "$skip" in url.lower():
        return "next page"
    path = url.split("?")[0]
    tail = path.split("/providers/")[-1] if "/providers/" in path else path
    tail = tail.replace("Microsoft.", "")
    parts = tail.split("/")
    label = "/".join(parts[-2:]) if len(parts) > 1 else tail
    if body and isinstance(body.get("dataset"), dict):
        dataset = body["dataset"]
        grouping = ",".join(group.get("name", "") for group in dataset.get("grouping") or [])
        period = body.get("timePeriod") or {}
        label += (f" {body.get('type', '')} {dataset.get('granularity', '')} by {grouping or 'total'}"
                  f" {str(period.get('from', ''))[:10]}..{str(period.get('to', ''))[:10]}")
    return f"{method} {label}"
