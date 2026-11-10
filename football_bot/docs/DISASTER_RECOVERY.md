# Backup & disaster recovery

Targets for the demo (adjust for production): **RPO ≤ 24 h** (daily dump; add WAL archiving/PITR for < 15 min),
**RTO ≈ 1–2 h** (rebuild from images + restore).

## What to protect

| Asset | How |
|---|---|
| PostgreSQL | `backup` service: daily `pg_dump -Fc` → `./backups` (14-day local retention). **Copy off-host and encrypt** (e.g. `age`/restic to object storage in another region). For production add continuous WAL archiving (pgBackRest/WAL-G). |
| Secrets (`SECRETS_KEY`, `RECEIPT_HMAC_KEY`, `CONFIG_SIGNING_KEY`, `AUDIT_HMAC_KEY`, `BOT_TOKEN`, API keys) | Store in a secrets manager; keep an offline sealed copy of the four app keys. Without them: no admin 2FA, receipts/audit/config cannot be verified. |
| Audit export | `GET /admin/api/audit/export` (NDJSON with chain status) — ship weekly to write-once storage so tampering by a DB superuser is detectable. |
| Redis | Non-critical (rate limits, FSM, dedupe). AOF is on; loss only resets in-progress dialogs. |

## Restore procedure

1. Provision host, install Docker, restore `.env` and keys from the secrets manager.
2. `docker compose up -d postgres`; create an empty DB.
3. `pg_restore -h … -U footballbot -d footballbot --clean --if-exists footballbot_<ts>.dump`
4. `docker compose up -d migrate` (applies any newer migrations), then `api worker`.
5. **Verify integrity:** `python -m app.cli verify-audit` must print `audit chain OK`; spot-check a few receipts
   (`receipts.verify`) and confirm `sum(ledger) == wallet balance` per customer.
6. Re-register the Telegram webhook (automatic on API start) and review `security_events` for the outage window.
7. Reconcile: bets placed during the gap were never confirmed to customers if they were not in the dump — customers
   keep their Telegram receipt messages, which carry the bet id and integrity code for dispute resolution.

## Drills

Quarterly: restore the latest dump into a scratch environment, run `verify-audit`, run the test-suite's
integrity queries, and record elapsed time against the RTO. A backup that has never been restored is not a backup.

## Failure scenarios

* **Odds provider down:** no new prices; existing quotes expire after `price_valid_s` (20 min); bets are refused
  (tested). Bot shows "no matches with valid odds".
* **Config/key mismatch after restore:** signature verification fails ⇒ pricing and betting stop (fail closed) with a
  critical alert. Restore the correct `CONFIG_SIGNING_KEY`; do not re-sign unless the incident is understood.
* **Duplicate worker / double delivery:** all jobs and notifications are idempotent (unique keys).
