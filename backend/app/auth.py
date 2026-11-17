"""Password protection for remote access (website + iPhone app).

* One shared password from APP_PASSWORD (never hard-coded, never sent to the browser).
* Successful login sets an HttpOnly, SameSite=Lax cookie holding an HMAC-signed expiry
  (30 days); also accepted as `Authorization: Bearer <token>` for native clients.
* Every page, API route and the live websocket require it; only the login page, its
  static assets and the login endpoint are public. Login attempts are rate-limited.
* If APP_PASSWORD is empty, auth is disabled (local-only use).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .config import get_settings

COOKIE = "rt_auth"
MAX_AGE = 30 * 24 * 3600
PUBLIC_PREFIXES = ("/login", "/_next/", "/api/auth/", "/favicon", "/icon", "/apple-touch-icon", "/manifest",
                   "/fonts/")

router = APIRouter(prefix="/api/auth")
_attempts: dict[str, deque] = defaultdict(deque)


def _secret() -> bytes:
    s = get_settings()
    if s.session_secret:
        return s.session_secret.encode()
    f = Path(s.data_dir) / "session.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return hashlib.sha256(f.read_text(encoding="utf-8").encode() + s.app_password.encode()).digest()


def make_token(ttl: int = MAX_AGE) -> str:
    exp = str(int(time.time()) + ttl)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{exp}.{sig}".encode()).decode()


def valid_token(tok: str | None) -> bool:
    if not tok:
        return False
    try:
        exp, sig = base64.urlsafe_b64decode(tok.encode()).decode().split(".", 1)
    except Exception:
        return False
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and int(exp) > time.time()


def auth_enabled() -> bool:
    return bool(get_settings().app_password)


def request_authorized(cookies: dict, headers) -> bool:
    if not auth_enabled():
        return True
    if valid_token(cookies.get(COOKIE)):
        return True
    h = headers.get("authorization") or ""
    return h.startswith("Bearer ") and valid_token(h[7:])


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not auth_enabled() or path.startswith(PUBLIC_PREFIXES) or path in ("/robots.txt",):
        return await call_next(request)
    if request_authorized(request.cookies, request.headers):
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/docs") or path.startswith("/openapi"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse("/login/", status_code=303)


class LoginIn(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    q = _attempts[ip]
    now = time.time()
    while q and now - q[0] > 300:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "too many attempts — wait 5 minutes")
    q.append(now)
    pw = get_settings().app_password
    if not pw:
        return {"ok": True, "auth": "disabled"}
    if not hmac.compare_digest(body.password.encode(), pw.encode()):
        raise HTTPException(401, "wrong password")
    q.clear()
    tok = make_token()
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, tok, max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure, path="/")
    return {"ok": True, "token": tok}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/status")
async def status(request: Request):
    return {"auth_enabled": auth_enabled(), "authenticated": request_authorized(request.cookies, request.headers)}
