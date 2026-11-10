import json
import time

import httpx
import pyotp
import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func, select

from app import admin_auth
from app.bot.setup import make_dispatcher
from app.db.models import SecurityEvent
from app.db.session import transaction
from app.ratelimit import MemoryKV
from app.runtime import Runtime
from app.web.main import create_app
from tests.fakebot import make_bot, msg_update

PW = "correct horse battery staple"


@pytest.fixture
async def api(world):
    bot, sess = make_bot()
    kv = MemoryKV()
    dp = make_dispatcher(world.settings, world.sm, MemoryStorage(), kv, clock=world.clock)
    rt = Runtime(world.settings, None, world.sm, kv, world.svc, [], [], bot, dp)
    app = create_app(world.settings, rt)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.sess, c.world = sess, world
        yield c


HDR = {"X-Telegram-Bot-Api-Secret-Token": "w" * 40}
URL = "/telegram/webhook/" + "p" * 40


async def test_webhook_secret_validation(api):
    body = json.dumps(msg_update(111, "/start"))
    assert (await api.post("/telegram/webhook/wrong-path", content=body, headers=HDR)).status_code == 404
    assert (await api.post(URL, content=body)).status_code == 403
    assert (await api.post(URL, content=body, headers={"X-Telegram-Bot-Api-Secret-Token": "x" * 40})).status_code == 403
    assert api.sess.calls == []
    async with api.world.sm() as s:
        assert (await s.execute(select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.kind == "webhook_bad_secret"))).scalar() == 2
    assert (await api.post(URL, content=body, headers=HDR)).status_code == 200
    assert "شماره مشتری" in api.sess.last_text()


async def test_webhook_rejects_garbage_and_oversize_and_replays(api):
    assert (await api.post(URL, content=b"not json", headers=HDR)).status_code == 400
    assert (await api.post(URL, content=b"x" * 1_100_000, headers=HDR)).status_code == 413
    body = json.dumps(msg_update(111, "/start", update_id=4242))
    for _ in range(3):
        assert (await api.post(URL, content=body, headers=HDR)).status_code == 200
    assert len(api.sess.of("SendMessage")) == 1          # replayed update_id processed once


async def test_unconfigured_secrets_disable_webhook(world):
    from app.config import Settings
    s = Settings(**{**world.settings.model_dump(), "webhook_secret_token": "", "webhook_path_secret": ""})
    bot, _ = make_bot()
    rt = Runtime(s, None, world.sm, MemoryKV(), world.svc, [], [], bot, None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(s, rt)), base_url="http://t") as c:
        assert (await c.post("/telegram/webhook/", content=b"{}")).status_code in (404, 405)
        assert (await c.post("/telegram/webhook/anything", content=b"{}", headers={"X-Telegram-Bot-Api-Secret-Token": ""})).status_code == 404


async def mk_admin(world, tid, role):
    async with transaction(world.sm) as s:
        uri = await admin_auth.create_admin(s, world.settings, tid, role, PW)
    return pyotp.parse_uri(uri)


async def login(api, tid, totp):
    r = await api.post("/admin/api/login", json={"telegram_id": tid, "password": PW, "totp": totp.now()})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


async def test_admin_api_requires_auth_and_enforces_rbac(api):
    w = api.world
    for path in ("/customers/1", "/audit", "/claims", "/config", "/security/alerts", "/fixtures", "/odds/health"):
        assert (await api.get("/admin/api" + path)).status_code == 401
        assert (await api.get("/admin/api" + path, headers={"Authorization": "Bearer forged"})).status_code == 401
    assert (await api.post("/admin/api/config/margin", json={"margin_bp": 0, "reason": "no auth"})).status_code == 401
    # webhook secret is not an admin credential
    assert (await api.get("/admin/api/audit", headers={"Authorization": "Bearer " + "w" * 40})).status_code == 401

    viewer_totp = await mk_admin(w, 9002, "viewer")
    root_totp = await mk_admin(w, 9001, "superadmin")
    v = await login(api, 9002, viewer_totp)
    assert (await api.get("/admin/api/fixtures", headers=v)).status_code == 200
    assert (await api.get("/admin/api/audit", headers=v)).status_code == 403
    assert (await api.post("/admin/api/config/margin", headers=v, json={"margin_bp": 0, "reason": "viewer hack"})).status_code == 403
    assert (await api.post("/admin/api/settlement/correct", headers=v, json={
        "event_id": 1, "final_status": "finished", "home_goals": 9, "away_goals": 0, "reason": "viewer hack"})).status_code == 403

    r = await login(api, 9001, root_totp)
    assert (await api.get("/admin/api/audit/verify", headers=r)).json() == {"chain_ok": True, "first_bad_id": None}
    cfg = (await api.get("/admin/api/config", headers=r)).json()
    assert cfg["real_money_gate_open"] is False and cfg["config"]["margin_bp"] == 500
    assert (await api.post("/admin/api/config/margin", headers=r, json={"margin_bp": 9999, "reason": "too high"})).status_code == 422
    assert (await api.post("/admin/api/config/margin", headers=r, json={"margin_bp": 650, "reason": "seasonal review"})).status_code == 200
    assert (await api.get("/admin/api/config", headers=r)).json()["config"]["margin_bp"] == 650
    acts = [a["action"] for a in (await api.get("/admin/api/audit?limit=20", headers=r)).json()]
    assert "config.publish" in acts and "admin.login" in acts
    export = await api.get("/admin/api/audit/export", headers=r)
    assert export.status_code == 200 and '"chain_ok": true' in export.text.splitlines()[0]
    alerts = (await api.get("/admin/api/security/alerts", headers=r)).json()
    assert any(a["kind"] == "admin_permission_denied" for a in alerts)      # denied attempts were recorded


async def test_admin_login_throttled_and_2fa_required(api):
    w = api.world
    totp = await mk_admin(w, 9001, "superadmin")
    bad = {"telegram_id": 9001, "password": PW, "totp": "000000"}
    codes = [(await api.post("/admin/api/login", json=bad)).status_code for _ in range(12)]
    assert set(codes) <= {401, 429} and 429 in codes
    assert (await api.post("/admin/api/login", json={"telegram_id": 9001, "password": PW, "totp": ""})).status_code == 422
    assert (await api.post("/admin/api/login", json={"telegram_id": 9001, "password": PW})).status_code == 422


async def test_admin_flow_customer_lookup_and_claim_resolution(api):
    from datetime import timedelta
    from app.services import settlement
    from tests.conftest import place, register
    from tests.test_settlement import finish
    w = api.world
    await register(w)
    bet, _, _ = await place(w, selection="home", stake=1000)
    await finish(w, w.event_id, 2, 1)
    await settlement.settle_pending(w.sm, w.settings, w.clock())
    totp = await mk_admin(w, 9001, "superadmin")
    h = await login(api, 9001, totp)
    c = (await api.get("/admin/api/customers/111", headers=h)).json()
    assert c["customer_number"] == 111 and c["demo"] is True and c["balance_minor"] == 99_000
    assert (await api.get("/admin/api/customers/424242", headers=h)).status_code == 404
    bets = (await api.get("/admin/api/customers/111/bets", headers=h)).json()
    assert bets[0]["bet_id"] == bet.id and bets[0]["status"] == "won"
    claims = (await api.get("/admin/api/claims", headers=h)).json()
    assert claims[0]["status"] == "pending_request"
    r = await api.post(f"/admin/api/claims/{claims[0]['id']}/resolve", headers=h, json={"approve": True, "reason": "verified"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert (await api.post(f"/admin/api/claims/{claims[0]['id']}/resolve", headers=h, json={"approve": True, "reason": "again"})).status_code == 409
    led = (await api.get("/admin/api/wallets/111", headers=h)).json()
    assert led["balance_minor"] == 99_000 + bet.payout_minor and led["demo"] is True
    # suspend a market -> no longer offered
    r = await api.post("/admin/api/markets/suspend", headers=h, json={"event_id": w.event_id, "market": "btts", "reason": "injury news"})
    assert r.status_code == 200
    fx = (await api.get("/admin/api/fixtures", headers=h)).json()
    assert isinstance(fx, list) and (await api.get("/admin/api/odds/health", headers=h)).status_code == 200
    assert (await api.post(f"/admin/api/markets/lift/{r.json()['id']}", headers=h)).status_code == 200
    acts = [a["action"] for a in (await api.get("/admin/api/audit?limit=100", headers=h)).json()]
    assert {"admin.read_customer", "admin.read_bets", "admin.read_wallet", "claim.approved", "market.suspended"} <= set(acts)


async def test_console_and_headers(api):
    r = await api.get("/admin/console")
    assert r.status_code == 200 and "DEMO MODE" in r.text and r.headers["x-frame-options"] == "DENY"
    assert (await api.get("/healthz")).json()["mode"] == "demo"
