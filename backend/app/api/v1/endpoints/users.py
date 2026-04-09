"""Users endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_admin_user, TokenPayload
from app.db.session import get_db
from app.models.models import User, UserRole, AuditAction
from app.schemas.schemas import UserOut, UserRoleUpdate, MessageResponse
from app.services.audit_service import write_audit_log

router = APIRouter()
DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.tenant_id == DEFAULT_TENANT).limit(200))
    return [UserOut.model_validate(u) for u in result.scalars().all()]


@router.patch("/{user_id}/role", response_model=MessageResponse)
async def update_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role.value
    user.role = UserRole(body.role)
    await write_audit_log(db=db, tenant_id=user.tenant_id, action=AuditAction.ROLE_CHANGE,
                          resource_type="user", resource_id=str(user_id),
                          details={"old_role": old_role, "new_role": body.role})
    return MessageResponse(message=f"Role updated to {body.role}")


@router.delete("/{user_id}", response_model=MessageResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    return MessageResponse(message="User deactivated")
