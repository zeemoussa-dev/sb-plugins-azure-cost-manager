"""The cross-customer reports as Excel workbooks (operator, 2026-10-21: "the new
reports don't have export -- add it and maintain the templates"): growth and
churn, service whitespace, Marketplace whitespace, subscription and tag hygiene,
and Marketplace renewals.

Each is built on `export_xlsx`'s template so it looks like every other workbook
the plugin exports: Aptos Narrow, no gridlines, a navy summary tab, light-blue
KPI tiles, navy section bars, #D9E1F2 headers, `"$"#,##0` money and `0.0%`
percentages, charts down column J. Values only -- no formulas.
"""
from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from .export_xlsx import (BLUE_TAB, BOX, MONEY, MONTH, NAVY, PERCENT, SLATE, TILE_BLUE, _bar, _fill, _font,
                          _fraction, _month_date, _new_sheet, _place, _section, _table, _widths, _workbook)

# Charts show the first rows of a ranked table; more bars than this are unreadable.
CHARTED = 15


def _tiles(sheet, row: int, tiles: list[tuple[str, object, str]]) -> None:
    """KPI tiles across one row, as on the Marketplace workbook's summary."""
    for index, (label, value, number_format) in enumerate(tiles):
        for line, (text, font) in enumerate([(label.upper(), _font(8, bold=True, color=SLATE)),
                                             (value, _font(15, bold=True, color=NAVY))]):
            cell = sheet.cell(row + line, 1 + index, text)
            cell.font, cell.fill, cell.border = font, _fill(TILE_BLUE), BOX
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if line == 1:
                cell.number_format = number_format
    sheet.row_dimensions[row + 1].height = 22


def _summary(workbook: Workbook, title: str, heading: str, subtitle: str, today: date):
    sheet = _new_sheet(workbook, title, heading, f"{subtitle}  ·  exported {today.isoformat()}", tab=NAVY,
                       sheet=workbook.active)
    sheet.sheet_view.zoomScale = 115
    return sheet


def _chart_beside(sheet, title: str, header: int, last: int, column: int, row: int) -> None:
    """A bar chart of a ranked table's first rows, beside it in column J."""
    if last > header:
        _place(sheet, [_bar(title, sheet, header, header + 1, min(last, header + CHARTED), [column],
                            labelled=min(last, header + CHARTED) - header < 14)], row)


def _saved(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# -- growth and churn ----------------------------------------------------------------

def build_growth(rows: list[dict], today: date) -> bytes:
    workbook = _workbook()
    shown = [row for row in rows if row.get("last_month")]
    sheet = _summary(workbook, "Growth and Churn", "Growth and churn – all customers",
                     "Closed months only; 20% either way over three months is a signal; groups include their affiliates",
                     today)
    _widths(sheet, {"A": 44, "B": 12, "C": 12, "D": 16, "E": 16, "F": 12, "G": 12, "H": 12, "I": 60})
    count = lambda status: sum(1 for row in shown if row["status"] == status)  # noqa: E731
    _tiles(sheet, 3, [("Customers", len(shown), "0"), ("Growing", count("growing"), "0"),
                      ("Declining", count("declining"), "0"),
                      ("Stopped or dropped", sum(1 for row in shown if any(signal["kind"] in ("stopped", "drop")
                                                                        for signal in row["signals"])), "0")])
    row = 7
    _section(sheet, row, "Every customer, the largest last month first", last_column=9)
    header = row + 1
    last = _table(sheet, header, ["Customer", "Affiliates", "Status", "Last month", "Monthly, last 3", "3 months",
                                  "12 months", "Year on year", "Signals"],
                  [[item["name"], item["affiliates"] or None, item["status"], item.get("last_total"),
                    item.get("recent_monthly"), _fraction(item.get("change_3m_pct")),
                    _fraction(item.get("change_12m_pct")), _fraction(item.get("yoy_pct")),
                    "; ".join(signal["text"] for signal in item["signals"])] for item in shown],
                  {3: MONEY, 4: MONEY, 5: PERCENT, 6: PERCENT, 7: PERCENT}, bold_first=True)
    sheet.freeze_panes = sheet.cell(header + 1, 2)
    _chart_beside(sheet, "Last Month by Customer", header, last, 4, row)

    moves = _new_sheet(workbook, "Stopped and New", "Services that stopped or started",
                       "Stopped: $1,000+ a month falling under a tenth; new: $1,000+ and not billed in the three months before.")
    _widths(moves, {"A": 44, "B": 12, "C": 40, "D": 18, "E": 16})
    _table(moves, 4, ["Customer", "Change", "Service", "Monthly before", "Last month"],
           [[item["name"], "Stopped", stop["service"], stop["before"], stop["last"]]
            for item in shown for stop in item.get("stopped") or []]
           + [[item["name"], "New", start["service"], None, start["last"]]
              for item in shown for start in item.get("started") or []], {3: MONEY, 4: MONEY})
    moves.freeze_panes = "B5"

    plays = _new_sheet(workbook, "By Solution Play", "Each customer's solution plays, last 3 months against the 3 before",
                       "Monthly averages, Cost Management's actual cost; EA Marketplace from the invoice.")
    _widths(plays, {"A": 44, "B": 20, "C": 18, "D": 18, "E": 16, "F": 12})
    _table(plays, 4, ["Customer", "Solution play", "Monthly, last 3", "Monthly, 3 before", "Change", "Change %"],
           [[item["name"], play["play"], play["recent"], play["before"], play["change"], _fraction(play["change_pct"])]
            for item in shown for play in item.get("by_play") or []],
           {2: MONEY, 3: MONEY, 4: MONEY, 5: PERCENT})
    plays.freeze_panes = "B5"
    return _saved(workbook)


# -- service whitespace --------------------------------------------------------------

def build_whitespace(rows: list[dict], today: date) -> bytes:
    workbook = _workbook()
    sheet = _summary(workbook, "Service Whitespace", "Service whitespace – all customers",
                     "A gap: a service 30%+ of customers (and three or more) use at $500 a month that this one does not",
                     today)
    _widths(sheet, {"A": 44, "B": 16, "C": 14, "D": 10, "E": 70})
    gaps = sum(len(row["gaps"]) for row in rows)
    _tiles(sheet, 3, [("Customers", len(rows), "0"), ("Gaps", gaps, "0"),
                      ("Customers with gaps", sum(1 for row in rows if row["gaps"]), "0")])
    row = 7
    _section(sheet, row, "Every customer, the largest first", last_column=5)
    header = row + 1
    _table(sheet, header, ["Customer", "Monthly spend", "Services used", "Gaps", "Most common gaps"],
           [[item["name"], item.get("monthly"), item["uses"], len(item["gaps"]),
             " · ".join(gap["service"] for gap in item["gaps"][:5])] for item in rows],
           {1: MONEY}, bold_first=True)
    sheet.freeze_panes = sheet.cell(header + 1, 2)

    detail = _new_sheet(workbook, "Gaps", "Every gap, one row per customer and service",
                        "Typical spend: the median monthly spend of the customers who use it.")
    _widths(detail, {"A": 44, "B": 40, "C": 20, "D": 14, "E": 12, "F": 18})
    _table(detail, 4, ["Customer", "Service", "Solution play", "Customers using it", "Adoption", "Typical spend a month"],
           [[item["name"], gap["service"], gap["play"], gap["users"], _fraction(gap["adoption_pct"]),
             gap["typical_monthly"]] for item in rows for gap in item["gaps"]],
           {4: PERCENT, 5: MONEY})
    detail.freeze_panes = "B5"
    return _saved(workbook)


# -- Marketplace whitespace ----------------------------------------------------------

def build_marketplace_whitespace(report: dict, today: date) -> bytes:
    workbook = _workbook()
    period = report.get("period") or {}
    covered = f"{period.get('first') or 'from the start'} to {period.get('last') or ''}"
    sheet = _summary(workbook, "Marketplace Whitespace", "Marketplace whitespace – all customers",
                     f"{covered}  ·  publishers other than Core42, by a category read from their names", today)
    _widths(sheet, {"A": 30, "B": 18, "C": 18, "D": 12, "E": 60})
    _tiles(sheet, 3, [("Other publishers", report["third_party"], MONEY), ("Core42's offers", report["core42"], MONEY),
                      ("Core42's share", _fraction(report["core42_share_pct"]), PERCENT)])
    row = 7
    _section(sheet, row, "By category", last_column=5)
    header = row + 1
    last = _table(sheet, header, ["Category", "Spend", "Toward MACCs", "Customers", "Leading publishers"],
                  [[group["category"], group["total"], group["macc_eligible"], group["customers"],
                    " · ".join(item["publisher"] for item in group["solutions"][:3])] for group in report["categories"]],
                  {1: MONEY, 2: MONEY}, bold_first=True)
    _chart_beside(sheet, "Other Publishers by Category", header, last, 2, row)

    offers = _new_sheet(workbook, "Leading Offers", "The leading offers in each category",
                        "Up to five per category, the largest first.")
    _widths(offers, {"A": 20, "B": 30, "C": 60, "D": 12, "E": 16, "F": 12, "G": 14})
    _table(offers, 4, ["Category", "Publisher", "Offer", "Kind", "Spend", "Customers", "Toward MACC"],
           [[group["category"], item["publisher"], item["offer"], item.get("kind"), item["total"], item["customers"],
             "Yes" if item["macc_eligible"] else "No"] for group in report["categories"] for item in group["solutions"]],
           {4: MONEY})
    offers.freeze_panes = "C5"

    categories = [group["category"] for group in report["categories"]]
    customers = _new_sheet(workbook, "By Customer", "Other publishers' Marketplace, by customer and category",
                           "Customers and billing profiles; Core42's share is of everything the customer bought.")
    _widths(customers, {"A": 44, "B": 18, "C": 18, "D": 14})
    _table(customers, 4, ["Customer or billing profile", "Other publishers", "Toward its MACC", "Core42's share"]
           + categories,
           [[item["name"], item["third_party"], item["macc_eligible"], _fraction(item["core42_share_pct"])]
            + [item["by_category"].get(name) for name in categories] for item in report["customers"]],
           {1: MONEY, 2: MONEY, 3: PERCENT, **{4 + index: MONEY for index in range(len(categories))}})
    for index in range(len(categories)):
        customers.column_dimensions[get_column_letter(5 + index)].width = 16
    customers.freeze_panes = "B5"
    return _saved(workbook)


# -- subscription and tag hygiene ----------------------------------------------------

def build_hygiene(rows: list[dict], today: date) -> bytes:
    workbook = _workbook()
    tags = ["Environment", "Project", "Owner"]
    sheet = _summary(workbook, "Hygiene", "Subscription and tag hygiene – all customers",
                     "The last closed month; groups include their affiliates", today)
    _widths(sheet, {"A": 44, "B": 14, "C": 14, "D": 10, "E": 10, "F": 10, "G": 14, "H": 14, "I": 14, "J": 14,
                    "K": 14})
    _tiles(sheet, 3, [("Customers", len(rows), "0"), ("Subscriptions", sum(row["subscriptions"] for row in rows), "0"),
                      ("Dormant", sum(row["dormant_count"] for row in rows), "0"),
                      ("Tiny", sum(row["tiny"] for row in rows), "0")])
    row = 7
    _section(sheet, row, "Every customer, the most subscriptions first", last_column=11)
    header = row + 1
    _table(sheet, header, ["Customer", "Subscriptions", "In 12 months", "New", "Dormant", "Tiny", "Top one's share",
                           "Top three's share"] + [f"{tag} tagged" for tag in tags],
           [[item["name"], item["subscriptions"], item["subscriptions_12m"], item["new_count"], item["dormant_count"],
             item["tiny"], _fraction(item["top_share_pct"]), _fraction(item["top3_share_pct"])]
            + [_fraction(item["tag_coverage"].get(tag)) if item["tags_synced"] else None for tag in tags]
            for item in rows],
           {6: PERCENT, 7: PERCENT, 8: PERCENT, 9: PERCENT, 10: PERCENT}, bold_first=True)
    sheet.freeze_panes = sheet.cell(header + 1, 2)

    changes = _new_sheet(workbook, "New and Dormant", "Subscriptions that are new or went dormant",
                         "New: $100+ a month and not billed in the three months before. Dormant: $100+ a month over "
                         "those months, now under a tenth of it.")
    _widths(changes, {"A": 44, "B": 12, "C": 50, "D": 18, "E": 16})
    _table(changes, 4, ["Customer", "Change", "Subscription", "Monthly before", "Last month"],
           [[item["name"], "New", new["subscription"], None, new["last"]] for item in rows for new in item["new"]]
           + [[item["name"], "Dormant", gone["subscription"], gone["before"], gone["last"]]
              for item in rows for gone in item["dormant"]], {3: MONEY, 4: MONEY})
    changes.freeze_panes = "B5"
    return _saved(workbook)


# -- Marketplace renewals ------------------------------------------------------------

def build_renewals(rows: list[dict], today: date) -> bytes:
    workbook = _workbook()
    sheet = _summary(workbook, "Renewals", "Marketplace renewals – all customers",
                     "The cadence is read from the charges; one charged once is taken as yearly", today)
    _widths(sheet, {"A": 14, "B": 18, "C": 18})
    upcoming = [row for row in rows if row["status"] != "overdue"]
    _tiles(sheet, 3, [("Upcoming", len(upcoming), "0"), ("At last charge", sum(row["last_amount"] for row in upcoming),
                                                          MONEY),
                      ("Overdue", sum(1 for row in rows if row["status"] == "overdue"), "0")])
    by_month: dict[str, list[dict]] = {}
    for item in upcoming:
        by_month.setdefault(item["next_month"], []).append(item)
    row = 7
    _section(sheet, row, "By month expected", last_column=3)
    header = row + 1
    last = _table(sheet, header, ["Month", "Renewals", "At last charge"],
                  [[_month_date(month), len(items), sum(item["last_amount"] for item in items)]
                   for month, items in sorted(by_month.items())], {0: MONTH, 2: MONEY})
    _chart_beside(sheet, "Renewals by Month", header, last, 3, row)

    calendar = _new_sheet(workbook, "Calendar", "Every renewal, the soonest first",
                          "Overdue: the expected month passed with no charge -- renewed another way, or cancelled.",
                          tab=BLUE_TAB)
    _widths(calendar, {"A": 12, "B": 14, "C": 40, "D": 30, "E": 60, "F": 30, "G": 16, "H": 12, "I": 16, "J": 10})
    _table(calendar, 4, ["Expected", "Status", "Customer", "Publisher", "Offer", "Plan", "Cadence", "Last charged",
                         "Last charge", "Core42"],
           [[_month_date(item["next_month"]), item["status"], item["customer"], item["publisher"], item["offer"],
             item["plan"], item["cadence"] + (" (assumed)" if item["cadence_assumed"] else ""),
             _month_date(item["last_month"]), item["last_amount"], "Yes" if item["core42"] else ""] for item in rows],
           {0: MONTH, 7: MONTH, 8: MONEY})
    calendar.freeze_panes = "C5"
    return _saved(workbook)


# -- baseline and quota --------------------------------------------------------------

def build_quota(report: dict, today: date) -> bytes:
    workbook = _workbook()
    chosen = report["settings"]
    measure = report.get("measure") or {}
    counted = ("Core42's own Marketplace" if measure.get("marketplace") == "core42"
               else "all Marketplace" if measure.get("marketplace", True) else "no Marketplace")
    sheet = _summary(workbook, "Quota", f"Baseline and quota – {chosen['fy']}",
                     f"{chosen['fy_first']} to {chosen['fy_last']}  ·  baseline: the average of {chosen['baseline_start']} "
                     f"to {chosen['baseline_last']}  ·  {counted}, credits "
                     f"{'subtracted' if measure.get('credits', True) else 'not subtracted'}  ·  counted net", today)
    _widths(sheet, {"A": 44, "B": 16, "C": 18, "D": 18, "E": 20, "F": 16, "G": 16, "H": 12})
    _tiles(sheet, 3, [("Quota", chosen.get("quota"), MONEY), ("Above baseline to date", report["above_to_date"], MONEY),
                      ("Attained", _fraction(report["attained_pct"]), PERCENT),
                      ("Projected", report["above_projected"], MONEY),
                      ("With pipeline", report["above_with_pipeline"], MONEY),
                      ("Gap to quota", report.get("gap_to_quota"), MONEY)])
    row = 7
    _section(sheet, row, "Every customer, the most projected above the line first", last_column=8)
    header = row + 1
    last = _table(sheet, header, ["Customer", "Baseline a month", "Above, to date", "Projected, year",
                                  "With pipeline", "Pipeline planned", "Pipeline gap", "Behind plan"],
                  [[item["name"], item["baseline"], item["above_to_date"], item["above_projected"],
                    item["above_with_pipeline"], item["pipeline"]["planned_to_date"] or None,
                    item["pipeline"]["gap"] if item["pipeline"]["planned_to_date"] else None,
                    "Yes" if item["pipeline"]["behind"] else ""] for item in report["customers"]],
                  {1: MONEY, 2: MONEY, 3: MONEY, 4: MONEY, 5: MONEY, 6: MONEY}, bold_first=True,
                  total_row=["Total", None, report["above_to_date"], report["above_projected"],
                             report["above_with_pipeline"], None, None, None])
    sheet.freeze_panes = sheet.cell(header + 1, 2)
    _chart_beside(sheet, "Projected Above Baseline by Customer", header, last - 1, 4, row)

    missed = _new_sheet(workbook, "Missed Forecasts", "Opportunities that planned more than happened",
                        "Open and Won opportunities' planned consumption in the year's closed months, where the customer "
                        "added less above its line than they planned together.")
    _widths(missed, {"A": 40, "B": 60, "C": 10, "D": 16, "E": 12, "F": 18, "G": 20})
    _table(missed, 4, ["Customer", "Opportunity", "Status", "Stage", "Planned from", "Planned to date",
                       "Customer added to date"],
           [[item["name"], opportunity["title"], opportunity["status"], opportunity["stage"],
             _month_date(opportunity["first_month"]), opportunity["planned_to_date"], item["pipeline"]["achieved_to_date"]]
            for item in report["customers"] for opportunity in item["missed"]],
           {4: MONTH, 5: MONEY, 6: MONEY})
    missed.freeze_panes = "B5"
    return _saved(workbook)
