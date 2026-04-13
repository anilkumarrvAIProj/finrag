"""
Auth API
========
POST /auth/register  — create new user account
POST /auth/login     — email + password → access + refresh tokens
POST /auth/refresh   — refresh token → new access token
POST /auth/logout    — invalidate session (client deletes tokens)
GET  /auth/me        — current user profile
POST /auth/dev-token — dev mode only
PATCH /auth/password — change own password
"""
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_admin_user, TokenPayload
from app.db.session import get_db
from app.models.models import User, Tenant, AuditAction
from app.services.auth_service import (
    authenticate_user, register_user,
    create_access_token, create_refresh_token,
    refresh_access_token, hash_password, verify_password,
    set_rls_context,
)
from app.services.audit_service import write_audit_log
from jose import jwt

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_slug: str = "default"


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str
    tenant_slug: str = "default"
    role: str = "read_only"
    invite_code: str = ""  # optional invite code for self-registration

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(body.email, body.password, body.tenant_slug, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)

    await write_audit_log(
        db=db, tenant_id=user.tenant_id, action=AuditAction.LOGIN,
        user_id=user.id, resource_type="user", resource_id=str(user.id),
        ip_address=request.client.host if request.client else None,
        details={"email": user.email, "role": user.role},
    )
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=60 * 60 * 8,
        user={
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
        },
    )


@router.post("/register")
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Self-registration. In production, restrict by invite code or
    require admin to create users via /users endpoint.
    """
    # Find tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == body.tenant_slug, Tenant.is_active == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # In production, only allow admin-created users
    if settings.is_production and body.invite_code != settings.app_secret_key[:8]:
        raise HTTPException(
            status_code=403,
            detail="Self-registration is disabled. Contact your administrator.",
        )

    user = await register_user(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        tenant_id=tenant.id,
        role=body.role if not settings.is_production else "read_only",
        db=db,
    )

    await write_audit_log(
        db=db, tenant_id=tenant.id, action=AuditAction.REGISTER,
        user_id=user.id, resource_type="user", resource_id=str(user.id),
        ip_address=request.client.host if request.client else None,
        details={"email": user.email, "role": user.role},
    )
    await db.commit()

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=60 * 60 * 8,
        user={
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
        },
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    result = await refresh_access_token(body.refresh_token, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please log in again.",
        )
    return result


@router.post("/logout")
async def logout(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Client should delete tokens. Server logs the event."""
    await write_audit_log(
        db=db,
        tenant_id=uuid.UUID(current_user.tenant_id),
        action=AuditAction.LOGOUT,
        user_id=uuid.UUID(current_user.sub),
        resource_type="user",
        resource_id=current_user.sub,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me")
async def me(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(current_user.sub))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "tenant_id": str(user.tenant_id),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.patch("/password")
async def change_password(
    body: PasswordChangeRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(current_user.sub))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, user.password_hash or ""):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"message": "Password changed successfully"}


@router.post("/dev-token", summary="Dev-mode JWT (non-production only)")
async def dev_token(
    role: str = "admin",
    email: str = "dev@finrag.local",
    db: AsyncSession = Depends(get_db),
):
    """Issues a dev token tied to the default admin user."""
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Not available in production")

    # Return a token for the default admin user
    result = await db.execute(
        select(User).where(User.email == "admin@finrag.local")
    )
    user = result.scalar_one_or_none()

    if user:
        # Use real user for proper audit trail
        access_token = create_access_token(user)
        refresh_token = create_refresh_token(user)
    else:
        # Fallback: generate token without DB user
        payload = {
            "sub": "00000000-0000-0000-0000-000000000002",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "roles": [role],
            "email": email,
            "type": "access",
            "exp": datetime.utcnow() + timedelta(hours=8),
        }
        access_token = jwt.encode(payload, settings.app_secret_key, algorithm="HS256")
        refresh_token = access_token  # same for dev

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 28800,
    }


@router.post("/admin/create-user", summary="Admin creates a user")
async def admin_create_user(
    body: RegisterRequest,
    current_user: TokenPayload = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin endpoint to create users with any role."""
    user = await register_user(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        tenant_id=uuid.UUID(current_user.tenant_id),
        role=body.role,
        db=db,
    )
    await db.commit()
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "message": "User created successfully",
    }
