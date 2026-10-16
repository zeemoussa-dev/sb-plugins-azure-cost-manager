"""Billing months as `YYYY-MM` strings -- the one key every module here shares."""
from __future__ import annotations

from calendar import monthrange
from datetime import date


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def shift(month: str, by: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + (number - 1) + by
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def span(first: str, last: str) -> list[str]:
    """Every month from `first` to `last`, both included; empty when reversed."""
    months, current = [], first
    while current <= last:
        months.append(current)
        current = shift(current, 1)
    return months


def first_day(month: str) -> date:
    year, number = (int(part) for part in month.split("-"))
    return date(year, number, 1)


def last_day(month: str) -> date:
    year, number = (int(part) for part in month.split("-"))
    return date(year, number, monthrange(year, number)[1])


def months_between(earlier: date, later: date) -> float:
    return (later - earlier).days / 30.4375
