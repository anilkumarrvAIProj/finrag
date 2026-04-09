"""
Native Excel Parser
Reads XLSX/XLS directly using openpyxl to preserve table structure,
then converts to well-formatted text for chunking.
Much better than PDF conversion for tabular financial data.
"""
import io
from pathlib import Path
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


def excel_to_text(file_bytes: bytes, filename: str) -> str:
    """
    Convert Excel file to structured text preserving table relationships.
    Each sheet becomes a clearly labelled section.
    """
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl not installed, falling back to PDF conversion")
        return ""

    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes),
            read_only=True,
            data_only=True,   # get computed values not formulas
        )
    except Exception as exc:
        logger.warning("openpyxl failed to open file", error=str(exc))
        return ""

    sections = []
    sections.append(f"Document: {filename}\n")

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Collect all rows with data
        rows = []
        for row in ws.iter_rows(values_only=True):
            # Skip completely empty rows
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            rows.append(row)

        if not rows:
            continue

        sections.append(f"\n=== Sheet: {sheet_name} ===\n")

        # Find max columns with data
        max_cols = max(len([c for c in row if c is not None]) for row in rows) if rows else 0

        # Format as Markdown table
        if rows:
            # Use first non-empty row as header
            header = rows[0]
            header_cells = [str(c) if c is not None else "" for c in header]
            sections.append("| " + " | ".join(header_cells) + " |")
            sections.append("|" + "|".join(["---"] * len(header_cells)) + "|")

            # Data rows
            for row in rows[1:]:
                cells = [str(c) if c is not None else "" for c in row]
                # Pad to header length
                while len(cells) < len(header_cells):
                    cells.append("")
                sections.append("| " + " | ".join(cells) + " |")

        sections.append("")

    wb.close()
    result = "\n".join(sections)
    logger.info("Excel parsed natively", filename=filename, sheets=len(wb.sheetnames), chars=len(result))
    return result


def is_excel(filename: str) -> bool:
    return Path(filename).suffix.lower() in {".xlsx", ".xls", ".xlsm"}
