"""File export helpers for tabular query results."""
from __future__ import annotations

import csv
import io
from typing import Any


def build_csv_text(columns: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        row_values = row if isinstance(row, list) else [row]
        writer.writerow(["" if value is None else value for value in row_values])
    return buffer.getvalue()


def build_xlsx_bytes(columns: list[str], rows: list[list[Any]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(columns)
    for row in rows:
        row_values = row if isinstance(row, list) else [row]
        ws.append(["" if value is None else value for value in row_values])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_pdf_bytes(columns: list[str], rows: list[list[Any]]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    table_data: list[list[Any]] = [columns]
    for row in rows:
        row_values = row if isinstance(row, list) else [row]
        table_data.append(["" if value is None else str(value) for value in row_values])

    if len(table_data) > 301:
        table_data = table_data[:301]

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    styles = getSampleStyleSheet()
    subtitle = Paragraph(
        "Generated from query result table. Large outputs are truncated to 300 rows.",
        styles["Normal"],
    )
    doc.build([subtitle, Spacer(1, 4 * mm), table])
    return buffer.getvalue()
