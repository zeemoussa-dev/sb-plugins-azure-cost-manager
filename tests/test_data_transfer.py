"""Moving the plugin's data to another machine.

Worth pinning: an export brings back exactly what it held, the cache included and
read afresh; a damaged or foreign file imports nothing; the sync log stays behind.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone

import pytest

from backend import data_transfer
from backend.consumption_service import ConsumptionService
from backend.consumption_store import CONSUMPTION_CACHE_FILE, CUSTOMERS_FILE, DATA_FILES, ConsumptionStore
from backend.customers import AccountDirectory, CustomerBook

ACCOUNTS = [{"name": "1", "display_name": "Contoso", "agreement_type": "EnterpriseAgreement",
             "term_start": "2026-01-01", "term_end": "2028-12-31"}]


def service_on(fake_api) -> tuple[ConsumptionService, ConsumptionStore, CustomerBook]:
    fake_api.get_service = lambda name: None
    store = ConsumptionStore(fake_api)
    book = CustomerBook(store, AccountDirectory(lambda: [dict(a) for a in ACCOUNTS]))
    return ConsumptionService(store, book, today=lambda: date(2026, 10, 23),
                              now=lambda: datetime(2026, 10, 23, tzinfo=timezone.utc)), store, book


def test_an_export_brings_back_what_it_held(fake_api):
    service, store, book = service_on(fake_api)
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    store.save_account("1", {"months": {"2026-09": {"actual": {"service": {"VM": 100.0}}}}, "synced_at": "x"})
    service.save_quota_settings({"quota": 1000})
    name, archive = service.export_data()

    store.save_account("1", {"months": {}, "synced_at": None})         # this machine moves on
    service.save_quota_settings({"quota": 5})
    found = service.import_data(archive)

    assert name.endswith(".zip") and found == {"files": 3, "customers": 1, "enrollments": 1}
    assert store.account("1")["months"]["2026-09"]["actual"]["service"] == {"VM": 100.0}   # read afresh
    assert service.quota_settings()["quota"] == 1000
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        manifest = json.loads(opened.read("manifest.json"))
    assert manifest["format"] == data_transfer.FORMAT and "Azure-Cost-Manager/Sync-Log.json" not in manifest["files"]


def test_a_damaged_or_foreign_file_imports_nothing(fake_api):
    service, store, book = service_on(fake_api)
    book.save(None, {"name": "Contoso", "accounts": ["1"]})
    before = store.customers()

    def zipped(manifest: dict, files: dict[str, str]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, text in files.items():
                archive.writestr(f"data/{name}", text)
        return buffer.getvalue()

    bad = [b"not a zip",
           zipped({"format": "something-else", "files": []}, {}),
           zipped({"format": data_transfer.FORMAT, "format_version": 99, "files": [CUSTOMERS_FILE]}, {}),
           zipped({"format": data_transfer.FORMAT, "format_version": 1, "files": [CUSTOMERS_FILE]},
                  {"Customers.json": "{broken"}),
           zipped({"format": data_transfer.FORMAT, "format_version": 1, "files": ["Elsewhere/Secrets.json"]},
                  {"Secrets.json": "{}"})]
    for content in bad:
        with pytest.raises(data_transfer.DataImportError):
            service.import_data(content)
    assert store.customers() == before


def test_every_data_file_but_the_log_can_travel():
    assert CONSUMPTION_CACHE_FILE in DATA_FILES and CUSTOMERS_FILE in DATA_FILES
    assert not any(path.endswith("Sync-Log.json") for path in DATA_FILES)
