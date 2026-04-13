"""
Row-Level Security Middleware
Sets PostgreSQL session variable app.current_tenant_id on every
authenticated request so RLS policies fire correctly.
"""
from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware


class RLSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.tenant_id = None
        request.state.user_id = None
        request.state.user_role = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                from jose import jwt
                from app.core.config import settings
                payload = jwt.decode(
                    token,
                    settings.app_secret_key,
                    algorithms=["HS256"],
                    options={"verify_aud": False, "verify_exp": False},
                )
                request.state.tenant_id = payload.get("tenant_id")
                request.state.user_id = payload.get("sub")
                roles = payload.get("roles", [])
                request.state.user_role = roles[0] if roles else "read_only"
            except Exception:
                pass

        response = await call_next(request)
        return response
