# Architecture

```
Telegram ──webhook/polling──▶ aiogram Dispatcher ──▶ handlers (thin) ──▶ services ──▶ PostgreSQL
                                   │ middlewares: update-id dedupe (Redis NX) → throttle → identify/register
Odds APIs ──▶ providers ──▶ normalize ──▶ pricing (pure) ──▶ price_quotes (immutable snapshots, full calc JSON)
Result sources (≥2 must agree) ──▶ event_results ──▶ event_outcomes ──▶ settlements ──▶ wallet / claims / outbox
Worker: odds refresh · result ingest · settle · claim sweep · notification outbox · housekeeping (Redis job locks)
FastAPI: /telegram/webhook/{secret}   /admin/api/*   /admin/console   /healthz
```

Layering: `bot/` (Telegram only) → `services/` (business rules, no Telegram imports) → `db/`. `odds/pricing.py` and
`services/settlement.evaluate` are pure functions. Money = integer minor units (1 demo-USDT = 100); odds = integer
thousandths; payouts `stake × odds ÷ 1000` rounded **down**. No float touches money (floats appear only in the
synthetic mock-feed generator and in tests).

## Pricing (transparent & reproducible)

Per outcome: collect one quote per mapped bookmaker (freshest), drop stale (> `max_quote_age_s`), future-dated,
suspended, missing or out-of-range prices; require ≥ `min_quotes` per outcome. `best = max`, `median = median`.
Fair probabilities = normalised `1/median`. **Customer price = 1 / (fair_p × (1 + margin))**, floored to 0.01 and
**capped at the best real quote**. Markets are withheld when the median overround or the resulting customer overround
leaves its configured band. The margin therefore applies to the *de-vigged* probabilities: customer overround ≈
`100% + margin` regardless of how wide the bookmakers' own margins are (it can be lower than the bookmakers' median
overround — an operator pricing choice, visible in every stored calculation). Each `price_quotes` row stores all quotes
with source timestamps, exclusions with reasons, best/median/fair probability/overrounds and the config version.
The customer UI shows only the proposed price, source *count*, best & median — never a bookmaker name, never implying
the price is any bookmaker's.

The margin lives in a **signed, versioned, append-only config** (`signed_configs`, HMAC-SHA256). A row that fails
verification stops pricing and betting (fail closed) and raises a critical security event. Changing it requires the
`config:write` permission and writes an audit event (bounded 0–20 %).

## Bet lifecycle

1. `sl:<quote_id>` → `create_draft` (re-checks event open, cutoff, suspension, quote still current & unchanged).
2. stake text → strict parse (digits only, ≤2 decimals) → `set_stake` (range + balance).
3. `cf:<draft_id>` → `confirm_bet`, **one transaction**: atomically claim the draft (`UPDATE … WHERE consumed=false`,
   exactly one concurrent caller wins) → lock the customer row → verify signed config, customer status/exclusion/
   jurisdiction, event `scheduled` and `kickoff > now + bet_cutoff_s`, market not suspended, current price **equal** to
   the price shown, stake bounds, daily limit → guarded wallet debit (`UPDATE … WHERE balance + Δ ≥ 0`) → insert bet,
   receipt (+HMAC) and a hash-chained audit event. Any failure rolls everything back (draft stays usable).
   A repeat confirmation returns the existing bet (`created=False`) — no second debit, no second pin.
4. Receipt is sent and pinned best-effort; failure is reported to the customer and the receipt remains in "my bets".

## Settlement

`ingest_results` (append-only `event_results`) → `decide_outcomes` (needs ≥ 2 *distinct* sources with identical
verdicts, else the event is flagged `result.dispute` once and waits for an admin decision) → `settle_pending`
(idempotent: unique `(bet, outcome, result)`, only `open` bets). Regular time only. `void` (stake refunded):
postponed / cancelled / abandoned. A win creates a **claim**; winnings are credited to the demo wallet only when an
admin approves the claim. Corrections (`apply_correction`) require `settlement:correct` + a reason, create a superseding
outcome and superseding settlements, reverse prior effects (claim cancel / refund clawback, partial if funds were
spent) and are audited; history is never edited. Admins cannot replace an existing outcome through the "decide" path.

## Claims

`pending_request → requested → approved|rejected`, or `pending_request → admin_review` at the 10-day deadline (never
forfeited; a customer can still request, flagged `late_request`). Reminders at 3 and 1 day(s) before the deadline
(`claim_reminder_days_before`). One claim per bet (unique key) and an atomic status transition prevent duplicates.

## Reliability

Customer messages go through a DB outbox (`notifications`, unique `dedupe_key`) drained by the worker with retries.
Worker jobs are idempotent and additionally take short Redis locks. Telegram updates are deduplicated by `update_id`.
