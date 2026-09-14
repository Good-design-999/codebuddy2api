"""Shared API-key checks and header-only admission before inference buffering."""

import secrets

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def require_api_key(key, authorization=None, x_api_key=None):
    """Preserve Bearer precedence, X-Api-Key fallback, and optional empty keys."""
    if not key:
        return
    token = ""
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token and isinstance(x_api_key, str):
        token = x_api_key
    if not secrets.compare_digest(token.encode(), key.encode()):
        raise HTTPException(status_code=401, detail={"error": {"message": "invalid api key", "type": "auth_error"}})


class InferenceAuthMiddleware:
    def __init__(self, app, config):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        try:
            require_api_key(self.config.get("api_key"), headers.get("authorization"), headers.get("x-api-key"))
        except HTTPException as error:
            payload = error.detail
            if scope["path"].startswith("/v1/messages"):
                payload = {"type": "error", "error": {**payload["error"], "type": "authentication_error"}}
            response = JSONResponse(payload, status_code=error.status_code, headers=error.headers)
            return await response(scope, receive, send)
        await self.app(scope, receive, send)
