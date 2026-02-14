"""API Key authentication and rate limiting for Frank Gateway."""
from __future__ import annotations

import hashlib
import time
from typing import Dict, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_security = HTTPBearer()


class RateLimiter:
    """Simple in-memory sliding-window rate limiter."""

    def __init__(self, default_rpm: int = 60, chat_rpm: int = 10):
        self._default_rpm = default_rpm
        self._chat_rpm = chat_rpm
        self._hits: Dict[str, list] = {}  # key -> [timestamps]

    def check(self, key: str, is_chat: bool = False) -> bool:
        now = time.time()
        limit = self._chat_rpm if is_chat else self._default_rpm
        window = now - 60.0

        bucket = self._hits.setdefault(key, [])
        # Prune old entries
        bucket[:] = [t for t in bucket if t > window]

        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


_rate_limiter: Optional[RateLimiter] = None
_api_key_hash: str = ""


def init_auth(api_key_hash: str, default_rpm: int = 60, chat_rpm: int = 10):
    """Initialize auth module with config values."""
    global _rate_limiter, _api_key_hash
    _api_key_hash = api_key_hash
    _rate_limiter = RateLimiter(default_rpm=default_rpm, chat_rpm=chat_rpm)


def hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_security),
):
    """FastAPI dependency: verify Bearer token and rate limit."""
    token = credentials.credentials
    token_hash = hash_api_key(token)

    if token_hash != _api_key_hash:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    is_chat = request.url.path.startswith("/chat")

    if _rate_limiter and not _rate_limiter.check(client_ip, is_chat=is_chat):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return token
