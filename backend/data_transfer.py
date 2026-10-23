"""Moving this plugin's data to another machine (operator, 2026-10-23: "when I move
this into another machine I would not need to sync everything again").

The export is one zip: a `manifest.json` naming what it holds, and each data file
as it is on disk. The sync log stays behind -- it records this machine's runs.
An import takes only the files this plugin knows, each checked to be JSON, and
replaces them whole: two machines' syncs cannot be merged file by file.

MACCs kept on Customer notes live in the vault, not here; they move with it.
"""
from __future__ import annotations

import io
import json
import posixpath
import zipfile
from datetime import datetime

FORMAT = "azure-cost-manager-data"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"


class DataImportError(ValueError):
    pass


def build(files: dict[str, str | None], exported_at: datetime, plugin_version: str | None = None) -> bytes:
    """`files`: data path -> its text (None for a file that does not exist yet)."""
    present = {path: text for path, text in files.items() if text}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps({
            "format": FORMAT, "format_version": FORMAT_VERSION, "plugin_version": plugin_version,
            "exported_at": exported_at.isoformat(), "files": sorted(present),
        }, indent=1))
        for path, text in present.items():
            archive.writestr(f"data/{posixpath.basename(path)}", text)
    return buffer.getvalue()


def read(content: bytes, known: tuple[str, ...]) -> dict[str, str]:
    """The data files in an export, checked: path -> text."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise DataImportError("this is not an Azure Customer 360 export (not a zip file)") from exc
    with archive:
        try:
            manifest = json.loads(archive.read(MANIFEST))
        except (KeyError, ValueError) as exc:
            raise DataImportError("this is not an Azure Customer 360 export (no manifest)") from exc
        if manifest.get("format") != FORMAT:
            raise DataImportError("this is not an Azure Customer 360 export")
        if int(manifest.get("format_version") or 0) > FORMAT_VERSION:
            raise DataImportError("this export is from a newer Azure Customer 360; update the plugin first")
        by_name = {posixpath.basename(path): path for path in known}
        found: dict[str, str] = {}
        for path in manifest.get("files") or []:
            name = posixpath.basename(path)
            if name not in by_name:
                continue          # a file this version does not know is left out, never written
            try:
                text = archive.read(f"data/{name}").decode("utf-8")
                json.loads(text)
            except (KeyError, UnicodeDecodeError, ValueError) as exc:
                raise DataImportError(f"{name} in the export is damaged; nothing was imported") from exc
            found[by_name[name]] = text
    if not found:
        raise DataImportError("the export holds no Azure Customer 360 data")
    return found


def summary(files: dict[str, str], customers_file: str, cache_file: str) -> dict:
    """What an export holds, said in the operator's terms."""
    customers = json.loads(files.get(customers_file) or "{}").get("customers") or []
    accounts = json.loads(files.get(cache_file) or "{}").get("accounts") or {}
    return {"files": len(files), "customers": len(customers), "enrollments": len(accounts)}
