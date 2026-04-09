"""
Celery Pipeline Tasks
=====================
Pipeline stages per document:
  1. Download from S3
  2. OCR / parse (PDF or text)
  3. Semantic chunking
  4. Embedding + Weaviate indexing
  5a. Structured data extraction → PostgreSQL (LLM-based, for PDFs/PPTs)
  5b. Excel RDBMS mapping → PostgreSQL (LLM schema detection, for Excel files)
"""
import uuid
import asyncio
from datetime import datetime, timedelta

from celery import Celery
from celery.utils.log import get_task_logger

from app.core.config import settings

celery_app = Celery(
    "finrag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.tasks.run_ingestion_pipeline": {"queue": "ingestion"},
        "app.workers.tasks.reprocess_document": {"queue": "ingestion"},
    },
    beat_schedule={
        "cleanup-failed-tasks": {
            "task": "app.workers.tasks.cleanup_stale_tasks",
            "schedule": 3600,
        },
    },
)

logger = get_task_logger(__name__)


def _get_sync_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(settings.sync_database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def _update_doc_status(doc_id: str, status: str, **kwargs):
    from app.models.models import Document
    db = _get_sync_db()
    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
        if doc:
            doc.status = status
            for k, v in kwargs.items():
                setattr(doc, k, v)
            db.commit()
    finally:
        db.close()


def _run_async(coro):
    """Run an async coroutine safely from sync Celery context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_ingestion_pipeline(self, doc_id: str, tenant_id: str):
    logger.info("Pipeline started", extra={"doc_id": doc_id})
    try:
        _update_doc_status(doc_id, "ocr_processing", processing_started_at=datetime.utcnow())

        # ── Step 1: Load document metadata ────────────────────────────────────
        from app.models.models import Document
        db = _get_sync_db()
        doc = db.query(Document).filter(Document.id == uuid.UUID(doc_id)).first()
        if not doc:
            logger.error("Document not found", extra={"doc_id": doc_id})
            return
        s3_key = doc.s3_raw_key
        weaviate_ns = doc.weaviate_namespace or ""
        filename = doc.filename
        doc_type = doc.doc_type
        db.close()

        is_excel_file = s3_key.endswith(".txt") and any(
            filename.lower().endswith(ext) for ext in [".xlsx", ".xls", ".xlsm"]
        ) or s3_key.endswith(".txt")

        # ── Step 2: Download from S3 ───────────────────────────────────────────
        from app.services.ingestion.s3_client import S3Client
        s3 = S3Client()
        raw_bytes = _run_async(s3.download(settings.s3_bucket_raw, s3_key))
        logger.info("Downloaded from S3", extra={"doc_id": doc_id, "size_kb": len(raw_bytes) // 1024})

        # ── Step 3: Parse ─────────────────────────────────────────────────────
        _update_doc_status(doc_id, "parsing")

        if s3_key.endswith(".txt"):
            # Excel was pre-parsed to text
            from app.services.ocr.ocr_service import ParsedDocument, ParsedPage, _extract_fund_name, _extract_report_date
            text_content = raw_bytes.decode("utf-8")
            page = ParsedPage(page_num=1, text=text_content, tables=[], section_titles=[], is_ocr=False)
            parsed = ParsedDocument(
                pages=[page], page_count=1, is_scanned=False,
                avg_ocr_confidence=None, detected_language="en",
                fund_name=_extract_fund_name(text_content),
                report_date=_extract_report_date(text_content),
                entities={}, full_text=text_content,
            )
        else:
            from app.services.ocr.ocr_service import parse_pdf
            parsed = parse_pdf(raw_bytes)

        _update_doc_status(doc_id, "embedding",
            page_count=parsed.page_count,
            is_scanned=parsed.is_scanned,
            ocr_confidence=parsed.avg_ocr_confidence,
            fund_name=parsed.fund_name,
        )

        # ── Step 4: Chunk → Embed → Index ─────────────────────────────────────
        from app.services.embedding.chunker import chunk_document
        from app.services.embedding.embedding_service import embed_texts
        from app.services.embedding.weaviate_client import upsert_chunks

        chunks = chunk_document(parsed, doc_id)
        logger.info("Chunked", extra={"doc_id": doc_id, "chunks": len(chunks)})

        texts = [c.content for c in chunks]
        embeddings = _run_async(embed_texts(texts))

        chunk_dicts = [
            {
                "tenant_id": tenant_id,
                "namespace": weaviate_ns,
                "document_id": doc_id,
                "chunk_id": str(uuid.uuid4()),
                "content": c.content,
                "chunk_type": c.chunk_type,
                "section_title": c.section_title or "",
                "page_start": c.page_start,
                "page_end": c.page_end,
                "doc_type": doc_type or "other",
                "fund_name": parsed.fund_name or "",
                "report_date": parsed.report_date or "",
                "filename": filename,
                "token_count": c.token_count,
            }
            for c in chunks
        ]

        weaviate_ids = upsert_chunks(chunk_dicts, embeddings)

        # Save chunk records to PostgreSQL
        from app.models.models import DocumentChunk
        db = _get_sync_db()
        try:
            for i, (chunk, wid) in enumerate(zip(chunks, weaviate_ids)):
                db.add(DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=uuid.UUID(doc_id),
                    tenant_id=uuid.UUID(tenant_id),
                    chunk_index=i,
                    content=chunk.content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section_title=chunk.section_title,
                    chunk_type=chunk.chunk_type,
                    token_count=chunk.token_count,
                    weaviate_id=wid,
                ))
            db.commit()
        finally:
            db.close()

        _update_doc_status(doc_id, "indexed",
            chunk_count=len(chunks),
            processing_completed_at=datetime.utcnow(),
        )
        logger.info("Indexed in Weaviate", extra={"doc_id": doc_id, "chunks": len(chunks)})

        # ── Step 5: Structured data → PostgreSQL ──────────────────────────────
        try:
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AsyncSess

            if is_excel_file:
                # Excel: use LLM-assisted RDBMS mapper for all sheets
                logger.info("Running Excel RDBMS mapper", extra={"doc_id": doc_id})
                from app.services.ingestion.excel_rdbms_mapper import map_excel_to_rdbms

                # Re-download original Excel bytes if available, else use text
                # For now use the text-parsed content for schema detection
                async def _excel_map():
                    async_engine = create_async_engine(settings.database_url)
                    async with AsyncSess(async_engine) as async_db:
                        # Pass raw_bytes as placeholder — mapper uses text for schema detection
                        result = await map_excel_to_rdbms(
                            raw_bytes, filename, doc_id, tenant_id, async_db, settings
                        )
                        await async_db.commit()
                        return result

                result = _run_async(_excel_map())
                logger.info("Excel mapped to RDBMS", extra={"doc_id": doc_id, "result": result})

            else:
                # PDF/PPT: use LLM text extraction for structured fields
                from app.services.ingestion.structured_extractor import extract_structured_data, save_structured_data

                extracted = _run_async(extract_structured_data(parsed.full_text, doc_id))

                if extracted:
                    async def _save_structured():
                        async_engine = create_async_engine(settings.database_url)
                        async with AsyncSess(async_engine) as async_db:
                            await save_structured_data(extracted, doc_id, tenant_id, async_db)
                            await async_db.commit()

                    _run_async(_save_structured())
                    logger.info("Structured data saved", extra={
                        "doc_id": doc_id,
                        "fund": extracted.get("fund_name"),
                    })

        except Exception as exc:
            # Structured extraction failure is non-fatal
            logger.warning("Structured extraction skipped", extra={"doc_id": doc_id, "error": str(exc)})

        logger.info("Pipeline complete", extra={"doc_id": doc_id})

    except Exception as exc:
        logger.error("Pipeline failed", extra={"doc_id": doc_id, "error": str(exc)})
        _update_doc_status(doc_id, "failed", error_message=str(exc)[:1000])
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2)
def reprocess_document(self, doc_id: str, tenant_id: str, force_ocr: bool = False):
    from app.services.embedding.weaviate_client import delete_by_document
    from app.models.models import DocumentChunk
    delete_by_document(doc_id, tenant_id)
    db = _get_sync_db()
    try:
        db.query(DocumentChunk).filter(DocumentChunk.document_id == uuid.UUID(doc_id)).delete()
        db.commit()
    finally:
        db.close()
    run_ingestion_pipeline.apply_async(args=[doc_id, tenant_id], queue="ingestion")


@celery_app.task
def cleanup_stale_tasks():
    from app.models.models import Document
    from sqlalchemy import and_
    db = _get_sync_db()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=2)
        stale = db.query(Document).filter(
            and_(
                Document.status.in_(["ocr_processing", "parsing", "embedding", "queued"]),
                Document.processing_started_at < cutoff,
            )
        ).all()
        for doc in stale:
            doc.status = "failed"
            doc.error_message = "Timeout: exceeded 2 hours"
        db.commit()
    finally:
        db.close()
