"""
Ingestion Service
- PDF: direct pipeline
- DOCX/PPTX: convert to PDF via LibreOffice
- XLSX/XLS: parse natively with openpyxl (preserves table structure)
File type detected by EXTENSION not MIME (Windows sends octet-stream).
"""
import hashlib
import io
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.models import Document, DocumentType
from app.services.ingestion.s3_client import S3Client
from app.services.ingestion.converter import convert_to_pdf, get_pdf_filename
from app.services.ingestion.excel_parser import excel_to_text, is_excel
from app.workers.tasks import run_ingestion_pipeline

logger = get_logger(__name__)
s3 = S3Client()

EXT_TO_MIME = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":  "application/vnd.ms-excel",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt":  "application/vnd.ms-powerpoint",
}

OFFICE_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}


class IngestionService:

    @staticmethod
    def _compute_sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _classify_doc_type(filename: str) -> DocumentType:
        name = filename.lower()
        if any(k in name for k in ["fact", "factsheet"]):
            return DocumentType.FACT_SHEET
        if any(k in name for k in ["investment", "inv_report"]):
            return DocumentType.INVESTMENT_REPORT
        if any(k in name for k in ["quarterly", "q1", "q2", "q3", "q4"]):
            return DocumentType.QUARTERLY_REPORT
        if any(k in name for k in ["personnel", "people", "staff", "hr"]):
            return DocumentType.PERSONNEL
        if any(k in name for k in ["portfolio", "summary"]):
            return DocumentType.PORTFOLIO_SUMMARY
        return DocumentType.OTHER

    async def ingest(
        self,
        file: UploadFile,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        db: AsyncSession,
        doc_type: Optional[DocumentType] = None,
        fund_id: Optional[uuid.UUID] = None,
        parent_id: Optional[uuid.UUID] = None,
    ) -> Document:

        data = await file.read()
        original_filename = file.filename or f"upload_{uuid.uuid4()}.pdf"

        # Size check
        size_mb = len(data) / (1024 * 1024)
        if size_mb > settings.max_upload_size_mb:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.max_upload_size_mb}MB limit",
            )

        # Detect type from extension
        ext = Path(original_filename).suffix.lower()
        mime = EXT_TO_MIME.get(ext)
        if mime is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type: '{ext}'. Supported: PDF, DOCX, XLSX, PPTX",
            )

        # ── Excel: parse natively, store as text file ─────────────────────────
        excel_text = None
        if is_excel(original_filename):
            logger.info("Excel file detected — parsing natively", filename=original_filename)
            excel_text = excel_to_text(data, original_filename)
            if excel_text:
                logger.info("Excel parsed natively", chars=len(excel_text))
                # Store original excel bytes in S3, but pipeline will use excel_text
            else:
                logger.warning("Native Excel parse failed, falling back to PDF conversion")

        # ── Convert Office files → PDF (for non-Excel or Excel fallback) ──────
        if mime in OFFICE_MIMES and not (is_excel(original_filename) and excel_text):
            logger.info("Converting to PDF via LibreOffice", filename=original_filename)
            try:
                data = convert_to_pdf(data, mime, original_filename)
                original_filename = get_pdf_filename(original_filename)
                mime = "application/pdf"
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"File conversion failed: {exc}",
                )

        # Dedup
        sha = self._compute_sha256(data)
        existing = await db.execute(
            select(Document).where(
                Document.sha256_hash == sha,
                Document.tenant_id == tenant_id,
                Document.is_latest == True,
            )
        )
        if doc := existing.scalar_one_or_none():
            logger.info("Duplicate upload", sha=sha[:16])
            return doc

        # Versioning
        version = 1
        if parent_id:
            result = await db.execute(
                select(Document).where(Document.id == parent_id, Document.tenant_id == tenant_id)
            )
            if parent := result.scalar_one_or_none():
                parent.is_latest = False
                version = parent.version + 1

        # Upload to S3 — for Excel, store the text content; otherwise store PDF
        s3_key = f"{tenant_id}/raw/{uuid.uuid4()}/{original_filename}"
        if is_excel(file.filename or "") and excel_text:
            # Store as text for the pipeline to process
            upload_data = excel_text.encode("utf-8")
            s3_key = s3_key.replace(".xlsx", ".txt").replace(".xls", ".txt").replace(".xlsm", ".txt")
            content_type = "text/plain"
        else:
            upload_data = data
            content_type = "application/pdf"

        await s3.upload(
            bucket=settings.s3_bucket_raw,
            key=s3_key,
            data=io.BytesIO(upload_data),
            content_type=content_type,
        )

        # Create DB record
        resolved_type = doc_type or self._classify_doc_type(original_filename)
        doc = Document(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            uploaded_by=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            filename=original_filename,
            sha256_hash=sha,
            doc_type=resolved_type.value if hasattr(resolved_type, "value") else str(resolved_type),
            status="queued",
            version=version,
            is_latest=True,
            parent_id=parent_id,
            s3_raw_key=s3_key,
            file_size_bytes=len(upload_data),
            weaviate_namespace=f"{tenant_id}__{resolved_type.value if hasattr(resolved_type, 'value') else resolved_type}",
        )
        db.add(doc)
        await db.flush()

        run_ingestion_pipeline.apply_async(
            args=[str(doc.id), str(tenant_id)],
            queue="ingestion",
        )
        logger.info("Ingestion queued", doc_id=str(doc.id), filename=original_filename)
        return doc

    async def bulk_ingest(self, files, tenant_id, user_id, db):
        results = []
        for file in files:
            try:
                doc = await self.ingest(file, tenant_id, user_id, db)
                results.append(doc)
            except HTTPException as exc:
                logger.warning("Bulk ingest failed", filename=file.filename, error=exc.detail)
        return results
