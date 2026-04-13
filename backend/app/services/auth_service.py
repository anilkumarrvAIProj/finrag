"""
Authentication Service
======================
Handles:
- Password hashing and verification (bcrypt)
- JWT token generation (access + refresh tokens)
- User registration and login
- Token refresh
- RLS context setting for PostgreSQL
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.models import User, Tenant, AuditAction
from app.services.audit_service import write_audit_log

logger = get_logger(__name__)


ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8      # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "tenant_id": str(user.tenant_id),
        "roles": [user.role],
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def create_refresh_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


async def authenticate_user(
    email: str,
    password: str,
    tenant_slug: str,
    db: AsyncSession,
) -> Optional[User]:
    """Verify email + password + tenant. Returns user or None."""
    # Find tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        logger.warning("Login attempt for unknown tenant", slug=tenant_slug)
        return None

    # Find user
    user_result = await db.execute(
        select(User).where(
            User.email == email.lower().strip(),
            User.tenant_id == tenant.id,
            User.is_active == True,
        )
    )
    user = user_result.scalar_one_or_none()
    if not user:
        logger.warning("Login attempt for unknown user", email=email, tenant=tenant_slug)
        return None

    # Check password
    if not user.password_hash:
        logger.warning("User has no password set", user_id=str(user.id))
        return None

    if not verify_password(password, user.password_hash):
        logger.warning("Invalid password", user_id=str(user.id))
        return None

    # Update last login
    user.last_login_at = datetime.utcnow()
    return user


async def register_user(
    email: str,
    password: str,
    display_name: str,
    tenant_id: uuid.UUID,
    role: str,
    db: AsyncSession,
) -> User:
    """Create a new user with hashed password."""
    # Check email not already taken in this tenant
    existing = await db.execute(
        select(User).where(User.email == email.lower().strip(), User.tenant_id == tenant_id)
    )
    if existing.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        external_id=f"local|{uuid.uuid4().hex[:12]}",
        email=email.lower().strip(),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    logger.info("User registered", user_id=str(user.id), email=email, role=role)
    return user


async def set_rls_context(db: AsyncSession, tenant_id: str) -> None:
    """Set PostgreSQL RLS context so row-level security policies fire correctly."""
    await db.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))


async def refresh_access_token(refresh_token: str, db: AsyncSession) -> Optional[dict]:
    """Validate refresh token and issue new access token."""
    try:
        payload = jwt.decode(
            refresh_token,
            settings.app_secret_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        if payload.get("type") != "refresh":
            return None

        user_id = payload.get("sub")
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id), User.is_active == True)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        return {
            "access_token": create_access_token(user),
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
    except JWTError:
        return None
