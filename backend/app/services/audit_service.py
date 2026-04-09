"""Audit Service with HMAC chain."""
import hashlib
import hmac as hmac_module
import json
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import AuditLog, AuditAction
from app.core.logging import get_logger

logger = get_logger(__name__)


def _compute_hmac(prev_hash: str, record: dict) -> str:
    canonical = json.dumps(record, sort_keys=True, default=str)
    message = (prev_hash + canonical).encode()
    return hmac_module.new(
        settings.app_secret_key.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


async def write_audit_log(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: AuditAction,
    user_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
) -> AuditLog:
    try:
        result = await db.execute(
            select(AuditLog.hmac_chain)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(desc(AuditLog.created_at))
            .limit(1)
        )
        prev_hash = result.scalar_one_or_none() or "genesis"
    except Exception:
        prev_hash = "genesis"

    record_data = {
        "tenant_id": str(tenant_id),
        "user_id": str(user_id) if user_id else None,
        "action": action.value,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }
    chain_hash = _compute_hmac(prev_hash, record_data)

    entry = AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
        hmac_chain=chain_hash,
    )
    db.add(entry)
    await db.flush()
    return entry


async def verify_audit_chain(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 1000):
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at)
        .limit(limit)
    )
    logs = result.scalars().all()
    prev_hash = "genesis"
    for log in logs:
        record_data = {
            "tenant_id": str(log.tenant_id),
            "user_id": str(log.user_id) if log.user_id else None,
            "action": log.action.value,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "timestamp": log.created_at.isoformat(),
        }
        expected = _compute_hmac(prev_hash, record_data)
        if expected != log.hmac_chain:
            return False, str(log.id)
        prev_hash = log.hmac_chain
    return True, None
