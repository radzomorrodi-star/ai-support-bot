from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select, update

from app import admin_auth, compliance
from app.admin_auth import AuthError
from app.config import Settings
from app.db.models import AdminUser, AuditEvent, PaymentTransaction, SecurityEvent, SignedConfig
from app.db.session import transaction
from app.logging import redact
from app.payments import usdt
from app.payments.usdt import BSC_CHAIN_ID, USDT_BSC_CONTRACT, ChainTransfer, MockChain, mock_deposit_address
from app.security import decrypt_secret
from app.services import opconfig, wallet
from app.services.audit import append_audit, verify_chain
from tests.conftest import bypass_triggers, place, register

PW = "correct horse battery staple"


async def mk_admin(world, tid=9001, role="superadmin"):
    async with transaction(world.sm) as s:
        uri = await admin_auth.create_admin(s, world.settings, tid, role, PW)
    return pyotp.parse_uri(uri)


async def try_login(world, tid, pw, code, ip="1.2.3.4"):
    async with world.sm() as s:
        try:
            tok = await admin_auth.login(s, world.settings, tid, pw, code, ip)
            await s.commit()
            return tok
        except AuthError:
            await s.commit()        # persist failure counters/events, like the API layer does
            raise


# ---------------- admin access ----------------
async def test_admin_cannot_be_created_outside_allowlist(world):
    async with transaction(world.sm) as s:
        with pytest.raises(AuthError):
            await admin_auth.create_admin(s, world.settings, 31337, "superadmin", PW)


async def test_unauthorized_admin_access(world):
    totp = await mk_admin(world)
    # not allow-listed even if someone planted a DB row
    async with transaction(world.sm) as s:
        s.add(AdminUser(telegram_id=555, role="superadmin", password_hash="x", totp_secret_enc="x"))
    with pytest.raises(AuthError):
        await try_login(world, 555, PW, "000000")
    with pytest.raises(AuthError):
        await try_login(world, 9001, "wrong password!!", totp.now())
    with pytest.raises(AuthError):
        await try_login(world, 9001, PW, "123456")
    with pytest.raises(AuthError):
        await try_login(world, 9001, PW, "")            # no 2FA code
    async with world.sm() as s:
        for tok in (None, "", "forged-token"):
            with pytest.raises(AuthError):
                await admin_auth.authenticate(s, world.settings, tok, "1.2.3.4")
        kinds = {e.kind for e in (await s.execute(select(SecurityEvent))).scalars()}
    assert {"admin_login_denied_allowlist", "admin_login_failed"} <= kinds


async def test_totp_code_cannot_be_replayed_and_lockout(world):
    totp = await mk_admin(world)
    code = totp.now()
    tok = await try_login(world, 9001, PW, code)
    async with world.sm() as s:
        assert (await admin_auth.authenticate(s, world.settings, tok, "1.2.3.4")).telegram_id == 9001
    with pytest.raises(AuthError):
        await try_login(world, 9001, PW, code)          # same 30s code twice = replay
    for _ in range(5):
        with pytest.raises(AuthError):
            await try_login(world, 9001, PW, "000000")
    with pytest.raises(AuthError):                      # locked: even valid creds are refused
        await try_login(world, 9001, PW, totp.at(__import__("time").time() + 30))


async def test_rbac_and_session_expiry_and_ip_allowlist(world):
    totp = await mk_admin(world, 9002, "viewer")
    tok = await try_login(world, 9002, PW, totp.now())
    async with world.sm() as s:
        await admin_auth.require(s, world.settings, tok, "1.2.3.4", "customers:read")
        with pytest.raises(AuthError):
            await admin_auth.require(s, world.settings, tok, "1.2.3.4", "settlement:correct")
        with pytest.raises(AuthError):
            await admin_auth.require(s, world.settings, tok, "1.2.3.4", "config:write")
        await s.execute(update(__import__("app.db.models", fromlist=["AdminSession"]).AdminSession).values(
            expires_at=__import__("app.db.base", fromlist=["utcnow"]).utcnow() - timedelta(seconds=1)))
        with pytest.raises(AuthError):
            await admin_auth.authenticate(s, world.settings, tok, "1.2.3.4")
    strict = Settings(**{**world.settings.model_dump(), "admin_ip_allowlist": "10.0.0.0/8"})
    assert admin_auth.ip_allowed(strict, "10.1.2.3") and not admin_auth.ip_allowed(strict, "8.8.8.8")
    assert not admin_auth.ip_allowed(strict, None)


async def test_totp_secret_encrypted_at_rest(world):
    totp = await mk_admin(world)
    async with world.sm() as s:
        a = await s.get(AdminUser, 9001)
        assert totp.secret not in a.totp_secret_enc and decrypt_secret(world.settings, a.totp_secret_enc) == totp.secret
        assert PW not in a.password_hash


# ---------------- payments ----------------
def transfer(cid=111, tx="0x" + "ab" * 32, conf=20, amount=25 * 10**18, **kw):
    d = dict(chain_id=BSC_CHAIN_ID, tx_hash=tx, log_index=0, token_contract=USDT_BSC_CONTRACT,
             to_address=mock_deposit_address(cid), amount_base_units=amount, confirmations=conf)
    d.update(kw)
    return ChainTransfer(**d)


async def test_fake_and_malformed_transactions_rejected(world):
    await register(world)
    chain = MockChain()
    prov = usdt.MockPaymentProvider(chain, world.settings)
    chain.mine(transfer(tx="0x" + "01" * 32, token_contract="0x" + "99" * 20))          # wrong token
    chain.mine(transfer(tx="0x" + "02" * 32, chain_id=1))                                # wrong chain
    chain.mine(transfer(tx="0x" + "03" * 32, to_address="0x" + "11" * 20))              # not this customer's address
    chain.mine(transfer(tx="0x" + "04" * 32, amount=1))                                  # dust
    async with transaction(world.sm) as s:
        for tx in ("0x" + "ff" * 32,          # never mined => fabricated by the caller
                   "0x" + "01" * 32, "0x" + "02" * 32, "0x" + "03" * 32, "0x" + "04" * 32,
                   "not-a-hash", "0x123", ""):
            with pytest.raises(usdt.PaymentRejected):
                await prov.ingest_deposit(s, 111, tx)
        assert await wallet.balance(s, 111) == 100_000       # nothing credited
        kinds = {e.kind for e in (await s.execute(select(SecurityEvent))).scalars()}
    assert {"deposit_unknown_tx", "deposit_wrong_token", "deposit_wrong_recipient"} <= kinds


async def test_replayed_transaction_credits_once(world):
    await register(world)
    await register(world, 222)
    chain = MockChain()
    t = transfer()
    chain.mine(t)
    prov = usdt.MockPaymentProvider(chain, world.settings)
    async with transaction(world.sm) as s:
        row = await prov.ingest_deposit(s, 111, t.tx_hash)
        assert row.status == "credited" and await wallet.balance(s, 111) == 100_000 + 2500
    for cid in (111, 222):
        async with world.sm() as s:
            with pytest.raises(usdt.PaymentRejected):          # replay by owner / by another account
                await prov.ingest_deposit(s, cid, t.tx_hash.upper().replace("0X", "0x"))
            await s.rollback()
    async with world.sm() as s:
        assert await wallet.balance(s, 111) == 102_500 and await wallet.balance(s, 222) == 100_000
        assert len((await s.execute(select(PaymentTransaction))).scalars().all()) == 1


async def test_unconfirmed_deposit_waits_for_confirmations(world):
    await register(world)
    chain = MockChain()
    t = transfer(conf=3)
    chain.mine(t)
    prov = usdt.MockPaymentProvider(chain, world.settings)
    async with transaction(world.sm) as s:
        assert (await prov.ingest_deposit(s, 111, t.tx_hash)).status == "pending"
        assert await wallet.balance(s, 111) == 100_000
    chain.set_confirmations(t.tx_hash, usdt.MIN_CONFIRMATIONS)
    async with transaction(world.sm) as s:
        assert (await prov.ingest_deposit(s, 111, t.tx_hash)).status == "credited"
        assert await wallet.balance(s, 111) == 102_500


# ---------------- feature gate ----------------
def full_cfg():
    return {**opconfig.DEFAULT_CONFIG, "compliance": {
        "license_ref": "L-1", "legal_approval_ref": "LEGAL-1", "security_assessment_ref": "PEN-1",
        "approved_jurisdictions": ["XX"]}}


async def test_real_money_gate_cannot_be_bypassed(world):
    s_on = Settings(**{**world.settings.model_dump(), "real_money_enabled": True})
    for settings in (world.settings, s_on):
        for cfg in (None, opconfig.DEFAULT_CONFIG, full_cfg()):
            ok, unmet = compliance.gate_status(settings, cfg)
            assert not ok and any("not implemented" in u for u in unmet)
            with pytest.raises(compliance.FeatureDisabled):
                compliance.require_real_money(settings, cfg)
    async with transaction(world.sm) as s:
        for settings, cfg in ((world.settings, None), (s_on, full_cfg())):
            with pytest.raises(compliance.FeatureDisabled):
                await usdt.request_withdrawal(s, settings, cfg, 111, 100, "0x" + "11" * 20)
        n = len((await s.execute(select(SecurityEvent).where(SecurityEvent.kind == "withdrawal_attempt_blocked"))).scalars().all())
    assert n == 2
    # providers: the factory only ever returns the MOCK provider, even with every flag + approval set
    assert isinstance(usdt.get_payment_provider(s_on, full_cfg(), MockChain()), usdt.MockPaymentProvider)


async def test_flipping_the_code_constant_still_yields_no_real_provider(world, monkeypatch):
    s_on = Settings(**{**world.settings.model_dump(), "real_money_enabled": True})
    monkeypatch.setattr(compliance, "REAL_MONEY_CODE_PATH_IMPLEMENTED", True)
    assert compliance.gate_status(s_on, full_cfg())[0] is True
    with pytest.raises(NotImplementedError):
        usdt.get_payment_provider(s_on, full_cfg(), MockChain())
    async with transaction(world.sm) as s:
        with pytest.raises(NotImplementedError):
            await usdt.request_withdrawal(s, s_on, full_cfg(), 111, 100, "0x" + "11" * 20)


def test_withdrawal_policy_separation_of_duties():
    p = usdt.WithdrawalApprovalPolicy(2)
    assert not p.can_release(1, {1, 2}) and not p.can_release(1, {2}) and p.can_release(1, {2, 3})


# ---------------- config / audit integrity ----------------
async def test_tampered_signed_config_fails_closed(world):
    await register(world)
    async with transaction(world.sm) as s:      # attacker with DB access lowers the margin to 0
        await bypass_triggers(s)
        row = (await s.execute(select(SignedConfig))).scalars().first()
        row.payload = {**row.payload, "margin_bp": 0}
    with pytest.raises(opconfig.ConfigTampered):
        async with world.sm() as s:
            await opconfig.load_active(s, world.settings)
    from app.services import betting
    from tests.conftest import make_draft
    with pytest.raises(opconfig.ConfigTampered):
        await make_draft(world, 111)
    async with world.sm() as s:
        assert (await s.execute(select(SecurityEvent).where(SecurityEvent.kind == "config_signature_invalid"))).first()


async def test_margin_changes_are_versioned_audited_and_bounded(world):
    async with transaction(world.sm) as s:
        v, cfg = await opconfig.load_active(s, world.settings)
        await opconfig.publish(s, world.settings, {**cfg, "margin_bp": 700}, "admin:9001", "seasonal change")
        with pytest.raises(opconfig.ConfigInvalid):
            await opconfig.publish(s, world.settings, {**cfg, "margin_bp": 9000}, "admin:9001", "nope")
    async with world.sm() as s:
        v2, cfg2 = await opconfig.load_active(s, world.settings)
        assert v2 == v + 1 and cfg2["margin_bp"] == 700
        assert len((await s.execute(select(SignedConfig))).scalars().all()) == 2      # old version preserved
        a = (await s.execute(select(AuditEvent).where(AuditEvent.action == "config.publish").order_by(AuditEvent.id.desc()))).scalars().first()
        assert a.actor == "admin:9001" and a.data["margin_bp"] == 700


async def test_audit_chain_detects_tampering(world):
    async with transaction(world.sm) as s:
        for i in range(4):
            await append_audit(s, world.settings, "system", "t.event", "x", i, {"i": i})
    async with world.sm() as s:
        assert (await verify_chain(s, world.settings))[0]
    async with transaction(world.sm) as s:
        await bypass_triggers(s)
        row = (await s.execute(select(AuditEvent).where(AuditEvent.action == "t.event", AuditEvent.entity_id == "2"))).scalar()
        row.data = {"i": 999}
    async with world.sm() as s:
        ok, bad = await verify_chain(s, world.settings)
        assert not ok and bad is not None


async def test_audit_export_contains_chain_status(world):
    async with transaction(world.sm) as s:
        out = await compliance.export_audit_jsonl(s, world.settings)
    assert '"chain_ok": true' in out.splitlines()[0]


def test_log_redaction():
    assert "123456:ABCdefGhIJKlmNoPQRsTUVwxyZ_0123456789" not in redact("tok 123456:ABCdefGhIJKlmNoPQRsTUVwxyZ_0123456789 x")
    assert "s3cr3t" not in redact("GET /odds?apiKey=s3cr3t&regions=eu")
    assert "hunter2" not in redact('password: hunter2')


async def test_anonymize_keeps_financial_records(world):
    await register(world)
    await place(world)
    async with transaction(world.sm) as s:
        await compliance.anonymize_customer(s, 111)
    async with world.sm() as s:
        from app.db.models import Bet, Customer
        c = await s.get(Customer, 111)
        assert c.username is None and c.status == "blocked"
        assert (await s.execute(select(Bet))).scalars().all()
