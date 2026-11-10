# Security documentation

No system is "perfectly secure". This documents the controls that exist, how each was tested, and the known gaps.

## Controls (requirement → implementation → test)

| Requirement | Implementation | Tests |
|---|---|---|
| Strict input validation | `money.parse_stake` regex; Pydantic models with bounds on admin API; callback codec with per-verb regex; 64-byte limit | `test_pricing`, `test_bot_flow::test_callback_codec_is_strict` |
| Parameterised SQL | SQLAlchemy Core/ORM only; no string-built SQL (only static DDL in the migration) | forged-callback test with SQL payloads |
| Telegram webhook secret | secret **path** + `X-Telegram-Bot-Api-Secret-Token`, constant-time compare, 1 MB body cap; unconfigured secrets disable the endpoint | `test_web` |
| Replay protection | `update_id` SET-NX dedupe; admin TOTP step can't be reused; deposit `(chain, tx, log_index)` unique; claim/settlement/ledger unique keys | `test_web`, `test_security`, `test_claims` |
| Callback tampering | callbacks carry only opaque ids; acting user from Telegram `from_user`; prices/stakes/outcomes always re-read server-side; ownership filters on drafts/bets/claims | `test_bot_flow`, `test_betting` |
| Idempotency / races | draft claim by conditional UPDATE; unique `idempotency_key`; customer row lock; guarded wallet UPDATE + CHECK ≥ 0 | concurrent-confirm, overdraw and daily-limit tests (SQLite **and** PostgreSQL) |
| Admin: allowlist, RBAC, 2FA | env Telegram-ID allowlist (also enforced at login, session use and creation) → optional IP CIDR allowlist → scrypt password → TOTP (±1 step, no reuse, 5 failures ⇒ 15-min lock) → 256-bit opaque session stored as SHA-256, 30-min TTL → per-route permission | `test_security`, `test_web` |
| Rate limiting | per-user (20/10 s) bot throttle; admin login 10/min/IP; Redis fixed window | `test_bot_flow`, `test_web` |
| Secrets | env only; `SecretStr`; Fernet-encrypted TOTP secrets; log redaction filter; httpx URL logging off; `.env` git-ignored; prod refuses weak/missing keys, SQLite, or `REAL_MONEY_ENABLED=true` | `test_security::test_log_redaction` |
| Immutable financial audit | HMAC hash-chained `audit_events`; PostgreSQL triggers make ledger, audit, settlements, results, outcomes, signed configs append-only, bet terms/receipts immutable, security events ack-only | `test_security`, `test_pg_triggers` |
| Signed, versioned config | `signed_configs` HMAC; fail-closed on tamper | `test_security::test_tampered_signed_config_fails_closed` |
| Compliance gates | constant `REAL_MONEY_CODE_PATH_IMPLEMENTED=False` + env + signed refs; payment factory only ever returns the mock; withdrawals always raise and raise a security event | `test_security` (gate-bypass tests incl. flipping the constant) |
| External data untrusted | defensive parsers (shape checks, Decimal parsing, finite/range checks), future timestamps rejected, payload-shape failures count as provider errors | `test_providers_and_worker`, `test_pricing` |
| Monitoring | `security_events` (failed logins, lockouts, bad webhook secret, malformed callbacks, result disputes, fake/replayed deposits, tampering, velocity) surfaced at `/admin/api/security/alerts` | `test_web` |
| Dependency scanning | `pip-audit -r requirements.txt` (clean at time of writing); `requirements.lock` pins the tested set | run in CI |

## Defence notes

* Docker image runs as a non-root user; Postgres/Redis are on an internal network only; the API binds to localhost and
  expects a TLS-terminating reverse proxy.
* `X-Forwarded-For` is **not trusted**; behind a proxy the IP allowlist would see the proxy address (see gaps).
* OpenAPI/Swagger is disabled when `ENVIRONMENT=prod`; every response carries no-store / nosniff / frame-deny / CSP headers.
* Admin console renders data with `textContent` only (no HTML injection from stored text).

## Known gaps / risks (be honest about these)

1. **No independent penetration test or code audit.** Required before any real-money use.
2. Admin sessions are bearer tokens in `Authorization` held by JS in memory; no CSRF surface, but also no hardware-key
   (WebAuthn) support. Unknown-user logins return faster than known-user failures (minor timing oracle).
3. IP allowlist needs a trusted-proxy mode before deployment behind a load balancer (not implemented).
4. Redis has no password in the compose file (internal network only); use ACLs/TLS in production. FSM state is held in
   Redis (loss ⇒ customers re-select, no financial effect).
5. Single-region, single-DB design; no HSM/KMS — `SECRETS_KEY` and the HMAC keys live in env vars. Use a secrets
   manager and rotate; a key rotation procedure for the HMAC keys is **not** implemented (old rows would need
   key-versioning).
6. SQLite (dev/test) lacks the append-only triggers; those guarantees are PostgreSQL-only and tested only there.
7. Triggers do not stop a DB superuser (`session_replication_role`); the hash-chained audit log, receipt MACs and signed
   config exist to make such tampering *detectable* — ship the audit export off-host regularly.
8. Telegram messages are not end-to-end encrypted; customers' IDs/usernames are personal data (see retention below).
9. The Persian copy has not been reviewed by a native speaker; number/date rendering uses Persian digits and Jalali
   dates but was verified only by unit/flow tests, not on real clients.
10. Load/performance and fuzz testing were not done. Odds credit budgets must be sized per plan.

## Data retention (defaults to confirm with counsel)

Operational tables are pruned by the worker: processed updates 2 days, API usage 90 days, expired admin sessions 1 day,
expired drafts 1 day. Financial, audit and bet records are retained; `compliance.anonymize_customer` removes username
and country on request while keeping the financial trail.
