"""PostgreSQL-only: the database itself must refuse tampering, even if application code is bypassed."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import AuditEvent, Bet, LedgerEntry, Receipt, Settlement, Wallet
from app.db.session import transaction
from app.services.audit import append_audit
from tests.conftest import IS_PG, place, register

pytestmark = pytest.mark.skipif(not IS_PG, reason="requires TEST_DATABASE_URL (PostgreSQL migrated by Alembic)")


async def test_append_only_tables_reject_update_and_delete(world):
    await register(world)
    await place(world)
    async with transaction(world.sm) as s:
        await append_audit(s, world.settings, "system", "x", "x", 1, {})
    for stmt in ("UPDATE ledger_entries SET amount_minor = 1", "DELETE FROM ledger_entries",
                 "UPDATE audit_events SET actor = 'evil'", "DELETE FROM audit_events",
                 "UPDATE signed_configs SET reason = 'evil'", "DELETE FROM signed_configs"):
        with pytest.raises(DBAPIError):
            async with transaction(world.sm) as s:
                await s.execute(text(stmt))


async def test_bet_terms_and_receipt_content_immutable_but_status_updatable(world):
    await register(world)
    bet, rc, _ = await place(world)
    for stmt in ("UPDATE bets SET stake_minor = 1", "UPDATE bets SET odds_milli = 99999", "DELETE FROM bets",
                 "UPDATE receipts SET integrity_hash = 'x'", "DELETE FROM receipts"):
        with pytest.raises(DBAPIError):
            async with transaction(world.sm) as s:
                await s.execute(text(stmt))
    async with transaction(world.sm) as s:      # legitimate lifecycle updates still work
        await s.execute(text("UPDATE bets SET status = 'lost'"))
        await s.execute(text("UPDATE receipts SET pin_status = 'pinned', telegram_message_id = 5"))


async def test_negative_wallet_blocked_by_database(world):
    await register(world)
    with pytest.raises(DBAPIError):
        async with transaction(world.sm) as s:
            await s.execute(text("UPDATE wallets SET balance_minor = -1"))
