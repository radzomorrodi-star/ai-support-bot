from __future__ import annotations

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup

from app import fa
from app.bot.callbacks import Cb

BTN = fa.BTN


def b(text: str, verb: str, arg: str | None = None) -> B:
    return B(text=text, callback_data=Cb(verb, arg).pack())


def kb(rows: list[list[B]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav(back: tuple[str, str | None] | None = None) -> list[B]:
    row = []
    if back:
        row.append(b(BTN["back"], *back))
    row.append(b(BTN["home"], "h"))
    return row


def main_menu() -> InlineKeyboardMarkup:
    return kb([[b(BTN["matches"], "ml"), b(BTN["leagues"], "lg")],
               [b(BTN["mybets"], "mb"), b(BTN["results"], "rs")],
               [b(BTN["wallet"], "wl"), b(BTN["terms"], "tm")],
               [b(BTN["support"], "sp")]])


def home_only() -> InlineKeyboardMarkup:
    return kb([nav()])


def confirm_kb(draft_id: str) -> InlineKeyboardMarkup:
    return kb([[b(BTN["confirm"], "cf", draft_id), b(BTN["cancel"], "cx", draft_id)], [b(BTN["home"], "h")]])


def cancel_kb(draft_id: str) -> InlineKeyboardMarkup:
    return kb([[b(BTN["cancel"], "cx", draft_id)]])


def claim_kb(bet_id: str) -> InlineKeyboardMarkup:
    return kb([[b(BTN["claim"], "cl", bet_id)], [b(BTN["mybets"], "mb"), b(BTN["home"], "h")]])


def support_kb() -> InlineKeyboardMarkup:
    return kb([[b(BTN["complaint"], "cm")], [b(BTN["exclude"], "ex"), b(BTN["limit"], "lm")], nav()])


def exclusion_kb() -> InlineKeyboardMarkup:
    return kb([[b(fa.digits(f"{d} روز"), "exd", str(d)) for d in (1, 7)],
               [b(fa.digits(f"{d} روز"), "exd", str(d)) for d in (30, 180)], nav(("sp", None))])


def limit_kb() -> InlineKeyboardMarkup:
    return kb([[b(fa.money(u * 100), "dl", str(u)) for u in (50, 100, 500)], nav(("sp", None))])
