"""FastAPI app: Telegram webhook + separate, authenticated admin API."""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.db.session import transaction
from app.logging import setup_logging
from app.ratelimit import allow
from app.runtime import Runtime, build
from app.security import security_event
from app.web.admin import router as admin_router

log = logging.getLogger("web")
MAX_BODY = 1_000_000


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        app.state.rt = runtime or await build(settings, with_bot=True)
        rt: Runtime = app.state.rt
        if rt.bot and settings.telegram_mode == "webhook":
            url = f"{settings.webhook_base_url.rstrip('/')}/telegram/webhook/{settings.webhook_path_secret.get_secret_value()}"
            await rt.bot.set_webhook(url, secret_token=settings.webhook_secret_token.get_secret_value(),
                                     allowed_updates=["message", "callback_query"], drop_pending_updates=False)
        yield
        if runtime is None:
            await rt.close()

    prod = settings.environment == "prod"
    app = FastAPI(title="football-demo-bot", lifespan=lifespan, docs_url=None if prod else "/docs",
                  redoc_url=None, openapi_url=None if prod else "/openapi.json")
    app.state.settings = settings
    if runtime is not None:
        app.state.rt = runtime

    @app.middleware("http")
    async def sec_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                             "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
                             "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"})
        return resp

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "mode": "demo"}

    @app.post("/telegram/webhook/{path_secret}")
    async def webhook(path_secret: str, request: Request,
                      x_telegram_bot_api_secret_token: str | None = Header(default=None)):
        rt: Runtime = request.app.state.rt
        s = request.app.state.settings
        want_path = s.webhook_path_secret.get_secret_value()
        want_hdr = s.webhook_secret_token.get_secret_value()
        if not want_path or not want_hdr or not hmac.compare_digest(path_secret, want_path):
            raise HTTPException(404)
        if not x_telegram_bot_api_secret_token or not hmac.compare_digest(x_telegram_bot_api_secret_token, want_hdr):
            async with transaction(rt.sm) as db:
                await security_event(db, "webhook_bad_secret", "high", ip=request.client.host if request.client else None)
            raise HTTPException(403)
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            raise HTTPException(413)
        if rt.bot is None or rt.dp is None:
            raise HTTPException(503)
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413)
        try:
            update = Update.model_validate_json(body, context={"bot": rt.bot})
        except Exception:
            raise HTTPException(400)
        await rt.dp.feed_update(rt.bot, update)       # replay protection happens in UpdateDedupe middleware
        return Response(status_code=200)

    @app.get("/admin/console", response_class=HTMLResponse)
    async def console(request: Request):
        ip = request.client.host if request.client else None
        from app.admin_auth import ip_allowed
        if not ip_allowed(request.app.state.settings, ip):
            raise HTTPException(403)
        return (Path(__file__).parent / "console.html").read_text(encoding="utf-8")

    app.include_router(admin_router, prefix="/admin/api")
    return app


app = create_app()   # no I/O at import time; the runtime is built in the lifespan hook
