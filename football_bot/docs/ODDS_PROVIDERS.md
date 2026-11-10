# Odds & data providers — what was verified and what was not

Research for this build used web-search excerpts of vendor documentation (no vendor account, no live API calls, no
terms-of-service review). **Nothing below is a substitute for reading the current docs, pricing and licence terms
before buying.** Items are marked ✅ (stated in an official page excerpt), 🟡 (vendor marketing / third-party claim),
❓ (not found / not verified).

## The Odds API — https://the-odds-api.com (**implemented**: `app/odds/providers/theoddsapi.py`)

* ✅ v4 REST API; regions `us, us2, uk, au, eu`; multiple regions comma-separated; decimal odds via `oddsFormat=decimal`;
  endpoints `/sports/{sport}/odds` and `/sports/{sport}/scores`.
* ✅ Credit cost for current odds = markets × regions (so `h2h,totals` × `eu,uk` = 4 credits per league call).
  🟡 Per-event "additional markets" (we use it for BTTS) bill per event; at ~10 events × 8 leagues × 2 regions each
  refresh that is a large credit spend. `ODDS_REFRESH_SECONDS` and the BTTS fetch flag exist for budgeting.
* ❓ Exact bookmaker keys per region, whether Bet365 / Betano / Bwin / Marathonbet / 888sport are available, BTTS
  availability per league, numeric rate limits, and redistribution/display licence terms. The code reads quota headers
  (`x-requests-remaining` / `x-requests-used`) into `api_usage` for the admin health page, so real coverage and spend are
  observable on day one.
* The `/scores` feed is a data feed, **not** official league data.

## Odds-API.io — https://odds-api.io (**not implemented**)

* ✅ Docs index mentions 265 bookmakers (242 active) across 34 sports; v3 events endpoint takes `sport=football`;
  API key in the URL; rate-limit headers and HTTP 429.
* 🟡 "5,000 requests/hour" and "250+ bookmakers" come from the vendor's own comparison page, not the API reference.
* ❓ Bookmaker-by-name coverage for the ten targets, response schema, pricing table, licence terms. Not built because
  inventing an adapter against an unseen schema would violate the "don't invent API capabilities" requirement.
  It is the obvious candidate for the fallback slot once its schema is read (`OddsProvider` is a 2-method interface).

## API-Football — https://www.api-football.com (**not implemented**)

* ❓ The official documentation was not returned by search; plan limits, odds endpoint and bookmaker list are
  unverified. One third-party listing says odds responses are paginated at 10 results per page — unconfirmed.
  Worth evaluating as the **second result source** for settlement (it also provides fixtures/results).

## Sportmonks — https://www.sportmonks.com (**not implemented**)

* ✅ Pre-match odds endpoints (all odds, by fixture, by fixture+bookmaker, by fixture+market, last-updated);
  "Premium Odds" is a separate add-on powered by TXOdds (180+ bookmakers, 20+ markets); standard pre-match odds
  refresh roughly every 10 minutes (so up to ~20 min worst-case staleness vs. our 15-minute `max_quote_age_s`).
* 🟡 Odds are a paid add-on (a third-party blog cites €14–€69/month standard; plan prices unverified).

## Choice made

* **Primary: The Odds API** — the only one whose odds/scores endpoints and quota accounting could be confirmed enough to
  write a defensive adapter. **Fallback:** the interface supports one (`ODDS_FALLBACK_PROVIDER`), fixture matching
  across providers is implemented and tested (normalised team names + kickoff ±3 h); no second real adapter ships.
* **Ten bookmakers:** `opconfig.DEFAULT_CONFIG["bookmaker_aliases"]` maps canonical names → *candidate* provider keys.
  Only bookmakers that actually return fresh, valid prices are used; the customer never sees a bookmaker name, only
  "number of valid sources", best and median prices. A missing bookmaker is simply absent — never fabricated.
* **Mock provider:** synthetic prices for offline demo/tests only; clearly separate (`ODDS_PRIMARY_PROVIDER=mock`).

## Before relying on any provider

1. Read the ToS for *commercial display / redistribution / use in a betting product* — many odds feeds forbid or
   price this differently (a licensing blocker, not a coding task).
2. Confirm real coverage of the ten bookmakers for the eight competitions with a trial key; check
   `GET /admin/api/odds/health` and the `excluded` list stored in every `price_quotes.calc`.
3. Contract an official-data result source for settlement (see compliance checklist).
