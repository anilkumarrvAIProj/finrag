"""
JWT verification + Role-Based Access Control
============================================
Supports:
  - Real HS256 tokens issued by our auth service (login-based)
  - Dev tokens for local development only
  - Role hierarchy enforcement
  - RLS context injection per request
"""
from enum import Enum
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    ANALYST = "analyst"
    READ_ONLY = "read_only"


ROLE_HIERARCHY = {
    UserRole.SUPER_ADMIN: 4,
    UserRole.ADMIN: 3,
    UserRole.ANALYST: 2,
    UserRole.READ_ONLY: 1,
}


class TokenPayload(BaseModel):
    sub: str                    # user UUID
    email: Optional[str] = None
    tenant_id: str = "00000000-0000-0000-0000-000000000001"
    roles: list[UserRole] = [UserRole.READ_ONLY]
    type: str = "access"        # "access" or "refresh"
    exp: Optional[int] = None


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> TokenPayload:
    """
    Verify JWT issued by our auth service.
    In dev mode (APP_ENV != production) also accepts dev tokens.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )

        token_type = payload.get("type", "access")
        if token_type == "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token cannot be used for API access. Use /auth/refresh to get an access token.",
            )

        return TokenPayload(**payload)

    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalid or expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(minimum_role: UserRole):
    """Dependency factory — require minimum role level."""
    async def checker(payload: TokenPayload = Depends(verify_token)) -> TokenPayload:
        user_max = max(ROLE_HIERARCHY.get(r, 0) for r in payload.roles)
        required = ROLE_HIERARCHY[minimum_role]
        if user_max < required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {minimum_role.value}",
            )
        return payload
    return checker


# ── Dependency functions used in endpoints ────────────────────────────────────

def get_current_user(payload: TokenPayload = Depends(verify_token)) -> TokenPayload:
    """Any authenticated user."""
    return payload


def get_analyst_user(payload: TokenPayload = Depends(require_role(UserRole.ANALYST))) -> TokenPayload:
    """Analyst or above."""
    return payload


def get_admin_user(payload: TokenPayload = Depends(require_role(UserRole.ADMIN))) -> TokenPayload:
    """Admin or above."""
    return payload


def get_super_admin_user(payload: TokenPayload = Depends(require_role(UserRole.SUPER_ADMIN))) -> TokenPayload:
    """Super admin only."""
    return payload
