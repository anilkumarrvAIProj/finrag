"""
JWT verification + Role-Based Access Control.
Supports Auth0 and local development (HS256 dev tokens).
"""
import time
from enum import Enum
from typing import Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

_jwks_cache: dict = {}
_jwks_cache_time: float = 0.0
JWKS_TTL = 3600


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
    sub: str
    tenant_id: str = "00000000-0000-0000-0000-000000000001"
    roles: list[UserRole] = [UserRole.READ_ONLY]
    email: Optional[str] = None
    exp: Optional[int] = None


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> TokenPayload:
    """Verify JWT. In dev mode accepts HS256 tokens signed with APP_SECRET_KEY."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = credentials.credentials

    # Dev mode: HS256 only — never attempt Auth0
    if not settings.is_production:
        try:
            payload = jwt.decode(
                token,
                settings.app_secret_key,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            return TokenPayload(**payload)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid dev token: {exc}. Get a new token from /api/v1/auth/dev-token",
            )

    # Production only: RS256 via Auth0
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{settings.auth_domain}/.well-known/jwks.json"
            )
            jwks = resp.json()

        header = jwt.get_unverified_header(token)
        rsa_key = next(
            (
                {"kty": k["kty"], "kid": k["kid"], "use": k["use"], "n": k["n"], "e": k["e"]}
                for k in jwks["keys"]
                if k["kid"] == header["kid"]
            ),
            None,
        )
        if rsa_key is None:
            raise HTTPException(status_code=401, detail="Unknown signing key")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=[settings.auth_algorithm],
            audience=settings.auth_audience,
        )
        return TokenPayload(**payload)
    except JWTError as exc:
        logger.warning("JWT verification failed", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(minimum_role: UserRole):
    """Dependency factory: require a minimum role level."""
    async def checker(payload: TokenPayload = Depends(verify_token)) -> TokenPayload:
        user_max = max(ROLE_HIERARCHY.get(r, 0) for r in payload.roles)
        required = ROLE_HIERARCHY[minimum_role]
        if user_max < required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {minimum_role.value}",
            )
        return payload
    return checker


# Simple dependency functions — use these in endpoints
def get_current_user(payload: TokenPayload = Depends(verify_token)) -> TokenPayload:
    return payload

def get_admin_user(payload: TokenPayload = Depends(require_role(UserRole.ADMIN))) -> TokenPayload:
    return payload

def get_super_admin_user(payload: TokenPayload = Depends(require_role(UserRole.SUPER_ADMIN))) -> TokenPayload:
    return payload
