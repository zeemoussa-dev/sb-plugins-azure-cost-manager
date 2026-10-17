"""A bearer token for Azure Resource Manager, borrowed from the operator's `az login`.

No secret is stored: the backend uses the CLI's own sign-in, so it sees exactly
the billing accounts the operator sees in the portal (operator, 2026-10-16).
When the sign-in is missing or expired the operator is told to run `az login`;
nothing retries behind their back.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

MANAGEMENT_RESOURCE = "https://management.azure.com/"
_REFRESH_MARGIN = timedelta(minutes=5)
_AZ_TIMEOUT_SECONDS = 60


class AzureSignInError(RuntimeError):
    """Something only the operator can fix: install the CLI, or sign in."""


def _run_az(arguments: list[str]) -> subprocess.CompletedProcess:
    executable = shutil.which("az")
    if executable is None:
        raise AzureSignInError("The Azure CLI (az) is not installed, or not on the backend's PATH.")
    return subprocess.run([executable, *arguments], capture_output=True, text=True,
                          timeout=_AZ_TIMEOUT_SECONDS)


def _expiry(payload: dict) -> datetime:
    # Newer CLIs give `expires_on` as epoch seconds; older ones only `expiresOn`,
    # a naive timestamp in the machine's local time.
    if payload.get("expires_on"):
        return datetime.fromtimestamp(int(payload["expires_on"]), tz=timezone.utc)
    local = datetime.strptime(payload["expiresOn"].split(".")[0], "%Y-%m-%d %H:%M:%S")
    return local.astimezone(timezone.utc)


class AzureCliToken:
    def __init__(self, run_az: Callable[[list[str]], subprocess.CompletedProcess] = _run_az,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._run_az = run_az
        self._now = now
        self._token: str | None = None
        self._expires_at: datetime | None = None
        # The sync thread and page requests both ask for a token; two `az` processes
        # at once contend for the CLI's token cache. One asks, the other waits for it.
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            return self._get()

    def _get(self) -> str:
        if self._token and self._expires_at and self._expires_at - _REFRESH_MARGIN > self._now():
            return self._token
        try:
            completed = self._run_az(["account", "get-access-token", "--resource",
                                      MANAGEMENT_RESOURCE, "--output", "json"])
        except subprocess.TimeoutExpired as exc:
            raise AzureSignInError("The Azure CLI did not answer within a minute.") from exc
        if completed.returncode != 0:
            lines = [line for line in (completed.stderr or "").strip().splitlines() if line.strip()]
            detail = f" ({lines[-1].strip()})" if lines else ""
            raise AzureSignInError(f"No Azure sign-in on this machine -- run `az login`.{detail}")
        try:
            payload = json.loads(completed.stdout)
            self._token = payload["accessToken"]
            self._expires_at = _expiry(payload)
        except (ValueError, KeyError) as exc:
            raise AzureSignInError("The Azure CLI returned a token this plugin cannot read.") from exc
        return self._token

    def forget(self) -> None:
        """After a 401: the cached token was revoked or the operator switched account."""
        with self._lock:
            self._token = None
            self._expires_at = None
