"""The tests stub the Plugin API rather than importing the framework: the plugin
may only reach `app.plugin_api`, so its own tests must not need more than that."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeApi:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.seed_data_files: list[str] = []
        self.routers: list = []
        self.services: dict = {}
        self.data = SimpleNamespace(
            read_text=lambda name: self.files.get(name),
            write_text=lambda name, text: self.files.__setitem__(name, text),
        )

    def register_seed_data_file(self, path: str) -> None:
        self.seed_data_files.append(path)

    def register_router(self, router) -> None:
        self.routers.append(router)

    def provide_service(self, name: str, service) -> None:
        self.services[name] = service


@pytest.fixture
def fake_api() -> FakeApi:
    return FakeApi()


def cost_row(month: str, cost: float, service: str = "Virtual Machines",
             subscription: str = "Prod", currency: str = "USD") -> dict:
    return {"month": month, "service": service, "subscription": subscription,
            "cost": cost, "currency": currency}
