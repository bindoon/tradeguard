"""Restrict the online console to market reads and a private portfolio."""

import hmac
import re
import secrets
import time
from hashlib import sha256
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from tradeguard.config import Settings

COOKIE = "__Host-tradeguard-portfolio"
SESSION_SECONDS = 12 * 60 * 60
PUBLIC_READS = {
    "/api/context",
    "/api/health",
    "/api/search",
    "/api/securities/names",
    "/api/scan/dates",
    "/api/scan/summaries",
    "/api/stock-pool/filter",
    "/api/workspace",
}
MARKET_DETAIL = re.compile(
    r"/api/(?:kline/[^/]+|stocks/[^/]+/(?:profile|signals)"
    r"|scan/[^/]+/(?:summary|results|sectors))"
)
PORTFOLIO_READS = {"/api/portfolio/accounts", "/api/discipline/playbook"}
LOGIN = "/api/portfolio/login"
LOGOUT = "/api/portfolio/logout"
SESSION = "/api/portfolio/session"


class Credentials(BaseModel):
    username: str = Field(max_length=256)
    password: SecretStr = Field(max_length=256)


def configure_public_access(app: FastAPI, cfg: Settings) -> None:
    origin = urlsplit(cfg.public_origin or "")
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username is not None
        or cfg.public_origin != f"https://{origin.netloc}"
        or not cfg.portfolio_username
        or not cfg.portfolio_password
    ):
        raise ValueError("Public console requires an HTTPS origin and portfolio credentials")

    key = secrets.token_bytes(32)
    username = sha256(cfg.portfolio_username.get_secret_value().encode()).digest()
    password = sha256(cfg.portfolio_password.get_secret_value().encode()).digest()

    def signature(expires: str) -> str:
        return hmac.digest(key, expires.encode(), "sha256").hex()

    def authenticated(request: Request) -> bool:
        expires, _, signed = request.cookies.get(COOKIE, "").partition(".")
        return (
            bool(re.fullmatch(r"[0-9]{1,12}", expires))
            and int(expires) > time.time()
            and hmac.compare_digest(signature(expires).encode(), signed.encode())
        )

    @app.middleware("http")
    async def restrict_online(request: Request, call_next):
        path = request.url.path
        read = request.method in {"GET", "HEAD"}
        if path.startswith("/api/"):
            if read and (path in PUBLIC_READS or MARKET_DETAIL.fullmatch(path)):
                return await call_next(request)
            if read and path in PORTFOLIO_READS | {SESSION}:
                if path != SESSION and not authenticated(request):
                    response = JSONResponse({"detail": "请先登录"}, status_code=401)
                else:
                    response = await call_next(request)
            elif request.method == "POST" and path in {LOGIN, LOGOUT}:
                if request.headers.get("origin") != cfg.public_origin:
                    response = JSONResponse({"detail": "请从本站登录"}, status_code=403)
                else:
                    response = await call_next(request)
                    if path == LOGIN and response.status_code == 422:
                        response = JSONResponse({"detail": "登录信息格式无效"}, status_code=422)
            else:
                response = JSONResponse({"detail": "此接口未开放"}, status_code=404)
            response.headers["Cache-Control"] = "no-store"
            return response

        response = await call_next(request)
        if path.rstrip("/") in {"/portfolio", "/monitor"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Robots-Tag"] = "noindex"
        return response

    @app.get(SESSION)
    def portfolio_session(request: Request):
        return {"authenticated": authenticated(request)}

    @app.post(LOGIN)
    def portfolio_login(payload: Credentials, response: Response):
        valid_user = hmac.compare_digest(sha256(payload.username.encode()).digest(), username)
        valid_password = hmac.compare_digest(
            sha256(payload.password.get_secret_value().encode()).digest(), password
        )
        if not (valid_user and valid_password):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        expires = str(int(time.time()) + SESSION_SECONDS)
        response.set_cookie(
            COOKIE,
            f"{expires}.{signature(expires)}",
            max_age=SESSION_SECONDS,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return {"authenticated": True}

    @app.post(LOGOUT)
    def portfolio_logout(response: Response):
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict")
        return {"authenticated": False}
