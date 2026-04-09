"""
File Conversion Service
Converts DOCX, XLSX, PPTX → PDF using LibreOffice headless.
All conversion happens transparently before the PDF pipeline runs.

Supported input formats:
  - .docx / .doc   (Word)
  - .xlsx / .xls   (Excel)
  - .pptx / .ppt   (PowerPoint)
  - .pdf           (pass-through, no conversion needed)
"""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

# MIME type → file extension mapping
MIME_TO_EXT = {
    "application/pdf": ".pdf",
    # Word
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    # PowerPoint
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-powerpoint": ".ppt",
}

SUPPORTED_MIMES = set(MIME_TO_EXT.keys())

# Extension → friendly name for logging
EXT_LABELS = {
    ".docx": "Word", ".doc": "Word",
    ".xlsx": "Excel", ".xls": "Excel",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
    ".pdf": "PDF",
}


def needs_conversion(mime_type: str) -> bool:
    """Return True if file needs converting to PDF."""
    return mime_type != "application/pdf" and mime_type in SUPPORTED_MIMES


def convert_to_pdf(file_bytes: bytes, mime_type: str, original_filename: str) -> bytes:
    """
    Convert file bytes to PDF using LibreOffice headless.
    Returns PDF bytes. Raises RuntimeError on failure.
    
    LibreOffice command:
      libreoffice --headless --convert-to pdf --outdir /tmp/out /tmp/input.docx
    """
    ext = MIME_TO_EXT.get(mime_type, ".bin")
    label = EXT_LABELS.get(ext, "Unknown")

    logger.info(
        "Converting file to PDF",
        filename=original_filename,
        format=label,
        size_kb=len(file_bytes) // 1024,
    )

    # Work in a temp directory — LibreOffice needs real files on disk
    with tempfile.TemporaryDirectory(prefix="finrag_conv_") as tmpdir:
        input_path = Path(tmpdir) / f"input{ext}"
        output_dir = Path(tmpdir) / "out"
        output_dir.mkdir()

        # Write input file
        input_path.write_bytes(file_bytes)

        # Run LibreOffice conversion
        cmd = [
            "libreoffice",
            "--headless",
            "--norestore",
            "--nofirststartwizard",
            "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(input_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,   # 2 minute timeout
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Conversion timed out for {original_filename}")
        except FileNotFoundError:
            raise RuntimeError(
                "LibreOffice not found. Ensure it is installed in the Docker image."
            )

        if result.returncode != 0:
            logger.error(
                "LibreOffice conversion failed",
                returncode=result.returncode,
                stderr=result.stderr[:500],
            )
            raise RuntimeError(
                f"LibreOffice failed (exit {result.returncode}): {result.stderr[:200]}"
            )

        # Find the output PDF
        pdf_files = list(output_dir.glob("*.pdf"))
        if not pdf_files:
            raise RuntimeError(
                f"LibreOffice ran successfully but produced no PDF for {original_filename}"
            )

        pdf_bytes = pdf_files[0].read_bytes()
        logger.info(
            "Conversion complete",
            filename=original_filename,
            format=label,
            pdf_size_kb=len(pdf_bytes) // 1024,
        )
        return pdf_bytes


def get_pdf_filename(original_filename: str) -> str:
    """Return the filename with .pdf extension."""
    stem = Path(original_filename).stem
    return f"{stem}.pdf"
