# Legal & compliance readiness checklist — and blockers to any real-money launch

> This is an engineering checklist, **not legal advice.** Online betting is licensed/prohibited differently in every
> jurisdiction (and unlawful in some, including for customers resident there). Obtain qualified local counsel *before*
> any real-money step, including marketing. The server refuses real-money operation until **all** of this is done.

## Hard blockers (nothing real-money may happen until each is closed)

| # | Blocker | State in this build |
|---|---|---|
| 1 | Gambling licence(s) in each target jurisdiction; written legal opinion on legality of serving customers there (and on offering in Persian to residents of restricted countries) | ❌ none — `compliance.approved_jurisdictions` empty |
| 2 | Independent security assessment / penetration test and code audit; remediation of findings | ❌ not done |
| 3 | Licensed, audited custody / payment provider for crypto (no self-held hot wallet; withdrawals with segregation of duties); verified USDT contract & decimals from Tether / BscScan primary sources (the address in `payments/usdt.py` is unverified) | ❌ mock only |
| 4 | KYC / AML programme, sanctions & PEP screening, source-of-funds rules, Travel-Rule handling, MLRO, suspicious-activity reporting | ❌ integration stubs only (`compliance.py`) |
| 5 | Age verification (18+/local minimum) with a real provider; blocking of minors | ❌ stub returns True |
| 6 | Official / licensed sports data and odds with redistribution rights; contractual second result source; documented void/cancellation rules | ❌ vendor feeds, ToS unreviewed |
| 7 | Reviewed Terms & Conditions, privacy policy, complaint procedure/ADR, bonus rules, **claim-limitation clause** — the 10-day window must be legally validated per jurisdiction; until then it only triggers admin review and **never forfeits** | ⚠️ implemented safely; text unreviewed |
| 8 | Responsible-gambling programme meeting local rules: deposit/stake/loss limits, cooling-off, self-exclusion (incl. cross-operator registers where required), reality checks, help-line links | ⚠️ daily stake limit + self-exclusion only |
| 9 | Data-protection compliance (GDPR/UK GDPR/local): lawful basis, DPIA, retention schedule, data-subject requests, processor contracts, cross-border transfer basis | ⚠️ retention + anonymise primitives only |
| 10 | Native-speaker review of all Persian copy; accessibility review; app-store/Telegram platform policy review for gambling | ❌ not done |
| 11 | Incident response plan, 24×7 on-call, fraud/collusion monitoring, bet-limit risk management, liability exposure caps | ❌ basic velocity alert only |
| 12 | Tax and accounting treatment of gaming duty, VAT, crypto gains; financial audit trail reconciliation procedures | ❌ |

## Built-in safeguards (what the code already does)

- [x] Demo-only master switch is source code, not config; env flag + signed approvals also required; prod start refuses `REAL_MONEY_ENABLED=true`
- [x] Withdrawal requests always blocked and logged as security events; no hot-wallet; no private keys/seed phrases requested or stored
- [x] Pre-match only; server-side cutoff (`bet_cutoff_s`) and re-validation at confirmation
- [x] Winning claims never forfeit; deadline ⇒ `admin_review`; late requests accepted and flagged
- [x] Settlement requires two agreeing sources or an audited admin decision; corrections append-only with reasons
- [x] Customer can only lower daily limit; self-exclusion cannot be shortened; excluded customers cannot bet
- [x] Jurisdiction block-list hook (`blocked_countries`) and country field on customers (no geolocation/KYC wired)
- [x] Complaints recorded (`complaints` table, admin list) — SLA/escalation process to be defined
- [x] Immutable financial audit trail with export (`/admin/api/audit/export`) and chain verification
- [x] Margin transparent, signed, versioned, audited; customer UI never claims prices are a bookmaker's

## Pre-launch work plan (suggested order)

1. Legal scoping & licence strategy → decide jurisdictions (drives everything else).
2. Choose licensed data/odds suppliers; sign contracts; build/verify second result source.
3. Choose custody/payment provider; implement `payments/` real provider behind the gate **in a separate reviewed change**
   (set `REAL_MONEY_CODE_PATH_IMPLEMENTED` only in that change, with tests for reconciliation, confirmations, reorgs,
   dust, wrong-token, replay, chargeback-equivalents, and dual-approval withdrawals).
4. KYC/AML/sanctions/age integrations; transaction-monitoring rules; MLRO sign-off.
5. Full responsible-gambling suite; T&C / privacy / complaints; Persian copy review.
6. Independent pen-test + remediation; load test; DR drill; incident runbooks.
7. Regulator/licensor sign-off, then a limited, capped soft launch.
