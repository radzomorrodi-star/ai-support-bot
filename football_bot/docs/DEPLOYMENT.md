# Deployment (demo mode)

Requirements: Docker + Compose v2, a domain with TLS (for webhook mode), a bot token from @BotFather.

## 1. Configure

```bash
cd football_bot
cp .env.example .env && chmod 600 .env
# generate and paste (each independently):
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # SECRETS_KEY
openssl rand -hex 32   # RECEIPT_HMAC_KEY      openssl rand -hex 32   # CONFIG_SIGNING_KEY
openssl rand -hex 32   # AUDIT_HMAC_KEY        openssl rand -hex 32   # POSTGRES_PASSWORD (also in DATABASE_URL)
openssl rand -hex 24   # WEBHOOK_SECRET_TOKEN  openssl rand -hex 24   # WEBHOOK_PATH_SECRET
```

Set `ENVIRONMENT=prod`, `BOT_TOKEN`, `ADMIN_ALLOWLIST=<your Telegram id>`, and `ODDS_PRIMARY_PROVIDER` (`mock` for a
pure demo, `the_odds_api` + `THE_ODDS_API_KEY` for real prices). **Back up the four keys now** (password manager /
KMS): losing `SECRETS_KEY` locks admins out of 2FA; losing the HMAC keys makes receipts/audit/config unverifiable.
Never set `REAL_MONEY_ENABLED=true` (prod start-up refuses it).

## 2. Start

```bash
docker compose up -d --build        # postgres, redis, migrate (alembic), api, worker, backup
docker compose logs -f worker api
docker compose run --rm api python -m app.cli bootstrap          # competitions + signed default config
docker compose run --rm -it api python -m app.cli create-admin --telegram-id <id> --role superadmin
```

Scan the printed `otpauth://` URI into an authenticator app immediately (shown once).

## 3. Telegram mode

* **Polling** (default; simplest): `TELEGRAM_MODE=polling`; the worker runs the bot.
* **Webhook**: `TELEGRAM_MODE=webhook`, `WEBHOOK_BASE_URL=https://bot.example.com`; put Caddy/nginx with TLS in front of
  `127.0.0.1:8000` and proxy only `/telegram/webhook/*`, `/healthz` (and, if desired, `/admin/*` restricted by IP/VPN).
  The API registers the webhook with the secret token on start-up. **Run exactly one of polling/webhook.**

Pinning works in private chats without extra rights; if Telegram refuses, the customer is told and the receipt stays in
"🎟 شرط‌های من".

## 4. Verify

```bash
curl -s https://bot.example.com/healthz                     # {"ok":true,"mode":"demo"}
docker compose run --rm api python -m app.cli verify-audit   # audit chain OK
```

Open the bot, `/start`: you should see your Telegram ID as the customer number and a 1,000 demo balance.
Run the test-suite from a dev checkout (`pip install -r requirements-dev.txt && pytest`), not inside the image.
Admin console: `https://…/admin/console` (restrict at the proxy); the API is documented in `app/web/admin.py`.

## 5. Operate

* Margin change: `POST /admin/api/config/margin` (superadmin) — new signed version + audit entry; never edit rows.
* Suspend a market/fixture: `POST /admin/api/markets/suspend`; lift with `/markets/lift/{id}`.
* Disputed results appear as `result_dispute` security alerts; decide via `/settlement/decide`; fix finalised results via
  `/settlement/correct` (reason mandatory, audited).
* Upgrades: `git pull && docker compose up -d --build` (the `migrate` service runs Alembic first).
* Dependency audit in CI: `pip-audit -r requirements.txt`.
