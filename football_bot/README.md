# Persian Football Betting Bot — DEMO MODE ONLY

A Telegram bot (aiogram 3) with an entirely Persian (RTL) interface for **simulated** pre-match football betting on
European competitions, backed by FastAPI, PostgreSQL, Redis and a separate admin API.

> **No real money.** Wagering, USDT deposits, withdrawals and payouts are **not implemented**. Real-money paths are
> blocked by a server-side compliance gate whose master switch is a *source-code constant*
> (`app/compliance.py: REAL_MONEY_CODE_PATH_IMPLEMENTED = False`), not a setting. See
> [`docs/COMPLIANCE_CHECKLIST.md`](docs/COMPLIANCE_CHECKLIST.md) for everything required before a real launch.

This project lives in its own directory; the unrelated Telethon support bot in the repository root is untouched.

## What works (demo)

| Area | Status |
|---|---|
| Persian inline menus (main menu, leagues, matches, my bets, results, demo wallet, terms, support) | ✅ |
| Customer number = Telegram user ID | ✅ |
| 8 competitions, upcoming matches only, UTC storage + local (Jalali) display | ✅ |
| Markets: 1X2, Over/Under 2.5, BTTS; best / median / margin / overround, full calc stored | ✅ |
| Odds providers: The Odds API (real adapter), deterministic mock (offline demo) | ✅ |
| Bet flow: draft → stake → confirm → atomic, idempotent, re-validated server-side | ✅ |
| Receipt (HMAC-SHA256 integrity tag), pinned if Telegram allows, always kept in "my bets" | ✅ |
| Settlement: 2-source verification, void states, corrections (append-only), idempotent | ✅ |
| 10-day claim workflow: reminders, **never forfeits** (→ admin review), duplicate-proof | ✅ |
| Admin API + console: 2FA, RBAC, allowlist, audit, security alerts | ✅ |
| Mock USDT-BEP20 deposit pipeline (replay/fake-tx protection) | ✅ mock only |
| Real deposits / withdrawals / custody | ❌ intentionally absent |
| Odds-API.io / API-Football / Sportmonks adapters | ❌ not built (see `docs/ODDS_PROVIDERS.md`) |

## Quick start (local, no Docker, SQLite + mock odds)

```bash
cd football_bot
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # then set the four keys below, BOT_TOKEN, ADMIN_ALLOWLIST; keep ODDS_PRIMARY_PROVIDER=mock
export DATABASE_URL=sqlite+aiosqlite:///./dev.db REDIS_URL=
python -m app.cli bootstrap
python -m app.cli create-admin --telegram-id <your id> --role superadmin   # prints a 2FA QR URI once
python -m app.worker            # polling bot + odds refresh + settlement + reminders
uvicorn app.web.main:app --port 8000   # admin API/console (+ webhook if TELEGRAM_MODE=webhook)
pytest                          # 118 tests
```

Generate keys: `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` for
`SECRETS_KEY`; `openssl rand -hex 32` for `RECEIPT_HMAC_KEY`, `CONFIG_SIGNING_KEY`, `AUDIT_HMAC_KEY`.

Docker/PostgreSQL deployment: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Tests

`pytest` runs on SQLite by default. To run the same suite (plus PostgreSQL-only trigger tests) on PostgreSQL:

```bash
alembic upgrade head   # against an empty test database
TEST_DATABASE_URL=postgresql+asyncpg://user:pw@127.0.0.1/testdb pytest
```

Last run: **115 passed / 3 skipped on SQLite; 118 passed on PostgreSQL 16**. `pip-audit -r requirements.txt` reported no
known vulnerabilities on the day of writing (re-run in CI).

## Layout

```
app/
  config.py  compliance.py  security.py  money.py  fa.py  admin_auth.py  ratelimit.py  runtime.py  worker.py  cli.py
  db/        models.py (schema), session.py, base.py
  odds/      types, normalize, pricing (pure), service (ingest + quotes), providers/{theoddsapi,mock}
  results/   result sources (2-source settlement verification)
  services/  betting, wallet, receipts, settlement, claims, audit, opconfig (signed config), customers
  payments/  usdt.py (mock chain, replay protection, gate-guarded withdrawals)
  bot/       callbacks (strict codec), handlers, keyboards, views, middlewares, delivery (pin), notifier
  web/       main.py (webhook), admin.py (API), console.html
alembic/     0001_initial_schema.py (tables + PostgreSQL append-only triggers)
docs/        ARCHITECTURE, ODDS_PROVIDERS, SECURITY, DEPLOYMENT, DISASTER_RECOVERY, COMPLIANCE_CHECKLIST
tests/       118 tests
```

## Honest limitations

* Persian copy was written by an AI and **must be reviewed by a native speaker** before any user sees it.
* Result data comes from odds-vendor score feeds, which are **not official league data**; a real operator needs
  licensed official data. Only one real result source exists in this build, so real-feed settlements need an admin's
  second-source decision (the demo uses two named views of the synthetic mock feed).
* Provider capabilities/prices are documented only as far as they could be verified — see `docs/ODDS_PROVIDERS.md`.
* Not perfectly secure. See `docs/SECURITY.md` ("Known gaps") and the launch blockers in the compliance checklist.
