"""Transparent price construction. Pure functions (no I/O) so every number is reproducible & testable.

For each outcome we use only valid, fresh quotes from distinct mapped bookmakers:
  best   = max(odds)                       (best available market price)
  median = median(odds)                    (robust consensus)
Fair probabilities come from the per-outcome medians, normalised to sum to 1 (proportional de-vig).
Customer price = 1 / (fair_p * (1 + margin)), rounded DOWN to 2 decimals and CAPPED at the best market
price. The resulting overrounds are validated against configured bands; otherwise the market is withheld.
The customer price is an internal proposed price - it is never presented as a bookmaker quote.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, getcontext
from statistics import median_low

from app.money import MIN_ODDS_MILLI
from app.odds.normalize import MARKET_SELECTIONS
from app.odds.types import NormQuote, Rejected

getcontext().prec = 28
BP = Decimal(10000)


@dataclass
class SelectionPrice:
    selection: str
    odds_milli: int
    best_milli: int
    median_milli: int
    n_quotes: int
    calc: dict


@dataclass
class MarketPrice:
    market: str
    ok: bool
    reason: str | None = None
    selections: list[SelectionPrice] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _implied_sum_bp(odds_milli: list[int]) -> int:
    s = sum(Decimal(1000) / Decimal(o) for o in odds_milli)
    return int((s * BP).to_integral_value(rounding=ROUND_FLOOR))


def price_market(market: str, quotes: list[NormQuote], rejected: list[Rejected], cfg: dict, now: datetime
                 ) -> MarketPrice:
    sels = MARKET_SELECTIONS[market]
    max_age = cfg["max_quote_age_s"]
    per_sel: dict[str, list[dict]] = {s: [] for s in sels}
    excluded: list[dict] = [{"bookmaker": r.bookmaker, "selection": r.selection, "reason": r.reason}
                            for r in rejected if r.market == market]

    # one quote per canonical bookmaker per selection: keep the freshest
    latest: dict[tuple[str, str], NormQuote] = {}
    for q in quotes:
        if q.market != market:
            continue
        k = (q.bookmaker, q.selection)
        if k not in latest or q.last_update > latest[k].last_update:
            latest[k] = q
    for (bm, sel), q in latest.items():
        age = (now - q.last_update).total_seconds()
        if age > max_age:
            excluded.append({"bookmaker": bm, "selection": sel, "reason": f"stale({int(age)}s)"})
            continue
        if age < -300:   # timestamps from the future => untrustworthy
            excluded.append({"bookmaker": bm, "selection": sel, "reason": "timestamp_in_future"})
            continue
        per_sel[sel].append({"bookmaker": bm, "provider_key": q.provider_bookmaker_key,
                             "odds_milli": q.odds_milli, "last_update": q.last_update.isoformat()})

    base = {"excluded": excluded, "margin_bp": cfg["margin_bp"], "computed_at": now.isoformat()}
    for s in sels:
        if len(per_sel[s]) < cfg["min_quotes"]:
            return MarketPrice(market, False, f"insufficient_quotes:{s}:{len(per_sel[s])}<{cfg['min_quotes']}",
                               summary={**base, "valid_counts": {x: len(per_sel[x]) for x in sels}})

    medians: dict[str, int] = {}
    bests: dict[str, int] = {}
    for s in sels:
        vals = sorted(q["odds_milli"] for q in per_sel[s])
        medians[s] = median_low(vals) if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) // 2
        bests[s] = vals[-1]

    mkt_over = _implied_sum_bp(list(medians.values()))
    if not cfg["mkt_overround_min_bp"] <= mkt_over <= cfg["mkt_overround_max_bp"]:
        return MarketPrice(market, False, f"market_overround_out_of_band:{mkt_over}",
                           summary={**base, "market_overround_bp": mkt_over})

    inv = {s: Decimal(1000) / Decimal(medians[s]) for s in sels}
    total = sum(inv.values())
    margin = Decimal(cfg["margin_bp"]) / BP
    out: list[SelectionPrice] = []
    for s in sels:
        fair_p = inv[s] / total
        cust_p = fair_p * (Decimal(1) + margin)
        raw_odds = Decimal(1) / cust_p
        cust_milli = int((raw_odds * 100).to_integral_value(rounding=ROUND_FLOOR)) * 10   # floor to 0.01
        cust_milli = min(cust_milli, bests[s])            # never better than the best real quote
        cust_milli = max(cust_milli, MIN_ODDS_MILLI)
        out.append(SelectionPrice(
            s, cust_milli, bests[s], medians[s], len(per_sel[s]),
            {**base, "quotes": sorted(per_sel[s], key=lambda x: x["bookmaker"]), "best_milli": bests[s],
             "median_milli": medians[s], "fair_probability": str(fair_p.quantize(Decimal("0.000001"))),
             "uncapped_customer_odds": str(raw_odds.quantize(Decimal("0.0001"))),
             "customer_milli": cust_milli}))
    cust_over = _implied_sum_bp([o.odds_milli for o in out])
    if not cfg["cust_overround_min_bp"] <= cust_over <= cfg["cust_overround_max_bp"]:
        return MarketPrice(market, False, f"customer_overround_out_of_band:{cust_over}",
                           summary={**base, "market_overround_bp": mkt_over, "customer_overround_bp": cust_over})
    summary = {**base, "market_overround_bp": mkt_over, "customer_overround_bp": cust_over}
    for o in out:
        o.calc["market_overround_bp"] = mkt_over
        o.calc["customer_overround_bp"] = cust_over
    return MarketPrice(market, True, None, out, summary)
