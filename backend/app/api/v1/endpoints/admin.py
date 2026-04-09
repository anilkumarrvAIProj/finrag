"""Admin API endpoints."""
import uuid
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_admin_user, TokenPayload
from app.db.session import get_db
from app.models.models import AuditLog, Document, DocumentStatus, AuditAction
from app.schemas.schemas import AuditLogEntry, AuditLogResponse, PipelineHealthResponse, MessageResponse
from app.services.audit_service import verify_audit_chain

router = APIRouter()
DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.get("/health", response_model=PipelineHealthResponse)
async def pipeline_health(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    health: dict = {"status": "healthy", "workers": {}, "queue_depths": {}, "database": "unknown", "vector_store": "unknown", "cache": "unknown"}

    try:
        await db.execute(select(func.now()))
        health["database"] = "ok"
    except Exception as exc:
        health["database"] = f"error: {exc}"
        health["status"] = "degraded"

    try:
        r = await aioredis.from_url(settings.redis_url)
        await r.ping()
        health["cache"] = "ok"
        for queue in ["ingestion", "ocr", "embedding"]:
            depth = await r.llen(f"celery:{queue}")
            health["queue_depths"][queue] = depth
        await r.aclose()
    except Exception as exc:
        health["cache"] = f"error: {exc}"
        health["status"] = "degraded"

    try:
        from app.services.embedding.weaviate_client import _get_client, WEAVIATE_CLASS
        with _get_client() as client:
            health["vector_store"] = "ok" if client.collections.exists(WEAVIATE_CLASS) else "schema missing"
    except Exception as exc:
        health["vector_store"] = f"error: {exc}"

    return PipelineHealthResponse(**health)


@router.get("/audit-logs", response_model=AuditLogResponse)
async def list_audit_logs(
    action: Optional[str] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    filters = [AuditLog.tenant_id == DEFAULT_TENANT]
    if action:
        filters.append(AuditLog.action == AuditAction(action))
    if user_id:
        filters.append(AuditLog.user_id == user_id)
    if date_from:
        filters.append(AuditLog.created_at >= date_from)
    if date_to:
        filters.append(AuditLog.created_at <= date_to)

    total_q = await db.execute(select(func.count()).select_from(AuditLog).where(and_(*filters)))
    total = total_q.scalar_one()

    result = await db.execute(
        select(AuditLog).where(and_(*filters))
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    return AuditLogResponse(items=[AuditLogEntry.model_validate(l) for l in result.scalars().all()], total=total)


@router.post("/audit-logs/verify")
async def verify_audit(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    is_valid, broken_id = await verify_audit_chain(db, DEFAULT_TENANT)
    return {"chain_valid": is_valid, "first_broken_record_id": broken_id,
            "message": "Audit chain integrity verified" if is_valid else "Chain broken"}


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    total = await db.execute(select(func.count()).select_from(Document).where(Document.tenant_id == DEFAULT_TENANT, Document.is_latest == True))
    indexed = await db.execute(select(func.count()).select_from(Document).where(Document.tenant_id == DEFAULT_TENANT, Document.status == "indexed", Document.is_latest == True))
    failed = await db.execute(select(func.count()).select_from(Document).where(Document.tenant_id == DEFAULT_TENANT, Document.status == "failed"))
    return {"documents": {"total": total.scalar_one(), "indexed": indexed.scalar_one(), "failed": failed.scalar_one()}}
