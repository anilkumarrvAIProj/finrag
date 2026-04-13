"""Documents API endpoints."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, get_admin_user, TokenPayload
from app.db.session import get_db
from app.models.models import Document, DocumentStatus, DocumentType, AuditAction
from app.schemas.schemas import (
    DocStatusEnum, DocTypeEnum,
    DocumentDetail, DocumentListResponse,
    DocumentReprocessRequest, DocumentUploadResponse,
    MessageResponse,
)
from app.services.ingestion.ingestion_service import IngestionService
from app.services.ingestion.s3_client import S3Client
from app.services.audit_service import write_audit_log
from app.workers.tasks import reprocess_document

router = APIRouter()
ingestion = IngestionService()
s3 = S3Client()

DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: Optional[DocTypeEnum] = Form(None),
    fund_id: Optional[uuid.UUID] = Form(None),
    parent_id: Optional[uuid.UUID] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    doc = await ingestion.ingest(
        file=file,
        tenant_id=DEFAULT_TENANT,
        user_id=uuid.UUID(current_user.sub),
        db=db,
        doc_type=DocumentType(doc_type.value) if doc_type else None,
        fund_id=fund_id,
        parent_id=parent_id,
    )
    await write_audit_log(
        db=db, tenant_id=doc.tenant_id, action=AuditAction.UPLOAD,
        resource_type="document", resource_id=str(doc.id),
        ip_address=request.client.host if request.client else None,
        details={"filename": doc.filename, "size_bytes": doc.file_size_bytes},
    )
    return DocumentUploadResponse.model_validate(doc)


@router.post("/bulk-upload", response_model=list[DocumentUploadResponse], status_code=status.HTTP_202_ACCEPTED)
async def bulk_upload(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Max 500 files per batch")
    docs = await ingestion.bulk_ingest(files, DEFAULT_TENANT, uuid.uuid4(), db)
    return [DocumentUploadResponse.model_validate(d) for d in docs]


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_filter: Optional[DocStatusEnum] = Query(None, alias="status"),
    doc_type: Optional[DocTypeEnum] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    filters = [Document.tenant_id == DEFAULT_TENANT, Document.is_latest == True]
    if status_filter:
        filters.append(Document.status == status_filter.value)
    if doc_type:
        filters.append(Document.doc_type == doc_type.value)
    if search:
        filters.append(Document.filename.ilike(f"%{search}%"))

    total_q = await db.execute(select(func.count()).select_from(Document).where(and_(*filters)))
    total = total_q.scalar_one()

    result = await db.execute(
        select(Document).where(and_(*filters))
        .order_by(Document.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    docs = result.scalars().all()
    return DocumentListResponse(
        items=[DocumentDetail.model_validate(d) for d in docs],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == DEFAULT_TENANT)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail.model_validate(doc)


@router.post("/{doc_id}/reprocess", response_model=MessageResponse)
async def reprocess(
    doc_id: uuid.UUID,
    body: DocumentReprocessRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == DEFAULT_TENANT)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    reprocess_document.apply_async(args=[str(doc_id), str(DEFAULT_TENANT), body.force_ocr], queue="ingestion")
    await write_audit_log(
        db=db, tenant_id=DEFAULT_TENANT, action=AuditAction.REPROCESS,
        resource_type="document", resource_id=str(doc_id),
        ip_address=request.client.host if request.client else None,
    )
    return MessageResponse(message="Reprocessing initiated")


@router.delete("/{doc_id}", response_model=MessageResponse)
async def delete_document(
    doc_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == DEFAULT_TENANT)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from app.services.embedding.weaviate_client import delete_by_document
    delete_by_document(str(doc_id), str(DEFAULT_TENANT))
    doc.is_latest = False
    doc.status = "failed"
    await write_audit_log(
        db=db, tenant_id=DEFAULT_TENANT, action=AuditAction.DELETE,
        resource_type="document", resource_id=str(doc_id),
        ip_address=request.client.host if request.client else None,
    )
    return MessageResponse(message="Document deleted")


@router.get("/{doc_id}/download")
async def get_download_url(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    from app.core.config import settings
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == DEFAULT_TENANT)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    url = await s3.get_presigned_url(settings.s3_bucket_raw, doc.s3_raw_key)
    return {"url": url, "expires_in_seconds": 3600}
