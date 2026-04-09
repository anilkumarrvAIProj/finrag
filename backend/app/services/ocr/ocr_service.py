"""
Phase 2: OCR + PDF Parser
- Detects native vs scanned PDFs
- pytesseract for scanned documents (lighter than PaddleOCR, no GPU needed)
- PyMuPDF + pdfplumber for native PDFs
- Layout-aware section/table extraction
- Metadata NER (fund name, dates, entities)
"""
import io
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedPage:
    page_num: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    section_titles: list[str] = field(default_factory=list)
    ocr_confidence: Optional[float] = None
    is_ocr: bool = False


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    page_count: int
    is_scanned: bool
    avg_ocr_confidence: Optional[float]
    detected_language: str
    fund_name: Optional[str]
    report_date: Optional[str]
    entities: dict
    full_text: str


def _is_scanned(pdf_bytes: bytes, sample_pages: int = 3) -> bool:
    """Detect if PDF is primarily scanned by checking text density."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    char_counts = []
    for i in range(min(sample_pages, len(doc))):
        text = doc[i].get_text("text")
        char_counts.append(len(text.strip()))
    doc.close()
    avg_chars = statistics.mean(char_counts) if char_counts else 0
    return avg_chars < 100


def _extract_tables_from_page(page) -> list[list[list[str]]]:
    tables = []
    for table in page.extract_tables():
        if table:
            normalized = [[str(cell) if cell else "" for cell in row] for row in table]
            tables.append(normalized)
    return tables


def _detect_sections(text: str) -> list[str]:
    lines = text.split("\n")
    sections = []
    for line in lines:
        line = line.strip()
        if 3 < len(line) < 80 and (line.isupper() or line.istitle()) and len(line.split()) < 10:
            sections.append(line)
    return sections


def _extract_fund_name(text: str) -> Optional[str]:
    patterns = [
        r"Fund(?:\s+Name)?[:\s]+([A-Z][A-Za-z\s&\-]+(?:Fund|Trust|Portfolio))",
        r"([A-Z][A-Za-z\s&\-]+(?:Fund|Trust|ETF|Portfolio))\s+(?:Fact Sheet|Report|Summary)",
        r"^([A-Z][A-Za-z\s&\-]{5,50}(?:Fund|Portfolio|Trust))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:2000], re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _extract_report_date(text: str) -> Optional[str]:
    date_patterns = [
        r"(?:As of|Date|Report Date|Period Ending)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(?:As of|Date|Report Date|Period Ending)[:\s]+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})",
        r"(\d{4}[-/]\d{2}[-/]\d{2})",
        r"(Q[1-4]\s+\d{4})",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text[:3000], re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def parse_pdf(pdf_bytes: bytes) -> ParsedDocument:
    """Main parsing entry point — routes to OCR or native extraction."""
    scanned = _is_scanned(pdf_bytes)
    logger.info("PDF analysis", is_scanned=scanned, size_kb=len(pdf_bytes) // 1024)
    if scanned:
        return _parse_scanned(pdf_bytes)
    return _parse_native(pdf_bytes)


def _parse_native(pdf_bytes: bytes) -> ParsedDocument:
    """Parse native text-based PDF with pdfplumber + PyMuPDF."""
    pages = []
    fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, (fitz_page, plumber_page) in enumerate(zip(fitz_doc, pdf.pages)):
            text = fitz_page.get_text("text") or ""
            tables = _extract_tables_from_page(plumber_page)
            sections = _detect_sections(text)
            pages.append(ParsedPage(
                page_num=page_num + 1,
                text=text,
                tables=tables,
                section_titles=sections,
                is_ocr=False,
            ))

    fitz_doc.close()
    full_text = "\n".join(p.text for p in pages)

    return ParsedDocument(
        pages=pages,
        page_count=len(pages),
        is_scanned=False,
        avg_ocr_confidence=None,
        detected_language="en",
        fund_name=_extract_fund_name(full_text),
        report_date=_extract_report_date(full_text),
        entities={},
        full_text=full_text,
    )


def _parse_scanned(pdf_bytes: bytes) -> ParsedDocument:
    """Parse scanned PDF using pytesseract (CPU-based, no GPU needed)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.error("pytesseract not installed — cannot process scanned PDF")
        raise RuntimeError("pytesseract required for scanned PDFs")

    fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    confidence_scores = []

    for page_num in range(len(fitz_doc)):
        fitz_page = fitz_doc[page_num]
        # Render at 200 DPI
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = fitz_page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Get text + confidence data
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words = [w for w in data["text"] if w.strip()]
            confs = [c for c, w in zip(data["conf"], data["text"]) if w.strip() and c != -1]
            page_text = pytesseract.image_to_string(img)
            avg_conf = (sum(confs) / len(confs) / 100) if confs else 0.0
        except Exception as exc:
            logger.warning("Tesseract failed on page", page=page_num + 1, error=str(exc))
            page_text = ""
            avg_conf = 0.0

        confidence_scores.append(avg_conf)

        if avg_conf < settings.ocr_confidence_threshold and avg_conf > 0:
            logger.warning("Low OCR confidence", page=page_num + 1, confidence=round(avg_conf, 3))

        pages.append(ParsedPage(
            page_num=page_num + 1,
            text=page_text,
            tables=[],
            section_titles=_detect_sections(page_text),
            ocr_confidence=avg_conf,
            is_ocr=True,
        ))

    fitz_doc.close()
    full_text = "\n".join(p.text for p in pages)
    avg_conf = statistics.mean(confidence_scores) if confidence_scores else 0.0

    return ParsedDocument(
        pages=pages,
        page_count=len(pages),
        is_scanned=True,
        avg_ocr_confidence=avg_conf,
        detected_language="en",
        fund_name=_extract_fund_name(full_text),
        report_date=_extract_report_date(full_text),
        entities={},
        full_text=full_text,
    )
