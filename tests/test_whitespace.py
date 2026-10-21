"""Service whitespace against peers.

Worth pinning: a service is common when 30% of customers (and three or more)
use it at $500 a month; a customer's gaps are the common services it does not
use, most common first; Marketplace and Unassigned are never proposed.
"""
from __future__ import annotations

from backend import solution_plays, whitespace


def test_a_gap_is_a_common_service_the_customer_does_not_use():
    usage = {
        "a": {"Azure Kubernetes Service": 2000.0, "Microsoft Defender for Cloud": 900.0, "SaaS": 5000.0},
        "b": {"Azure Kubernetes Service": 4000.0, "Microsoft Defender for Cloud": 1100.0, "SaaS": 5000.0},
        "c": {"Azure Kubernetes Service": 3000.0, "SaaS": 5000.0},
        "d": {"Virtual Machines": 9000.0, "Azure Kubernetes Service": 100.0, "SaaS": 5000.0},
    }

    found = whitespace.analyse(usage, solution_plays.mapping(None))

    assert [gap["service"] for gap in found["d"]["gaps"]] == ["Azure Kubernetes Service"]   # $100 is not using it
    gap = found["d"]["gaps"][0]
    assert (gap["users"], gap["adoption_pct"], gap["typical_monthly"], gap["play"]) == \
        (3, 75, 3000.0, solution_plays.APPS)
    assert found["c"]["gaps"] == []          # Defender: only two users, not common; SaaS is never proposed
    assert found["a"]["uses"] == 3


def test_usage_is_the_average_of_the_last_closed_months():
    merged = {month: {"actual": {"service": {"Storage": cost}}}
              for month, cost in (("2026-06", 9.0), ("2026-07", 300.0), ("2026-08", 600.0), ("2026-09", 900.0),
                                  ("2026-10", 5000.0))}

    assert whitespace.usage(merged, "2026-10") == {"Storage": 600.0}
