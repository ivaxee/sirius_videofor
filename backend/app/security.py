"""Анонимные токены, хэш IP, rate limiting, доступ к админке, заголовки безопасности."""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
import uuid
from collections import deque
from datetime import date

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings


def _sign(message: str, purpose: str) -> str:
    key = hashlib.sha256(f"{purpose}:{settings.secret_key}".encode()).digest()
    mac = hmac.new(key, message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:24]).decode().rstrip("=")


def issue_token(user_id: uuid.UUID) -> str:
    return f"{user_id}.{_sign(str(user_id), 'user')}"


def parse_token(token: str) -> uuid.UUID | None:
    uid, _, sig = token.partition(".")
    try:
        parsed = uuid.UUID(uid)
    except ValueError:
        return None
    if not sig or not hmac.compare_digest(sig, _sign(str(parsed), "user")):
        return None
    return parsed


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_hash(ip: str, day: date) -> str:
    """Сырой IP не хранится: только HMAC от дня и IP — годится для дневных лимитов,
    но не позволяет связать активность разных дней."""
    return _sign(f"{day.isoformat()}:{ip}", "ip")[:24]


def sign_media(key: str, expires: int) -> str:
    return _sign(f"{key}:{expires}", "media")


def verify_media(key: str, expires: int, sig: str) -> bool:
    return expires >= int(time.time()) and hmac.compare_digest(sig, sign_media(key, expires))


def current_user_id(request: Request) -> uuid.UUID:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    uid = parse_token(token.strip()) if scheme.lower() == "bearer" else None
    if uid is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return uid


def require_admin(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not settings.admin_token or not hmac.compare_digest(
        token.strip().encode(), settings.admin_token.encode()
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


AdminDep = Depends(require_admin)


class RateLimiter:
    """Скользящее окно в памяти процесса. Для нескольких реплик — заменить на Redis;
    nginx перед бэкендом даёт общий лимит."""

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = limit
        self.window = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # защита памяти
                for k in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[k]
            return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/media/"):
            if not self.limiter.allow(client_ip(request)):
                return JSONResponse({"detail": "rate_limited"}, status_code=429, headers={"Retry-After": "30"})
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("X-Frame-Options", "DENY")
        if request.url.path != "/api/docs":  # Swagger UI грузит скрипты с CDN
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/media/"):
            h.setdefault("Cache-Control", "no-store")
        return response
