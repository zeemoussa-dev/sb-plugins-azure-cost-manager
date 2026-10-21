"""One customer's consumption as an Excel workbook, laid out and styled like the
operator's own consumption workbook (2026-10-16): a Dashboard of KPI tiles,
summary tables and charts beside them; the automatic forecast; the scenarios;
the Pipeline in its month-by-month grid; and the Export, one block per billing
profile and year. Values and charts only -- no formulas (operator's choice).

The look is the workbook's: Aptos Narrow, no gridlines, navy (#1F3864) section
bars and tab, light-blue KPI tiles, peach tiles for the signed value, #D9E1F2
table headers, thin grey borders, `"$"#,##0` money and `0.0%` percentages.

`openpyxl` is provided to plugin backends by the host (framework API 9).
"""
from __future__ import annotations

import io
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import categories, consumption_analysis, xlsx_pivot
from .office_theme import THEME_XML


def _workbook() -> Workbook:
    """A workbook on the operator's theme, so charts and fonts default to its colours."""
    workbook = Workbook()
    workbook.loaded_theme = THEME_XML.encode("utf8")
    return workbook

# -- the operator's workbook palette and formats ------------------------------
FONT = "Aptos Narrow"
NAVY, BLUE_TAB, SLATE, GREY_TEXT = "1F3864", "2E75B6", "44546A", "595959"
TILE_BLUE, TILE_PEACH, PEACH_TEXT, PEACH_EDGE = "EEF3FB", "FDF2E9", "843C0C", "F4B183"
HEADER_FILL, BAND_FILL, GRID = "D9E1F2", "F2F5FB", "BFBFBF"

MONEY = '"$"#,##0;\\("$"#,##0\\);\\-'
MONEY_CENTS = '\\$#,##0.00;\\(\\$#,##0.00\\);\\$#,##0.00'
PERCENT = '0.0%;\\(0.0%\\);\\-'
MONTH = 'yyyy\\-mm'
INDEX = '0.00'

THIN = Side(style="thin", color=GRID)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MEDIUM_NAVY = Side(style="medium", color=NAVY)
TOTAL_BOX = Border(left=THIN, right=THIN, top=MEDIUM_NAVY, bottom=MEDIUM_NAVY)
PEACH_BOX = Border(left=Side(style="thin", color=PEACH_EDGE), right=Side(style="thin", color=PEACH_EDGE),
                   top=Side(style="thin", color=PEACH_EDGE), bottom=Side(style="thin", color=PEACH_EDGE))

CHART_COLUMN = "J"
CHART_ROWS = 17
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
LONG_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                    "October", "November", "December"]


def _font(size: float = 11, bold: bool = False, italic: bool = False, color: str | None = None) -> Font:
    return Font(name=FONT, size=size, bold=bold, italic=italic, color=color)


def _fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


def _month_date(month: str) -> datetime:
    return datetime(int(month[:4]), int(month[5:]), 1)


def _fraction(percent: float | None) -> float | None:
    return None if percent is None else percent / 100


def _new_sheet(workbook: Workbook, title: str, heading: str, subtitle: str, tab: str = BLUE_TAB, sheet=None):
    sheet = sheet or workbook.create_sheet(title)
    sheet.title = title
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = tab
    sheet["A1"], sheet["A2"] = heading, subtitle
    sheet["A1"].font = _font(16, bold=True)
    sheet["A2"].font = _font(italic=True, color=GREY_TEXT)
    sheet.row_dimensions[1].height = 23.5
    return sheet


def _section(sheet, row: int, title: str, last_column: int = 8) -> None:
    """A navy bar with the section's name, the way the workbook separates sections."""
    for column in range(1, last_column + 1):
        sheet.cell(row, column).fill = _fill(NAVY)
    sheet.cell(row, 1, title).font = _font(bold=True, color="FFFFFF")


def _table(sheet, top: int, headers: list[str], rows: list[list], formats: dict[int, str] | None = None,
           left: int = 1, bold_first: bool = False, total_row: list | None = None) -> int:
    """Header row in the workbook's header style, bordered data rows; returns the last row."""
    for offset, header in enumerate(headers):
        cell = sheet.cell(top, left + offset, header)
        cell.font, cell.fill, cell.border = _font(bold=True), _fill(HEADER_FILL), BOX
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    every = rows + ([total_row] if total_row else [])
    for index, values in enumerate(every, start=1):
        is_total = total_row is not None and index == len(every)
        for offset, value in enumerate(values):
            cell = sheet.cell(top + index, left + offset, value)
            cell.font = _font(bold=is_total or (bold_first and offset == 0))
            cell.border = TOTAL_BOX if is_total else BOX
            if formats and offset in formats and value is not None and not isinstance(value, str):
                cell.number_format = formats[offset]
    return top + len(every)


def _widths(sheet, widths: dict[str, float]) -> None:
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def _labels(chart, money: bool = True) -> None:
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.numFmt = '"$"#,##0.0,,"M"' if money else '0.0%'


def _bar(title: str, sheet, header_row: int, first_row: int, last_row: int, value_columns: list[int],
         label_column: int = 1, stacked: bool = False, percent: bool = False, labelled: bool | None = None) -> BarChart:
    chart = BarChart()
    chart.type, chart.title, chart.width, chart.height = "col", title, 15, 7.5
    chart.gapWidth = 150 if stacked or len(value_columns) > 1 else 219
    if stacked:
        chart.grouping, chart.overlap = "stacked", 100
    for column in value_columns:
        chart.add_data(Reference(sheet, min_col=column, min_row=header_row, max_row=last_row), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=label_column, min_row=first_row, max_row=last_row))
    chart.y_axis.numFmt = '0%' if percent else '"$"#,##0,,"M"'
    chart.y_axis.majorGridlines = None
    if len(value_columns) == 1:
        chart.legend = None
    else:
        chart.legend.position = "b"
    # The workbook labels its bars; with more than ~14 of them the labels overlap.
    if labelled if labelled is not None else (last_row - first_row < 14 and not stacked):
        _labels(chart, money=not percent)
    return chart


def _line(title: str, sheet, header_row: int, first_row: int, last_row: int, value_columns: list[int],
          label_column: int = 1) -> LineChart:
    chart = LineChart()
    chart.title, chart.width, chart.height = title, 15, 7.5
    for column in value_columns:
        chart.add_data(Reference(sheet, min_col=column, min_row=header_row, max_row=last_row), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=label_column, min_row=first_row, max_row=last_row))
    chart.y_axis.numFmt = '"$"#,##0,,"M"'
    chart.y_axis.majorGridlines = None
    chart.legend.position = "b"
    return chart


def _place(sheet, charts: list, row: int) -> int:
    """Charts stacked down column J beside their table; returns the row below the last."""
    for chart in charts:
        sheet.add_chart(chart, f"{CHART_COLUMN}{row}")
        row += CHART_ROWS
    return row


# -- plan lines per month --------------------------------------------------------

def _lines(meters: dict[str, float]) -> dict[str, float]:
    """GPU H100 / GPU H200 / other GPU / PTU / Azure OpenAI tokens out of a month's meters."""
    found = {"GPU H100": 0.0, "GPU H200": 0.0, "GPU other": 0.0, "PTU": 0.0, "OpenAI tokens": 0.0}
    for item in categories.detail(meters or {}):
        if item["category"] == "GPU H100":
            found["GPU H100"] += item["cost"]
        elif item["category"] == "GPU H200":
            found["GPU H200"] += item["cost"]
        elif item["category"].startswith("GPU"):
            found["GPU other"] += item["cost"]
        elif item["category"] == categories.OPENAI_PTU:
            found["PTU"] += item["cost"]
        elif item["category"] == categories.OPENAI_TOKENS:
            found["OpenAI tokens"] += item["cost"]
    return found


def _components(data: dict, measure: dict) -> dict[str, float]:
    """One account-month (or merged month) as the workbook's columns. `Azure` is
    everything that is not GPU or PTU, so the columns add up to `total`."""
    balance = data.get("balance") or {}
    measured = data.get("measured")
    if measured is not None:  # a merged month
        usage, marketplace, credits = measured["usage"], measured["marketplace"], measured["credits"]
        core42 = measured.get("marketplace_core42", 0.0)
    elif balance and not balance.get("missing"):
        usage, marketplace, credits = balance["usage"], balance["marketplace"], balance["credits"]
        core42 = consumption_analysis.core42_marketplace(data)
    else:
        usage = sum(((data.get("actual") or {}).get("service") or {}).values())
        marketplace = credits = core42 = 0.0
    lines = _lines(data.get("meters") or {})
    special = lines["GPU H100"] + lines["GPU H200"] + lines["GPU other"] + lines["PTU"]
    marketplace_counted = core42 if measure["marketplace"] == "core42" else marketplace if measure["marketplace"] else 0.0
    credits_counted = credits if measure["credits"] else 0.0
    return {"marketplace": marketplace, "credits": credits, "azure": usage - special,
            "gpu_h100": lines["GPU H100"], "gpu_h200": lines["GPU H200"], "gpu_other": lines["GPU other"],
            "ptu": lines["PTU"], "openai_tokens": lines["OpenAI tokens"],
            "total": usage + marketplace_counted - credits_counted}


def _as_of(analysis: dict, measure: dict) -> str:
    """Said only when a billing date moved the report off calendar months."""
    if measure.get("billing_day", 1) == 1 or not analysis.get("as_of"):
        return ""
    return f"  ·  as of {analysis['as_of']} (billing date {measure['billing_day']})"


def _marketplace_counted(measure: dict) -> str:
    if measure["marketplace"] == "core42":
        return "Core42's own offers only (Core42 revenue)"
    return "included" if measure["marketplace"] else "excluded"


# -- sheets ------------------------------------------------------------------------

def _dashboard(workbook: Workbook, customer: dict, analysis: dict, merged: dict, today: date) -> None:
    board = analysis["dashboard"]
    kpis = board["kpis"]
    measure = analysis["measure"]
    commitment = analysis.get("commitment")
    automatic = analysis.get("automatic_forecast")
    sheet = _new_sheet(
        workbook, "Dashboard", f"Azure Consumption Dashboard – {customer['name']}",
        f"Data through {kpis['latest_month'] or '—'}  ·  {kpis['months_of_history']} months of history  ·  "
        f"{len(customer['accounts'])} billing profiles  ·  Marketplace {_marketplace_counted(measure)}"
        f", credits {'subtracted' if measure['credits'] else 'not subtracted'}"
        f"{_as_of(analysis, measure)}"
        f"  ·  exported {today.isoformat()}",
        tab=NAVY, sheet=workbook.active)
    sheet.sheet_view.zoomScale = 115
    _widths(sheet, {"A": 41.8, "B": 21, "C": 12, "D": 22.2, "E": 21, "F": 14, "G": 14, "H": 14, "I": 12.7,
                    "K": 34, "L": 24.7})

    # KPI tiles: five a row, in A, B:C, D:E, F:G, H:I -- the workbook's grid.
    tile_columns = [(1, 1), (2, 3), (4, 5), (6, 7), (8, 9)]

    def tiles(row: int, items: list[tuple[str, object, str | None]], peach: bool = False) -> None:
        fill = _fill(TILE_PEACH if peach else TILE_BLUE)
        border = PEACH_BOX if peach else BOX
        for (first, last), (label, value, number_format) in zip(tile_columns, items):
            for line, (text, font) in enumerate([(label.upper(), _font(8, bold=True, color=SLATE)),
                                                 (value if value is not None else "—",
                                                  _font(15, bold=True, color=PEACH_TEXT if peach else NAVY))]):
                if last > first:
                    sheet.merge_cells(start_row=row + line, start_column=first, end_row=row + line, end_column=last)
                for column in range(first, last + 1):
                    sheet.cell(row + line, column).fill = fill
                    sheet.cell(row + line, column).border = border
                cell = sheet.cell(row + line, first, text)
                cell.font, cell.alignment = font, Alignment(horizontal="center", vertical="center", wrap_text=True)
                if line == 1 and number_format and isinstance(value, (int, float)):
                    cell.number_format = number_format
        sheet.row_dimensions[row].height = 16
        sheet.row_dimensions[row + 1].height = 22

    tiles(3, [("Total consumption – all time", kpis["all_time"], MONEY),
              (f"YTD {today.year} (to {kpis['ytd_through'] or '—'})", kpis["ytd"], MONEY),
              ("YTD growth vs last year", _fraction(kpis["ytd_growth_pct"]), PERCENT),
              (f"Latest month total ({kpis['latest_month'] or '—'})", kpis["latest_total"], MONEY),
              ("Active billing profiles", kpis["active_enrollments"], "0")])
    tiles(6, [("Latest month MoM", _fraction(kpis["latest_mom_pct"]), PERCENT),
              ("Latest month YoY", _fraction(kpis["latest_yoy_pct"]), PERCENT),
              ("Next 12 months (auto forecast)", kpis["next_12_months"], MONEY),
              (f"{automatic['next_year'] if automatic else today.year + 1} forecast (auto)", kpis["next_year_forecast"], MONEY),
              ("Largest billing profile share", _fraction(kpis["largest_enrollment_share_pct"]), PERCENT)])
    if commitment:
        tiles(9, [("MACC consumed (% of commitment)", _fraction(commitment["consumed_pct"]), PERCENT),
                  ("MACC remaining ($)", commitment["remaining"], MONEY),
                  ("Consumption rate – 3-mo avg ($/mo)", kpis["burn_rate_3m"], MONEY),
                  ("Runway at current consumption rate (months)", kpis.get("runway_months"), "0.0"),
                  ("Projected exhaustion", commitment["projected_exhaustion"] or "not within term", None)], peach=True)

    # The signed value, as the workbook's MACC block beside the tiles.
    sheet.merge_cells("K2:L2")
    sheet["K2"] = "SIGNED VALUE  ·  entered in the plugin"
    sheet["K2"].font, sheet["K2"].fill = _font(bold=True, color="FFFFFF"), _fill(NAVY)
    if commitment:
        start, end = date.fromisoformat(commitment["start"]), date.fromisoformat(commitment["end"])
        term_months = (end.year - start.year) * 12 + end.month - start.month + 1
        facts = [("Total MACC value ($)" if commitment["type"] == "MACC" else f"Signed value ({commitment['type']})",
                  commitment["amount"], MONEY),
                 ("Start date", datetime(start.year, start.month, start.day), "yyyy-mm-dd"),
                 ("Term duration (months)", term_months, "0"),
                 ("End date", datetime(end.year, end.month, end.day), "yyyy-mm-dd"),
                 ("Term elapsed", _fraction(commitment["elapsed_pct"]), PERCENT),
                 ("Consumed since start ($)", commitment["consumed"], MONEY),
                 ("Consumed % of commitment", _fraction(commitment["consumed_pct"]), PERCENT),
                 ("Remaining ($)", commitment["remaining"], MONEY),
                 ("Against an even pace ($)", commitment["pace_gap"], MONEY),
                 ("Consumption rate – 3-mo avg ($/mo)", commitment["run_rate"], MONEY),
                 ("At term end, at run rate ($)", commitment["projected_at_end"], MONEY),
                 ("At term end, with pipeline ($)", commitment["projected_with_pipeline"], MONEY),
                 ("Projected exhaustion month", commitment["projected_exhaustion"] or "not within term", None),
                 ("Counted against it", "all Marketplace (except excluded offers), less credits", None),
                 ("Affiliates", "each signed its own MACC: only this customer's own enrollments count"
                  if commitment.get("affiliates") == "own" else "roll up: their consumption counts against it", None)]
    else:
        facts = [("No signed value entered for this customer", "", None)]
    for offset, (label, value, number_format) in enumerate(facts, start=3):
        sheet.cell(offset, 11, label).font = _font(9)
        cell = sheet.cell(offset, 12, value)
        cell.font = _font(color="000000")
        for column in (11, 12):
            sheet.cell(offset, column).border = BOX
        if number_format and isinstance(value, (int, float, datetime)):
            cell.number_format = number_format

    monthly = board["monthly"]
    by_month_components = {row["month"]: _components(merged.get(row["month"]) or {}, measure) for row in monthly}

    # Summary -- All Periods
    row = max(13, 3 + len(facts) + 2)
    _section(sheet, row, "Summary – All Periods")
    summary = [["Total consumption – all time", kpis["all_time"], "", "Billing profiles", len(customer["accounts"])],
               ["Months of history", kpis["months_of_history"], "", "First month", kpis["first_month"]],
               ["Marketplace – all time", kpis["marketplace_all_time"], "", "Latest closed month", kpis["latest_month"]],
               ["Credits applied – all time", kpis["credits_all_time"], "", "Current month so far", kpis["current_so_far"]],
               # Core42's revenue: the MACC burn less Marketplace from other publishers.
               ["Core42 revenue – all time", kpis.get("core42_revenue_all_time"), "",
                f"Core42 revenue – {today.year}", kpis.get("core42_revenue_this_year")]]
    for offset, values in enumerate(summary, start=1):
        for column, value in enumerate(values, start=1):
            if column == 3:
                continue
            cell = sheet.cell(row + offset, column, value)
            cell.border = BOX
            cell.font = _font(bold=column in (2, 5))
            if column in (2, 5) and isinstance(value, float):
                cell.number_format = MONEY
    row += len(summary) + 3

    # Consumption by Year
    _section(sheet, row, "Consumption by Year")
    year_rows = []
    previous = None
    for item in board["by_year"]:
        parts = [by_month_components[m] for m in by_month_components if m.startswith(f"{item['year']:04d}-")]
        year_rows.append([item["year"], item["total"], sum(p["azure"] for p in parts),
                          sum(p["gpu_h100"] + p["gpu_h200"] + p["gpu_other"] for p in parts),
                          sum(p["ptu"] for p in parts), sum(p["marketplace"] for p in parts),
                          sum(p["credits"] for p in parts),
                          (item["total"] / previous - 1) if previous else None])
        previous = item["total"]
    year_header = row + 1
    year_last = _table(sheet, year_header, ["Year", "Total", "Azure", "GPU", "PTU", "Marketplace", "Credits", "YoY %"],
                       year_rows, {0: "0", 1: MONEY, 2: MONEY, 3: MONEY, 4: MONEY, 5: MONEY, 6: MONEY, 7: PERCENT},
                       bold_first=False)
    ytd_header = year_last + 2
    ytd_last = _table(sheet, ytd_header, ["Year", f"YTD (Jan–{MONTH_NAMES[int(kpis['ytd_through'][5:]) - 1]})"
                                          if kpis["ytd_through"] else "YTD"],
                      [[item["year"], item["total"]] for item in board["ytd_by_year"]], {0: "0", 1: MONEY})
    chart_end = _place(sheet, [_bar("Total Consumption by Year", sheet, year_header, year_header + 1, year_last, [2]),
                               _bar(f"YTD Total by Year", sheet, ytd_header, ytd_header + 1, ytd_last, [2])], row)
    row = max(ytd_last, chart_end) + 2

    # Monthly Consumption
    _section(sheet, row, "Monthly Consumption")
    month_header = row + 1
    month_rows = []
    for item in monthly:
        parts = by_month_components[item["month"]]
        month_rows.append([_month_date(item["month"]), item["actual"], parts["azure"],
                           parts["gpu_h100"] + parts["gpu_h200"] + parts["gpu_other"], parts["ptu"],
                           parts["marketplace"], parts["credits"], _fraction(item["mom_pct"]), _fraction(item.get("yoy_pct"))])
    month_last = _table(sheet, month_header, ["Month", "Total", "Azure", "GPU", "PTU", "Marketplace", "Credits",
                                              "MoM %", "YoY %"], month_rows,
                        {0: MONTH, 1: MONEY, 2: MONEY, 3: MONEY, 4: MONEY, 5: MONEY, 6: MONEY, 7: PERCENT, 8: PERCENT})
    chart_end = _place(sheet, [
        _bar("Total Consumption by Month", sheet, month_header, month_header + 1, month_last, [2]),
        _bar("Service Mix by Month (Azure / GPU / PTU / Marketplace)", sheet, month_header, month_header + 1,
             month_last, [3, 4, 5, 6], stacked=True),
        _bar("Month-over-Month % – Total Consumption", sheet, month_header, month_header + 1, month_last, [8], percent=True),
        _bar("Year-over-Year % – Total Consumption", sheet, month_header, month_header + 1, month_last, [9], percent=True),
    ], row)
    row = max(month_last, chart_end) + 2

    # This year against last
    comparison = board["this_vs_last_year"]
    _section(sheet, row, f"Monthly Consumption – {comparison['last_year']} vs {comparison['this_year']}")
    compare_header = row + 1
    compare_last = _table(sheet, compare_header, ["Month", str(comparison["last_year"]), str(comparison["this_year"]),
                                                  f"MoM % {comparison['last_year']}", f"MoM % {comparison['this_year']}"],
                          [[MONTH_NAMES[index], comparison["last"][index], comparison["this"][index],
                            _fraction(comparison["last_mom"][index]), _fraction(comparison["this_mom"][index])]
                           for index in range(12)], {1: MONEY, 2: MONEY, 3: PERCENT, 4: PERCENT})
    chart_end = _place(sheet, [
        _bar(f"Monthly Consumption – {comparison['last_year']} vs {comparison['this_year']}", sheet, compare_header,
             compare_header + 1, compare_last, [2, 3], labelled=False),
        _bar(f"MoM Growth % – {comparison['last_year']} vs {comparison['this_year']}", sheet, compare_header,
             compare_header + 1, compare_last, [4, 5], percent=True, labelled=False),
    ], row)
    row = max(compare_last, chart_end) + 2

    # Consumption by Billing Profile
    _section(sheet, row, "Consumption by Billing Profile")
    totals: dict[str, float] = {}
    for data in merged.values():
        for label, cost in ((data.get("actual") or {}).get("account") or {}).items():
            totals[label] = totals.get(label, 0.0) + cost
    grand = sum(totals.values()) or 1.0
    profile_header = row + 1
    profile_last = _table(sheet, profile_header, ["Billing profile", "Total", "Share"],
                          [[label, cost, cost / grand] for label, cost in sorted(totals.items(), key=lambda i: -i[1])],
                          {1: MONEY, 2: PERCENT})
    quarter_header = profile_last + 2
    quarter_rows = [[item["quarter"]] + [item["by_account"].get(name, 0.0) for name in board["accounts"]]
                    for item in board["quarterly"]]
    quarter_last = _table(sheet, quarter_header, ["Quarter"] + board["accounts"], quarter_rows,
                          {index: MONEY for index in range(1, len(board["accounts"]) + 1)})
    chart_end = _place(sheet, [
        _bar("Total Consumption by Billing Profile", sheet, profile_header, profile_header + 1, profile_last, [2]),
        _bar("Quarterly Consumption by Billing Profile", sheet, quarter_header, quarter_header + 1, quarter_last,
             list(range(2, len(board["accounts"]) + 2)), labelled=False),
    ], row)
    row = max(quarter_last, chart_end) + 2

    allocations = analysis.get("allocations")
    if allocations:
        _section(sheet, row, "MACC Allocation across the Group")
        allocation_header = row + 1
        rows = []
        for item in allocations["affiliates"]:
            burn = item["burn"]
            signed = (item["commitment"] or {}).get("amount")
            rows.append([item["name"], signed, burn["consumed"] if burn else item["consumed_against_parent"],
                         _fraction(burn["consumed_pct"]) if burn else None, burn["remaining"] if burn else None,
                         burn["pace_gap"] if burn else None, burn["projected_at_end"] if burn else None])
        rows.append([f"{customer['name']} – unallocated (own enrollments)", allocations["unallocated"],
                     allocations["own"]["consumed"],
                     (allocations["own"]["consumed"] / allocations["unallocated"]) if allocations["unallocated"] else None,
                     allocations["own"]["remaining"], None, None])
        amount = allocations["parent_amount"]
        total = ["Group total", amount, allocations["consumed_total"],
                 (allocations["consumed_total"] / amount) if amount else None,
                 (amount - allocations["consumed_total"]) if amount is not None else None, None, None]
        allocation_last = _table(sheet, allocation_header, ["Affiliate", "Signed MACC", "Consumed", "% consumed",
                                                            "Remaining", "Against even pace", "At term end (run rate)"],
                                 rows, {1: MONEY, 2: MONEY, 3: PERCENT, 4: MONEY, 5: MONEY, 6: MONEY}, total_row=total)
        if allocations["over_allocated"]:
            note = sheet.cell(allocation_last + 1, 1, "The affiliates' MACCs add up to more than the group's.")
            note.font = _font(bold=True, color=PEACH_TEXT)
        chart_end = _place(sheet, [_bar("Signed MACC vs Consumed, by Affiliate", sheet, allocation_header,
                                        allocation_header + 1, allocation_last - 1, [2, 3], labelled=False)], row)
        row = max(allocation_last, chart_end) + 2


def _forecast_auto(workbook: Workbook, analysis: dict, today: date) -> None:
    automatic = analysis.get("automatic_forecast")
    sheet = _new_sheet(workbook, "Forecast Auto", "Forecast – Automatic (no inputs)",
                       "Method: linear trend on actuals (zero months excluded) × month-of-year seasonal index. "
                       "Recalculated by the plugin from the synced data.")
    _widths(sheet, {"A": 47.5, "B": 21, "C": 17.2, "D": 19, "E": 19, "F": 14, "G": 14})
    if not automatic:
        sheet["A4"] = "Not enough billed months for an automatic forecast (six are needed)."
        return
    _section(sheet, 4, "Derived model parameters", last_column=2)
    for column in (4, 5):
        sheet.cell(4, column).fill = _fill(NAVY)
    sheet.cell(4, 4, "Forecast summary").font = _font(bold=True, color="FFFFFF")
    parameters = [("Slope ($/month)", automatic["slope"], MONEY), ("Intercept ($)", automatic["intercept"], MONEY),
                  ("R² of trend fit", automatic["r_squared"], "0.000"),
                  ("Months of actuals", automatic["months_of_history"], "0"),
                  ("Backtest error (MAPE, actual months)", automatic["mape"], "0.0%")]
    summary = [("Next 12 months forecast", automatic["next_12_months"], MONEY),
               ("Next 12 months + pipeline", automatic["next_12_months_with_pipeline"], MONEY),
               (f"{today.year} total (actual + forecast)", automatic["this_year_total"], MONEY),
               (f"{automatic['next_year']} total (forecast)", automatic["next_year_total"], MONEY),
               (f"{automatic['next_year']} + pipeline", automatic["next_year_with_pipeline"], MONEY),
               (f"{automatic['next_year']} vs {today.year} %", _fraction(automatic["next_vs_this_pct"]), "0.0%")]
    for offset, (label, value, number_format) in enumerate(parameters, start=5):
        sheet.cell(offset, 1, label).border = BOX
        cell = sheet.cell(offset, 2, value)
        cell.border, cell.number_format = BOX, number_format
    for offset, (label, value, number_format) in enumerate(summary, start=5):
        sheet.cell(offset, 4, label).border = BOX
        cell = sheet.cell(offset, 5, value)
        cell.border, cell.number_format, cell.font = BOX, number_format, _font(bold=True)

    _section(sheet, 13, "Model timeline – actuals and forecast", last_column=6)
    rows = [[_month_date(item["month"]), item["actual"], item["model"], item["forecast"], item["pipeline"] or None,
             "Actual" if item["actual"] is not None else "Forecast"] for item in automatic["series"]]
    last = _table(sheet, 14, ["Month", "Actual", "Model", "Forecast", "Pipeline", "Type"], rows,
                  {0: MONTH, 1: MONEY, 2: MONEY, 3: MONEY, 4: MONEY})
    sheet.add_chart(_line("Total Consumption – Actual vs Model vs Forecast (auto)", sheet, 14, 15, last, [2, 3, 4]), "I3")
    season_rows = [[MONTH_NAMES[number - 1], automatic["seasonal_index"][str(number)]] for number in range(1, 13)]
    season_last = _table(sheet, 27, ["Month", "Seasonal index"], season_rows, {1: INDEX}, left=18)
    _widths(sheet, {"R": 10, "S": 14})
    chart = _bar("Month-of-year seasonal index (1.00 = average)", sheet, 27, 28, season_last, [19], label_column=18,
                 labelled=False)
    chart.y_axis.numFmt = INDEX
    sheet.add_chart(chart, "I21")


def _forecast_scenarios(workbook: Workbook, analysis: dict) -> None:
    scenarios = analysis.get("scenarios")
    sheet = _new_sheet(workbook, "Forecast Scenarios", "Forecast – Driver-Based Scenarios",
                       "The settings are this customer's, saved in the plugin's Forecast tab; change them there and export again.")
    _widths(sheet, {"A": 49.5, "B": 22.8, "C": 19, "D": 19, "E": 19, "F": 19, "G": 22})
    if not scenarios:
        sheet["A4"] = "No closed month to grow from yet."
        return
    settings = scenarios["settings"]
    _section(sheet, 4, "Inputs", last_column=2)
    inputs = [("Base month (last actual)", _month_date(scenarios["base_month"]), MONTH),
              ("Base month total ($)", scenarios["base_total"], MONEY),
              ("MoM growth % – Base", settings["growth"]["Base"], "0.0%"),
              ("MoM growth % – Upside", settings["growth"]["Upside"], "0.0%"),
              ("MoM growth % – Downside", settings["growth"]["Downside"], "0.0%"),
              ("Apply seasonality?", "Yes" if settings["seasonality"] else "No", None),
              ("Active scenario", settings["active"], None),
              ("Extra monthly uplift ($)", settings["uplift_usd"], MONEY),
              ("Uplift starts from period (yyyy-mm)", settings["uplift_from"] or "—", None)]
    for offset, (label, value, number_format) in enumerate(inputs, start=5):
        sheet.cell(offset, 1, label).border = BOX
        cell = sheet.cell(offset, 2, value)
        cell.border = BOX
        if number_format:
            cell.number_format = number_format
    for column in (4, 5):
        sheet.cell(4, column).fill = _fill(NAVY)
    sheet.cell(4, 4, "Scenario totals (horizon)").font = _font(bold=True, color="FFFFFF")
    totals = [(name, scenarios["totals"][name]) for name in ("Base", "Upside", "Downside")] + \
             [(f"Next year – {name}", scenarios["next_year"][name]) for name in ("Base", "Upside", "Downside")] + \
             [("Pipeline over the horizon", scenarios["pipeline_total"])]
    for offset, (label, value) in enumerate(totals, start=5):
        sheet.cell(offset, 4, label).border = BOX
        cell = sheet.cell(offset, 5, value)
        cell.border, cell.number_format, cell.font = BOX, MONEY, _font(bold=True)

    _section(sheet, 16, "Scenario timeline", last_column=6)
    rows = [[_month_date(item["month"]), item["Base"], item["Upside"], item["Downside"], item["pipeline"] or None,
             item["active_with_pipeline"]] for item in scenarios["rows"]]
    last = _table(sheet, 17, ["Month", "Base", "Upside", "Downside", "Pipeline", f"{settings['active']} + pipeline"],
                  rows, {0: MONTH, 1: MONEY, 2: MONEY, 3: MONEY, 4: MONEY, 5: MONEY})
    sheet.add_chart(_line("Total Consumption – Base / Upside / Downside", sheet, 17, 18, last, [2, 3, 4, 6]), "I3")


def _pipeline(workbook: Workbook, analysis: dict, today: date) -> None:
    """The workbook's Pipeline grid: one row per engagement, its expected $ per
    month under a merged year header, banded rows and a navy total -- a block per year."""
    sheet = workbook.create_sheet("Pipeline")
    sheet.sheet_view.zoomScale = 130
    _widths(sheet, {"A": 4.2, "B": 47.5, "C": 24.7, "D": 30.5, "E": 20, "R": 53.3})
    for column in range(6, 18):
        sheet.column_dimensions[get_column_letter(column)].width = 12
    pipeline = analysis.get("pipeline") or {}
    opportunities = pipeline.get("opportunities") or []
    if not opportunities:
        sheet["B1"] = pipeline.get("reason") or "No opportunities for this customer."
        sheet["B1"].font = _font(italic=True, color=GREY_TEXT)
        return
    years = sorted({int(row["month"][:4]) for o in opportunities for row in o.get("plan") or []}) or [today.year]
    header = _font(10, bold=True, color="FFFFFF")
    body = _font(10, color="000000")
    top = 1
    for year in years:
        for column, title in ((1, "#"), (2, "Engagement"), (3, "Partner"), (4, "Billing Profile"), (5, "Status"),
                              (18, "Comments")):
            sheet.merge_cells(start_row=top, start_column=column, end_row=top + 1, end_column=column)
            cell = sheet.cell(top, column, title)
            cell.font, cell.fill, cell.border = header, _fill(NAVY), BOX
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.merge_cells(start_row=top, start_column=6, end_row=top, end_column=17)
        cell = sheet.cell(top, 6, year)
        cell.font, cell.fill = _font(12, bold=True, color="FFFFFF"), _fill(NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        for index, name in enumerate(MONTH_NAMES):
            cell = sheet.cell(top + 1, 6 + index, name)
            cell.font, cell.fill = header, _fill(NAVY)
            cell.border = Border(left=MEDIUM_NAVY, right=MEDIUM_NAVY, top=MEDIUM_NAVY, bottom=MEDIUM_NAVY)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.row_dimensions[top].height = sheet.row_dimensions[top + 1].height = 22
        month_totals = [0.0] * 12
        for number, opportunity in enumerate(opportunities, start=1):
            row = top + 1 + number
            banded = number % 2 == 1
            plan = {item["month"]: item["usd"] for item in opportunity.get("plan") or []}
            partner = opportunity.get("partner")
            values = [number, opportunity.get("title"), ", ".join(partner) if isinstance(partner, list) else partner,
                      opportunity.get("billing_profile") or "", opportunity.get("status")]
            values += [plan.get(f"{year:04d}-{month:02d}") for month in range(1, 13)]
            comments = [opportunity.get("stage") or ""]
            if opportunity.get("affiliate"):
                comments.append(f"under {opportunity['affiliate']}")
            if opportunity.get("consumption_start"):
                comments.append(f"starts {opportunity['consumption_start']}")
            values.append(" · ".join(item for item in comments if item))
            for column, value in enumerate(values, start=1):
                cell = sheet.cell(row, column, value)
                cell.font = body if column > 1 else _font()
                if column > 1:
                    cell.border = BOX
                    if banded:
                        cell.fill = _fill(BAND_FILL)
                if 6 <= column <= 17:
                    cell.number_format = MONEY
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    month_totals[column - 6] += value or 0
                elif column in (3, 4, 5):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
            sheet.row_dimensions[row].height = 20.15
        total_row = top + 2 + len(opportunities)
        sheet.cell(total_row, 2, f"Total {year}")
        for column in range(2, 19):
            cell = sheet.cell(total_row, column)
            cell.font, cell.fill, cell.border = _font(10, bold=True, color="000000"), _fill(BAND_FILL), TOTAL_BOX
            if 6 <= column <= 17:
                cell.value = month_totals[column - 6] or None
                cell.number_format = MONEY
                cell.alignment = Alignment(horizontal="right", vertical="center")
        top = total_row + 3


def _export(workbook: Workbook, customer: dict, entries: dict[str, dict], measure: dict) -> None:
    """The workbook's Export: per billing profile, per year (newest first), a
    Total row then each month -- the shape the operator built the sheet from."""
    sheet = workbook.create_sheet("Export")
    sheet.sheet_view.zoomScale = 140
    headers = ["Customer Name", "Billing Profile ID", "Date - Year", "Date - Month", "Marketplace",
               "Charges against Credit", "Azure Consumption", "GPU Consumption ND96isrH100v5",
               "GPU Consumption ND96isrH200v5", "GPU Consumption (other)", "PTU Consumption", "Total Consumption"]
    _widths(sheet, {"A": 40, "B": 18.5, "C": 11, "D": 13.3, "E": 13.3, "F": 22, "G": 20, "H": 22, "I": 22,
                    "J": 20, "K": 16, "L": 18})
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(1, column, title)
        cell.font, cell.fill, cell.border = _font(bold=True), _fill(HEADER_FILL), BOX
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    formats = {5: MONEY_CENTS, 6: MONEY_CENTS, 7: MONEY_CENTS, 8: MONEY_CENTS, 9: MONEY_CENTS, 10: MONEY_CENTS,
               11: MONEY_CENTS, 12: MONEY_CENTS}
    names = {account["name"]: account["display_name"] for account in customer["accounts"]}
    row = 2
    grand = [0.0] * 8

    def write(values: list, bold: bool) -> None:
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row, column, value)
            cell.font = _font(bold=bold)
            cell.alignment = Alignment(vertical="top")
            if column in formats and isinstance(value, (int, float)):
                cell.number_format = formats[column]

    for account, entry in entries.items():
        account_top = row
        months_by_year: dict[int, list[str]] = {}
        for month in sorted(entry.get("months") or {}):
            months_by_year.setdefault(int(month[:4]), []).append(month)
        for year in sorted(months_by_year, reverse=True):
            parts = [_components(entry["months"][month], measure) for month in months_by_year[year]]
            if not any(part["total"] or part["azure"] for part in parts):
                continue
            year_top = row

            def numbers(items: list[dict]) -> list[float]:
                return [round(sum(item[key] for item in items), 2) for key in
                        ("marketplace", "credits", "azure", "gpu_h100", "gpu_h200", "gpu_other", "ptu", "total")]

            totals = numbers(parts)
            write([names.get(account, account), account, year, "Total"] + totals, bold=True)
            grand = [a + b for a, b in zip(grand, totals)]
            row += 1
            for month, part in zip(months_by_year[year], parts):
                write([None, None, None, LONG_MONTH_NAMES[int(month[5:]) - 1]] + numbers([part]), bold=False)
                row += 1
            if row - 1 > year_top:
                sheet.merge_cells(start_row=year_top, start_column=3, end_row=row - 1, end_column=3)
        if row - 1 > account_top:
            for column in (1, 2):
                sheet.merge_cells(start_row=account_top, start_column=column, end_row=row - 1, end_column=column)
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    write(["Total", None, None, None] + [round(value, 2) for value in grand], bold=True)
    for column in range(1, 13):
        sheet.cell(row, column).border = TOTAL_BOX
    sheet.freeze_panes = "A2"


def _breakdown(workbook: Workbook, title: str, heading: str, merged: dict, key: str, limit: int = 15) -> None:
    sheet = _new_sheet(workbook, title, heading, "Cost Management actual cost by month: Marketplace included, "
                                                 "credits not subtracted.", tab=BLUE_TAB)
    totals: dict[str, float] = {}
    for data in merged.values():
        for name, cost in ((data.get("actual") or {}).get(key) or {}).items():
            totals[name] = totals.get(name, 0.0) + cost
    names = [name for name, _ in sorted(totals.items(), key=lambda item: -item[1])]
    shown = names[:limit]
    rows = []
    for month in sorted(merged):
        spend = (merged[month].get("actual") or {}).get(key) or {}
        rows.append([_month_date(month)] + [spend.get(name) for name in shown] +
                    ([sum(cost for name, cost in spend.items() if name not in shown)] if len(names) > limit else []))
    headers = ["Month"] + shown + (["Other"] if len(names) > limit else [])
    _table(sheet, 4, headers, rows, {0: MONTH, **{index: MONEY for index in range(1, len(headers))}})
    sheet.column_dimensions["A"].width = 12
    for column in range(2, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 18
    sheet.freeze_panes = "B5"


def _gpu_and_ai(workbook: Workbook, analysis: dict) -> None:
    sheet = _new_sheet(workbook, "GPU & AI", "GPU & AI – by SKU and how it was bought",
                       "GPU by series from the meter, Azure OpenAI PTU (reservations) against pay-as-you-go tokens.")
    _widths(sheet, {"A": 12, "B": 32, "C": 18, "D": 16})
    rows = [[_month_date(item["month"]), line["category"], line["pricing"], line["cost"]]
            for item in analysis["gpu_and_ai"] for line in item["lines"]]
    if not rows:
        sheet["A4"] = "No GPU or Azure OpenAI spend in the synced months."
        return
    _table(sheet, 4, ["Month", "Line", "Bought as", "Cost"], rows, {0: MONTH, 3: MONEY})


def _commitment(workbook: Workbook, analysis: dict) -> None:
    commitment = analysis.get("commitment")
    if not commitment:
        return
    sheet = _new_sheet(workbook, "Commitment", f"Consumption against the signed value ({commitment['type']})",
                       commitment.get("note") or "Entered in the plugin's Settings.", tab=NAVY)
    _widths(sheet, {"A": 14, "B": 22, "C": 22, "D": 22})
    rows = [[_month_date(item["month"]), item["consumed"], commitment["amount"]] for item in commitment["cumulative"]]
    last = _table(sheet, 4, ["Month", "Consumed to date", "Signed value"], rows, {0: MONTH, 1: MONEY, 2: MONEY})
    sheet.add_chart(_line("Consumed against the signed value", sheet, 4, 5, last, [2, 3]), "F3")
    sheet.cell(last + 2, 1, commitment["verdict"]).font = _font(bold=True)


def _credits(workbook: Workbook, analysis: dict) -> None:
    rows = analysis["dashboard"]["credit_details"]
    if not rows:
        return
    sheet = _new_sheet(workbook, "Credits", "Credits applied", "Adjustments on the EA billing-period balance.")
    _widths(sheet, {"A": 12, "B": 40, "C": 18})
    _table(sheet, 4, ["Month", "Credit", "Value"], [[_month_date(r["month"]), r["name"], r["value"]] for r in rows],
           {0: MONTH, 2: MONEY_CENTS})


def _period_text(period: dict) -> str:
    if not period.get("first") or not period.get("last"):
        return "No Marketplace data synced"
    return f"{'From ' if period.get('from_start') else ''}{period['first']} to {period['last']}"


def _marketplace_sheet(workbook: Workbook, report: dict) -> None:
    """One customer's partner solutions: what each cost by month, whether it counts
    toward the MACC, and the solutions adopted at no charge."""
    covered = _period_text(report["period"])
    sheet = _new_sheet(workbook, "Marketplace", "Marketplace – partner solutions",
                       f"{covered}  ·  every Marketplace dollar counts toward the MACC unless its offer is "
                       "marked not eligible in the plugin", tab=NAVY)
    _widths(sheet, {"A": 30, "B": 44, "C": 30, "D": 14, "E": 16, "F": 16, "G": 12, "H": 40})
    row = 4
    for label, value in (("Marketplace total", report["total"]), ("Counts toward the MACC", report["macc"]),
                         ("Does not count", report["not_macc"])):
        sheet.cell(row, 1, label).border = BOX
        cell = sheet.cell(row, 2, value)
        cell.border, cell.number_format, cell.font = BOX, MONEY, _font(bold=True)
        row += 1
    row += 1
    _section(sheet, row, "Solutions bought")
    rows = [[s["publisher"], s["offer"], s["plan"], s["kind"], s["total"], "yes" if s["macc_eligible"] else "no",
             len(s["subscriptions"]), ", ".join(s["subscriptions"][:4]) + (" …" if len(s["subscriptions"]) > 4 else "")]
            for s in report["solutions"]]
    solutions_header = row + 1
    last_row = _table(sheet, solutions_header, ["Publisher", "Offer", "Plan", "Kind", "Total", "Counts toward MACC",
                                               "Subscriptions", "Where"], rows, {4: MONEY})
    if report["publishers"]:
        publisher_header = last_row + 2
        publisher_last = _table(sheet, publisher_header, ["Publisher", "Total", "Toward MACC", "Solutions"],
                                [[p["publisher"], p["total"], p["macc"], p["solutions"]] for p in report["publishers"]],
                                {1: MONEY, 2: MONEY})
        sheet.add_chart(_bar("Marketplace by Publisher", sheet, publisher_header, publisher_header + 1, publisher_last,
                             [2], labelled=publisher_last - publisher_header < 14), "J4")
        last_row = publisher_last
    month_header = last_row + 2
    month_last = _table(sheet, month_header, ["Month", "Total", "Toward MACC", "Not toward MACC"],
                        [[_month_date(m["month"]), m["total"], m["macc"], m["not_macc"]] for m in report["monthly"]],
                        {0: MONTH, 1: MONEY, 2: MONEY, 3: MONEY})
    if report["monthly"]:
        sheet.add_chart(_bar("Marketplace by Month", sheet, month_header, month_header + 1, month_last, [3, 4],
                             stacked=True), "J21")
    if report["adopted"]:
        adopted_top = month_last + 2
        _section(sheet, adopted_top, "Adopted, no charge in the period")
        _table(sheet, adopted_top + 1, ["Publisher", "Offer", "Plan", "Kind", "First seen", "Subscriptions"],
               [[s["publisher"], s["offer"], s["plan"], s["kind"], s["first_month"], len(s["subscriptions"])]
                for s in report["adopted"]])


def _tags(workbook: Workbook, found: dict) -> None:
    """Cost by business tag: per dimension, its values by month and its coverage."""
    sheet = _new_sheet(workbook, "Tags", "Cost by tag",
                       "Each business tag under any of its spellings, values folded (prd, prod, production → "
                       "Production). Untagged is the month's total less what any spelling tagged.", tab=BLUE_TAB)
    _widths(sheet, {"A": 36})
    row = 4
    if not found["dimensions"]:
        sheet.cell(row, 1, "Tags not synced for this customer yet, or none of the business tags is used.")
        return
    for dimension in found["dimensions"]:
        months = sorted(dimension["months"])
        coverage = f"{dimension['coverage_pct']}% tagged in {dimension['last_month']}" \
            if dimension["coverage_pct"] is not None else "coverage not known yet"
        _section(sheet, row, f"{dimension['dimension']} – {coverage} – spelled {len(dimension['all_spellings'])} ways",
                 last_column=max(len(months) + 2, 4))
        totals: dict[str, float] = {}
        for values in dimension["months"].values():
            for name, cost in values.items():
                totals[name] = totals.get(name, 0.0) + cost
        names = sorted(totals, key=lambda name: (name == "(untagged)", -totals[name]))
        row = _table(sheet, row + 1, [dimension["dimension"]] + [_month_date(month) for month in months] + ["Total"],
                     [[name] + [dimension["months"][month].get(name) for month in months] + [totals[name]] for name in names],
                     {index: MONEY for index in range(1, len(months) + 2)}) + 1
        for column in range(2, len(months) + 2):
            sheet.cell(row - len(names) - 1, column).number_format = MONTH
            sheet.column_dimensions[get_column_letter(column)].width = 14
        sheet.cell(row, 1, "Spellings: " + ", ".join(dimension["all_spellings"])).font = _font(italic=True, color=GREY_TEXT)
        row += 2


BUDGET_STATUS = {"over": "Over budget last month", "forecast-over": "Forecast over budget this month",
                 "within": "Within budget"}


def _finops(workbook: Workbook, found: dict) -> None:
    """Commitment coverage, steady on-demand candidates, up-front purchases,
    growth and the budget -- the FinOps report as a sheet."""
    sheet = _new_sheet(workbook, "FinOps", "FinOps – paying less for the same consumption",
                       "Coverage: the share of reservable spend (VMs, GPUs, Azure OpenAI and anything this customer "
                       "has reserved) under a reservation or savings plan, amortized. Closed months only.", tab=NAVY)
    _widths(sheet, {"A": 38, "B": 18, "C": 18, "D": 16, "E": 16, "F": 18, "G": 16})
    latest, budget = found["coverage"]["latest"], found["budget"]
    tiles = [("Commitment coverage", _fraction(latest["coverage_pct"]) if latest else None, PERCENT),
             ("On-demand, reservable", latest["on_demand"] if latest else None, MONEY),
             ("Steady on-demand / month", found["candidates_monthly"], MONEY),
             ("Monthly budget", budget["amount"] if budget else None, MONEY)]
    for index, (label, value, number_format) in enumerate(tiles):
        for line, (text, font) in enumerate([(label.upper(), _font(8, bold=True, color=SLATE)),
                                             (value if value is not None else "—", _font(15, bold=True, color=NAVY))]):
            cell = sheet.cell(4 + line, 1 + index, text)
            cell.font, cell.fill, cell.border = font, _fill(TILE_BLUE), BOX
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if line == 1 and value is not None:
                cell.number_format = number_format
    sheet.row_dimensions[5].height = 22
    row = 7
    if not found["has_meters"]:
        sheet.cell(row, 1, "No meter detail synced for this customer yet: sync it to see FinOps.")
        return

    _section(sheet, row, "Commitment coverage by month", last_column=5)
    header = row + 1
    last = _table(sheet, header, ["Month", "Covered", "On demand", "Coverage"],
                  [[_month_date(m["month"]), m["covered"], m["on_demand"], _fraction(m["coverage_pct"])]
                   for m in found["coverage"]["months"]], {0: MONTH, 1: MONEY, 2: MONEY, 3: PERCENT})
    if found["coverage"]["months"]:
        _place(sheet, [_bar("Covered vs On Demand", sheet, header, header + 1, last, [2, 3], stacked=True)], row)
    else:
        sheet.cell(header + 1, 1, "Amortized meter detail not synced yet: the next sync brings it.")
        last = header + 1
    row = max(last, row + CHART_ROWS) + 2

    if latest:
        _section(sheet, row, f"Coverage by family – {latest['month']}", last_column=5)
        row = _table(sheet, row + 1, ["Family", "Covered", "On demand", "Coverage"],
                     [[f["family"], f["covered"], f["on_demand"], _fraction(f["coverage_pct"])] for f in latest["families"]],
                     {1: MONEY, 2: MONEY, 3: PERCENT}) + 2

    _section(sheet, row, "Steady on-demand candidates – a reservation or savings plan pays here", last_column=8)
    sheet.cell(row + 1, 1, f"Savings are estimates: each VM or GPU series at the average discount across its sizes in "
                           f"{found.get('pricing_region', 'the pricing region')}, from Azure's public price list. A Windows "
                           "meter saves on compute only. Databases, storage and capacities are not priced yet.").font = \
        _font(italic=True, color=GREY_TEXT)
    savings = [(c.get("savings") or {}) for c in found["candidates"]]
    row = _table(sheet, row + 2, ["Meter", "Family", "On demand / month", "Variation", "Save / month, 1-yr savings plan",
                                  "Save / month, 3-yr savings plan", "Save / month, 1-yr reservation",
                                  "Save / month, 3-yr reservation"],
                 [[c["meter"], c["family"], c["monthly_on_demand"], _fraction(c["variation_pct"]),
                   s.get("sp_1y"), s.get("sp_3y"), s.get("ri_1y"), s.get("ri_3y")]
                  for c, s in zip(found["candidates"], savings)],
                 {2: MONEY, 3: PERCENT, 4: MONEY, 5: MONEY, 6: MONEY, 7: MONEY},
                 total_row=["Total", None, found["candidates_monthly"], None]
                 + [found.get("savings_monthly", {}).get(option) for option in ("sp_1y", "sp_3y", "ri_1y", "ri_3y")]
                 if found["candidates"] else None) + 2
    if not found["candidates"]:
        sheet.cell(row - 1, 1, "None: nothing ran on demand at a steady level for the last six months.")
        row += 1

    if found["purchases"]:
        _section(sheet, row, "Commitments bought up front", last_column=4)
        row = _table(sheet, row + 1, ["Month", "Charged", "Amortized", "Bought up front"],
                     [[_month_date(p["month"]), p["charged"], p["amortized"], p["bought_up_front"]]
                      for p in found["purchases"]], {0: MONTH, 1: MONEY, 2: MONEY, 3: MONEY}) + 2

    for key, title in (("services", "Fastest-growing services"), ("subscriptions", "Fastest-growing subscriptions")):
        rows = found["growth"][key]
        if not rows:
            continue
        _section(sheet, row, f"{title} – last three months against the three before", last_column=5)
        row = _table(sheet, row + 1, ["Name", "Monthly now", "Monthly before", "Change", "Change %"],
                     [[g["name"], g["monthly_now"], g["monthly_before"], g["change"], _fraction(g["change_pct"])]
                      for g in rows], {1: MONEY, 2: MONEY, 3: MONEY, 4: PERCENT}) + 2

    if budget:
        _section(sheet, row, "Budget", last_column=4)
        source = ("set in the plugin" if budget["source"] == "set"
                  else f"the MACC spread over its {budget['term_months']} months")
        details = [("Monthly budget", budget["amount"], MONEY), ("From", source, None),
                   (f"Last month ({budget['last_month']})", budget["last_month_actual"], MONEY),
                   ("This month, forecast", budget["current_month_forecast"], MONEY),
                   ("Months over budget, last 12", len(budget["over_in_last_12"]), "0"),
                   ("Status", BUDGET_STATUS[budget["status"]], None)]
        for offset, (label, value, number_format) in enumerate(details, start=row + 1):
            sheet.cell(offset, 1, label).border = BOX
            cell = sheet.cell(offset, 2, value)
            cell.border = BOX
            if number_format and value is not None:
                cell.number_format = number_format


def build_marketplace(report: dict, today: date) -> bytes:
    """Every partner solution across every customer, styled like the operator's workbook."""
    workbook = _workbook()
    covered = _period_text(report["period"])
    sheet = _new_sheet(workbook, "Marketplace Summary", "Azure Marketplace – all customers",
                       f"{covered}  ·  exported {today.isoformat()}  ·  every dollar counts toward the "
                       "customer's MACC unless its offer is marked not eligible", tab=NAVY, sheet=workbook.active)
    sheet.sheet_view.zoomScale = 115
    _widths(sheet, {"A": 40, "B": 18, "C": 18, "D": 14, "E": 40})
    tiles = [("Marketplace total", report["total"], MONEY), ("Toward MACCs", report["macc"], MONEY),
             ("Not toward MACCs", report["not_macc"], MONEY), ("Partner solutions", len(report["solutions"]), "0"),
             ("Publishers", len(report["publishers"]), "0")]
    for index, (label, value, number_format) in enumerate(tiles):
        column = 1 + index
        for line, (text, font) in enumerate([(label.upper(), _font(8, bold=True, color=SLATE)),
                                             (value, _font(15, bold=True, color=NAVY))]):
            cell = sheet.cell(3 + line, column, text)
            cell.font, cell.fill, cell.border = font, _fill(TILE_BLUE), BOX
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if line == 1:
                cell.number_format = number_format
    sheet.row_dimensions[4].height = 22
    row = 7
    _section(sheet, row, "By publisher", last_column=5)
    publisher_header = row + 1
    publisher_last = _table(sheet, publisher_header, ["Publisher", "Total", "Toward MACCs", "Solutions", "Customers"],
                            [[p["publisher"], p["total"], p["macc"], p["solutions"], ", ".join(p["customers"])]
                             for p in report["publishers"]], {1: MONEY, 2: MONEY})
    chart_end = _place(sheet, [_bar("Marketplace Revenue by Publisher", sheet, publisher_header, publisher_header + 1,
                                    publisher_last, [2], labelled=publisher_last - publisher_header < 14)], row)
    row = max(publisher_last, chart_end) + 2
    _section(sheet, row, "By customer", last_column=5)
    customer_header = row + 1
    buyers = [c for c in report["customers"] if c["total"]]
    customer_last = _table(sheet, customer_header, ["Customer / billing profile", "Marketplace", "Toward MACC",
                                                    "Solutions", "Top publisher", "Consumption", "Marketplace share"],
                           [[c["name"] + (" (affiliate)" if c["parent"] else "")
                             + (" (billing profile, not a customer)" if c.get("profile") else ""),
                             c["total"], c["macc"], c["solutions"], c["top_publisher"], c.get("consumption"),
                             (c["total"] / c["consumption"]) if c.get("consumption") else None] for c in buyers],
                           {1: MONEY, 2: MONEY, 5: MONEY, 6: PERCENT})
    chart_end = _place(sheet, [_bar("Marketplace by Customer", sheet, customer_header, customer_header + 1,
                                    customer_last, [2], labelled=customer_last - customer_header < 14)], row)
    row = max(customer_last, chart_end) + 2
    _section(sheet, row, "By month", last_column=5)
    month_header = row + 1
    month_last = _table(sheet, month_header, ["Month", "Total", "Toward MACCs"],
                        [[_month_date(m["month"]), m["total"], m["macc"]] for m in report["monthly"]],
                        {0: MONTH, 1: MONEY, 2: MONEY})
    if report["monthly"]:
        _place(sheet, [_bar("Marketplace by Month", sheet, month_header, month_header + 1, month_last, [2])], row)

    solutions = _new_sheet(workbook, "Solutions", "Partner solutions and who bought them",
                           "One row per offer; plans and buyers beside it.", tab=BLUE_TAB)
    _widths(solutions, {"A": 30, "B": 48, "C": 12, "D": 16, "E": 16, "F": 12, "G": 60, "H": 40})
    _table(solutions, 4, ["Publisher", "Offer", "Kind", "Total", "Toward MACCs", "Customers", "Bought by", "Plans"],
           [[s["publisher"], s["offer"], s["kind"], s["total"], s["macc"], s["adopted_by"],
             ", ".join(f"{c['name']} ({c['total']:,.0f})" for c in s["customers"]), ", ".join(s["plans"])]
            for s in report["solutions"]], {3: MONEY, 4: MONEY})
    solutions.freeze_panes = "C5"

    customers = [c["name"] for c in report["customers"]]
    matrix = _new_sheet(workbook, "Solution x Customer", "Spend by solution and customer",
                        "Each cell is what that customer spent on that offer in the period.", tab=BLUE_TAB)
    rows = []
    for s in report["solutions"]:
        spend = {c["name"]: c["total"] for c in s["customers"]}
        rows.append([s["publisher"], s["offer"]] + [spend.get(name) for name in customers] + [s["total"]])
    _table(matrix, 4, ["Publisher", "Offer"] + customers + ["Total"], rows,
           {index: MONEY for index in range(2, len(customers) + 3)})
    _widths(matrix, {"A": 28, "B": 44})
    for column in range(3, len(customers) + 4):
        matrix.column_dimensions[get_column_letter(column)].width = 18
    matrix.freeze_panes = "C5"

    _marketplace_pivot(workbook, report, covered)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


PIVOT_HEADERS = ["Publisher", "Solution", "Plan", "Buyer", "Group", "Buyer type", "Month", "Amount", "Toward MACC"]


def _marketplace_pivot(workbook: Workbook, report: dict, covered: str) -> None:
    """Who bought which partner solution, when, for how much (operator, 2026-10-17):
    the line-level data as an Excel Table, and a real PivotTable over it --
    Publisher › Solution › Buyer down the side, months across -- placed second, so
    it is the first thing after the summary."""
    lines = report.get("lines") or []
    amount_column = PIVOT_HEADERS.index("Amount")
    rows = xlsx_pivot.fold_case(
        [[line["publisher"], line["solution"], line["plan"], line["buyer"], line["group"], line["buyer_type"],
          line["month"], line["amount"], "Yes" if line["macc_eligible"] else "No"] for line in lines],
        [column for column in range(len(PIVOT_HEADERS)) if column != amount_column])

    data = _new_sheet(workbook, "Marketplace data", "Marketplace lines",
                      f"{covered}  ·  one row per solution, plan, buyer and month  ·  the Pivot sheet is built on it",
                      tab=BLUE_TAB)
    header_row = 4
    _table(data, header_row, PIVOT_HEADERS, rows, {7: MONEY_CENTS})
    _widths(data, {"A": 28, "B": 44, "C": 30, "D": 36, "E": 30, "F": 16, "G": 10, "H": 16, "I": 13})
    data.freeze_panes = data.cell(header_row + 1, 1)
    if rows:
        data.auto_filter.ref = f"A{header_row}:{get_column_letter(len(PIVOT_HEADERS))}{header_row + len(rows)}"

    pivot_sheet = _new_sheet(workbook, "Pivot", "Marketplace pivot – publisher, solution, buyer, month",
                             f"{covered}  ·  an Excel PivotTable: drag fields, filter, expand or collapse. "
                             "Excel builds it when the file opens; a file previewer shows it empty.", tab=NAVY)
    workbook.move_sheet(pivot_sheet, offset=-(len(workbook.sheetnames) - 2))
    if not rows:
        pivot_sheet["A4"] = "No Marketplace lines in the period."
        return
    _widths(pivot_sheet, {"A": 48})
    xlsx_pivot.add_pivot(pivot_sheet, data, header_row, PIVOT_HEADERS, rows,
                         row_fields=["Publisher", "Solution", "Buyer"], column_fields=["Month"],
                         page_fields=["Toward MACC", "Group", "Buyer type"],
                         value_field="Amount", value_caption="Amount (USD)", top_left="A9",
                         name="MarketplacePivot")


def build(customer: dict, analysis: dict, merged: dict, today: date, entries: dict[str, dict] | None = None) -> bytes:
    workbook = _workbook()
    _dashboard(workbook, customer, analysis, merged, today)
    _forecast_auto(workbook, analysis, today)
    # The Customer view leaves out only the scenarios -- the operator's assumptions
    # (operator, 2026-10-17).
    if not analysis.get("customer_view"):
        _forecast_scenarios(workbook, analysis)
    _pipeline(workbook, analysis, today)
    _export(workbook, customer, entries or {}, analysis["measure"])
    if analysis.get("marketplace"):
        _marketplace_sheet(workbook, analysis["marketplace"])
    if analysis.get("finops"):
        _finops(workbook, analysis["finops"])
    if analysis.get("tags"):
        _tags(workbook, analysis["tags"])
    _breakdown(workbook, "Services", "Consumption by Service", merged, "service")
    _breakdown(workbook, "Subscriptions", "Consumption by Subscription", merged, "subscription")
    _gpu_and_ai(workbook, analysis)
    _commitment(workbook, analysis)
    _credits(workbook, analysis)
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None and (cell.font is None or cell.font.name != FONT):
                    cell.font = _font(cell.font.sz or 11, bold=cell.font.b, italic=cell.font.i,
                                      color=cell.font.color.rgb if cell.font.color and isinstance(cell.font.color.rgb, str) else None)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
