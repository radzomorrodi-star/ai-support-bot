"""Receipts: immutable JSON body + HMAC-SHA256 integrity tag, stored independently of Telegram messages."""
from __future__ import annotations

from typing import Any

from app import fa
from app.config import Settings
from app.db.models import Bet, Event, Receipt
from app.money import profit_minor
from app.security import canonical, hmac_hex, hmac_ok

COMP_NAMES = fa.COMP_FA


def build_body(bet: Bet, ev: Event, customer_tz: str) -> dict[str, Any]:
    return {
        "bet_id": bet.id, "customer_id": bet.customer_id,
        "event": {"id": ev.id, "home": ev.home, "away": ev.away, "competition_key": ev.competition_key,
                  "kickoff_utc": bet.kickoff_utc.isoformat()},
        "market": bet.market, "selection": bet.selection, "odds_milli": bet.odds_milli,
        "stake_minor": bet.stake_minor, "payout_minor": bet.payout_minor,
        "profit_minor": profit_minor(bet.stake_minor, bet.odds_milli),
        "created_utc": bet.created_at.isoformat(), "customer_tz": customer_tz,
        "terms_version": bet.terms_version, "status_at_issue": "open", "quote_id": bet.quote_id, "demo": True,
    }


def make_receipt(settings: Settings, body: dict[str, Any]) -> Receipt:
    canon = canonical(body)
    return Receipt(bet_id=body["bet_id"], body=body, body_canonical=canon,
                   integrity_hash=hmac_hex(settings.receipt_hmac_key.get_secret_value(), canon, "RECEIPT_HMAC_KEY"))


def verify(settings: Settings, r: Receipt) -> bool:
    return (canonical(r.body) == r.body_canonical
            and hmac_ok(settings.receipt_hmac_key.get_secret_value(), r.body_canonical, r.integrity_hash,
                        "RECEIPT_HMAC_KEY"))


def render(r: Receipt, current_status: str) -> str:
    from datetime import datetime
    b = r.body
    created = datetime.fromisoformat(b["created_utc"])
    ko = datetime.fromisoformat(b["event"]["kickoff_utc"])
    tz = b["customer_tz"]
    e = b["event"]
    return fa.T["receipt"].format(
        bet=b["bet_id"], cid=b["customer_id"], title=fa.match_title(e["home"], e["away"]),
        comp=fa.COMP_FA.get(e["competition_key"], e["competition_key"]), market=fa.MARKET_FA[b["market"]],
        sel=fa.selection_label(b["market"], b["selection"], e["home"], e["away"]),
        odds=fa.odds(b["odds_milli"]), stake=fa.money(b["stake_minor"]), payout=fa.money(b["payout_minor"]),
        profit=fa.money(b["profit_minor"]), utc=fa.utc_stamp(created), local=fa.jdatetime_full(created, tz),
        kickoff=f"{fa.jdatetime_full(ko, tz)} ({fa.utc_stamp(ko)})", status=fa.STATUS_FA[current_status],
        terms=fa.digits(b["terms_version"]), hash=r.integrity_hash[:16], demo=fa.DEMO_BANNER)
