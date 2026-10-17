"""A real Excel PivotTable over a data sheet, written with openpyxl's pivot parts.

openpyxl has no "make a pivot" call: it reads and writes the parts of one -- a
pivot cache (the source range, each field's distinct values, the records) and a
pivot table (which field goes where). This module builds both. The table is
written without its laid-out cells and marked to refresh when the file opens,
so Excel draws it from the cache; a reader that never refreshes (a previewer)
shows an empty pivot, which the sheet's note says.

A column is either text, every value of which becomes a shared item the records
point at, or a number, which records carry as itself and the pivot sums.
"""
from __future__ import annotations

from openpyxl.pivot.cache import CacheDefinition, CacheField, CacheSource, SharedItems, WorksheetSource
from openpyxl.pivot.fields import Index, Number, Text
from openpyxl.pivot.record import Record, RecordList
from openpyxl.pivot.table import (
    DataField, FieldItem, Location, PageField, PivotField, PivotTableStyle, RowColField, TableDefinition,
)
from openpyxl.utils import get_column_letter

# Excel's built-in "#,##0" -- a pivot's value format must be one the workbook
# already defines, and built-ins always are.
WHOLE_NUMBER_FORMAT_ID = 3


def fold_case(rows: list[list], text_columns: list[int]) -> list[list]:
    """Each text value spelled one way. Excel compares pivot items ignoring case,
    so "CommVault" and "Commvault" are one item to it and two in the cache --
    and a workbook with such a cache does not open at all (Azure bills the same
    publisher and plan under both spellings). The most used spelling wins."""
    folded = [list(row) for row in rows]
    for column in text_columns:
        counts: dict[str, dict[str, int]] = {}
        for row in folded:
            value = str(row[column]).strip()
            row[column] = value
            spellings = counts.setdefault(value.lower(), {})
            spellings[value] = spellings.get(value, 0) + 1
        chosen = {key: min(spellings, key=lambda spelling: (-spellings[spelling], spelling))
                  for key, spellings in counts.items()}
        for row in folded:
            row[column] = chosen[row[column].lower()]
    return folded


def add_pivot(target, source, header_row: int, headers: list[str], rows: list[list],
              row_fields: list[str], column_fields: list[str], page_fields: list[str],
              value_field: str, value_caption: str, top_left: str = "A3", name: str = "Pivot") -> None:
    """A PivotTable on `target` over `rows` (already written to `source` under
    `headers` at `header_row`), summing `value_field`."""
    numeric = {index for index, header in enumerate(headers) if header == value_field}
    distinct: list[list[str]] = []
    for index in range(len(headers)):
        distinct.append([] if index in numeric else sorted({str(row[index]) for row in rows}, key=str.lower))
    position = [{value: at for at, value in enumerate(values)} for values in distinct]

    fields = []
    for index, header in enumerate(headers):
        if index in numeric:
            values = [float(row[index]) for row in rows] or [0.0]
            shared = SharedItems(containsSemiMixedTypes=False, containsString=False, containsNumber=True,
                                 minValue=min(values), maxValue=max(values))
        else:
            shared = SharedItems(_fields=[Text(v=value) for value in distinct[index]], count=len(distinct[index]))
        fields.append(CacheField(name=header, numFmtId=0, sharedItems=shared))

    records = RecordList(r=[Record(_fields=[Number(v=float(row[index])) if index in numeric
                                            else Index(v=position[index][str(row[index])])
                                            for index in range(len(headers))]) for row in rows])
    last_row = header_row + max(len(rows), 1)
    cache = CacheDefinition(
        refreshOnLoad=True, recordCount=len(rows), createdVersion=6, refreshedVersion=6, minRefreshableVersion=3,
        cacheSource=CacheSource(type="worksheet", worksheetSource=WorksheetSource(
            ref=f"A{header_row}:{get_column_letter(len(headers))}{last_row}", sheet=source.title)),
        cacheFields=fields)
    cache.records = records

    at = {header: index for index, header in enumerate(headers)}
    pivot_fields = []
    for index, header in enumerate(headers):
        if index in numeric:
            pivot_fields.append(PivotField(dataField=True, showAll=False))
            continue
        axis = ("axisRow" if header in row_fields else "axisCol" if header in column_fields
                else "axisPage" if header in page_fields else None)
        items = [FieldItem(x=item) for item in range(len(distinct[index]))] + [FieldItem(t="default")]
        pivot_fields.append(PivotField(axis=axis, showAll=False, items=items if axis else ()))

    pivot = TableDefinition(
        name=name, cacheId=1, dataCaption="Values", applyNumberFormats=False, applyBorderFormats=False,
        applyFontFormats=False, applyPatternFormats=False, applyAlignmentFormats=False,
        applyWidthHeightFormats=True, updatedVersion=6, minRefreshableVersion=3, createdVersion=6,
        useAutoFormatting=True, itemPrintTitles=True, indent=0, outline=True, outlineData=True,
        location=Location(ref=f"{top_left}:{top_left}", firstHeaderRow=1, firstDataRow=2, firstDataCol=1,
                          rowPageCount=len(page_fields) or None, colPageCount=1 if page_fields else None),
        pivotFields=pivot_fields,
        rowFields=[RowColField(x=at[header]) for header in row_fields],
        colFields=[RowColField(x=at[header]) for header in column_fields],
        pageFields=[PageField(fld=at[header], hier=-1) for header in page_fields],
        dataFields=[DataField(name=value_caption, fld=at[value_field], subtotal="sum",
                              numFmtId=WHOLE_NUMBER_FORMAT_ID)],
        pivotTableStyleInfo=PivotTableStyle(name="PivotStyleMedium2", showRowHeaders=True, showColHeaders=True,
                                            showRowStripes=False, showColStripes=False, showLastColumn=True))
    pivot.cache = cache
    target._pivots.append(pivot)
