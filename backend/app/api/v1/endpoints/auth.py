"""Auth endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, get_admin_user, TokenPayload
from app.core.config import settings
from app.db.session import get_db
from app.models.models import User, UserRole, AuditAction
from app.schemas.schemas import UserOut, UserRoleUpdate, MessageResponse
from app.services.audit_service import write_audit_log
from jose import jwt
from datetime import datetime, timedelta

router = APIRouter()


@router.post("/dev-token", summary="Dev-mode JWT (non-production only)")
async def dev_token(role: str = "admin", email: str = "dev@finrag.local"):
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Not available in production")
    payload = {
        "sub": f"dev|{uuid.uuid4().hex[:12]}",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "roles": [role],
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=8),
    }
    token = jwt.encode(payload, settings.app_secret_key, algorithm="HS256")
    return {"access_token": token, "token_type": "Bearer", "expires_in": 28800}


@router.get("/me")
async def me(current_user: TokenPayload = Depends(get_current_user)):
    return {
        "sub": current_user.sub,
        "email": current_user.email,
        "roles": [r.value for r in current_user.roles],
        "tenant_id": current_user.tenant_id,
    }
