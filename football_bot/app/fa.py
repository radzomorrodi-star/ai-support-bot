"""Persian presentation helpers: digits, money, odds, Jalali dates, bidi isolation, all user strings."""
from __future__ import annotations

import html
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import jdatetime

from app.money import MINOR_PER_UNIT, odds_milli_to_decimal

RLM = "‏"
LRI, PDI = "⁦", "⁩"   # isolate Latin runs (team names) inside RTL text
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

CURRENCY = "تتر آزمایشی"


def digits(s: str) -> str:
    return s.translate(_FA)


def iso(text: str, plain: bool = False) -> str:
    """Wrap a possibly-Latin string so it keeps its own direction inside RTL text.
    External strings are HTML-escaped for messages (parse_mode=HTML); plain=True is for button labels."""
    return f"{LRI}{text if plain else html.escape(text, quote=False)}{PDI}"


def num(n: int) -> str:
    return digits(f"{n:,}").replace(",", "٬")


def money(minor: int) -> str:
    whole, frac = divmod(abs(minor), MINOR_PER_UNIT)
    sign = "-" if minor < 0 else ""
    body = f"{whole:,}".replace(",", "٬") + (f"٫{frac:02d}" if frac else "")
    return f"{digits(sign + body)} {CURRENCY}"


def odds(milli: int) -> str:
    return digits(f"{odds_milli_to_decimal(milli):.2f}").replace(".", "٫")


def pct_bp(bp: int) -> str:
    """Basis points -> Persian percent string using integer math only (e.g. 10526 -> ۱۰۵٫۲۶٪)."""
    return digits(f"{bp // 100}.{bp % 100:02d}").replace(".", "٫") + "٪"


def _tz(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo("UTC")


def jdate(dt: datetime, tz: str) -> str:
    local = dt.astimezone(_tz(tz))
    j = jdatetime.datetime.fromgregorian(datetime=local.replace(tzinfo=None))
    return digits(f"{j.year:04d}/{j.month:02d}/{j.day:02d}")


def jtime(dt: datetime, tz: str) -> str:
    return digits(dt.astimezone(_tz(tz)).strftime("%H:%M"))


def jdatetime_full(dt: datetime, tz: str) -> str:
    return f"{jdate(dt, tz)} {jtime(dt, tz)}"


def utc_stamp(dt: datetime) -> str:
    return digits(dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")) + " UTC"


# ---- vocabulary ------------------------------------------------------------------------------
COMP_FA = {
    "epl": "لیگ برتر انگلیس",
    "laliga": "لالیگا اسپانیا",
    "bundesliga": "بوندسلیگا آلمان",
    "seriea": "سری آ ایتالیا",
    "ligue1": "لیگ ۱ فرانسه",
    "ucl": "لیگ قهرمانان اروپا",
    "uel": "لیگ اروپا",
    "uecl": "لیگ کنفرانس اروپا",
}

MARKET_FA = {
    "1x2": "نتیجه مسابقه",
    "ou25": "بیش/کمتر از ۲٫۵ گل",
    "btts": "هر دو تیم گل بزنند",
}

# (market, selection) -> label; "1"/"2" resolved with team names in selection_label()
SEL_FA = {
    ("1x2", "draw"): "مساوی",
    ("ou25", "over"): "بیشتر از ۲٫۵ گل",
    ("ou25", "under"): "کمتر از ۲٫۵ گل",
    ("btts", "yes"): "بله",
    ("btts", "no"): "خیر",
}

STATUS_FA = {
    "open": "🟡 باز (در انتظار نتیجه)",
    "won": "🟢 برنده",
    "lost": "🔴 بازنده",
    "void": "⚪ باطل‌شده (بازگشت مبلغ)",
}
EVENT_STATUS_FA = {
    "scheduled": "برنامه‌ریزی‌شده",
    "live": "در حال برگزاری",
    "finished": "پایان‌یافته",
    "postponed": "به تعویق افتاده",
    "cancelled": "لغو شده",
    "abandoned": "نیمه‌تمام",
}
CLAIM_STATUS_FA = {
    "pending_request": "در انتظار درخواست شما",
    "requested": "درخواست ثبت شد",
    "admin_review": "نیازمند بررسی مدیریت",
    "approved": "تأیید و واریز آزمایشی انجام شد",
    "rejected": "رد شد",
}


def selection_label(market: str, selection: str, home: str, away: str, plain: bool = False) -> str:
    if market == "1x2":
        return {"home": f"برد {iso(home, plain)}", "away": f"برد {iso(away, plain)}", "draw": "مساوی"}[selection]
    return SEL_FA[(market, selection)]


def match_title(home: str, away: str, plain: bool = False) -> str:
    return f"{iso(home, plain)} - {iso(away, plain)}"


DEMO_BANNER = "🧪 حالت آزمایشی: هیچ پول واقعی‌ای در این ربات استفاده نمی‌شود."

T = {
    "welcome": (
        "🏠 به ربات پیش‌بینی فوتبال خوش آمدید\n\n"
        f"{DEMO_BANNER}\n"
        "شماره مشتری شما: <code>{cid}</code>\n"
        "موجودی آزمایشی: {bal}"
    ),
    "main_menu": "🏠 منوی اصلی",
    "choose_comp": "🏆 یک لیگ را انتخاب کنید:",
    "no_matches": "در حال حاضر مسابقه‌ای با ضرایب معتبر وجود ندارد.",
    "choose_match": "⚽ یک مسابقه را انتخاب کنید:",
    "match_card": "⚽ {title}\n\n🏆 {comp}\n\n📅 تاریخ مسابقه: {date}\n\n⏰ ساعت شروع: {time}\n\n{market}:",
    "price_note": (
        "ℹ️ ضرایب بالا قیمت پیشنهادی همین سامانه آزمایشی است و ضریب هیچ شرکت شرط‌بندی خاصی نیست."
    ),
    "ask_stake": (
        "🎯 انتخاب شما: {sel}\n📈 ضریب: {odds}\n\n"
        "مبلغ شرط آزمایشی را به عدد وارد کنید (حداقل {min}، حداکثر {max}).\nموجودی: {bal}"
    ),
    "bad_stake": "❌ مبلغ نامعتبر است. فقط عدد وارد کنید (مثلاً ۱۰ یا ۲۵٫۵۰).",
    "stake_range": "❌ مبلغ باید بین {min} و {max} باشد.",
    "no_funds": "❌ موجودی آزمایشی کافی نیست. موجودی: {bal}",
    "confirm": (
        "🧾 پیش‌نمایش شرط\n\n⚽ {title}\n🎯 {sel}\n📈 ضریب: {odds}\n"
        "💵 مبلغ: {stake}\n🏁 پرداخت احتمالی: {payout}\n✨ سود احتمالی: {profit}\n\n"
        "برای ثبت نهایی تأیید کنید. ضریب هنگام تأیید دوباره بررسی می‌شود."
    ),
    "placed": "✅ شرط شما ثبت شد.",
    "pin_ok": "📌 رسید در این گفتگو پین شد.",
    "pin_fail": "ℹ️ امکان پین‌کردن رسید وجود نداشت؛ رسید در «🎟 شرط‌های من» نگهداری می‌شود.",
    "cancelled": "❎ لغو شد.",
    "expired": "⌛ این درخواست منقضی شده است. لطفاً دوباره انتخاب کنید.",
    "err_started": "⛔ این مسابقه شروع شده یا در حال شروع است؛ شرط‌بندی بسته است.",
    "err_not_open": "⛔ این مسابقه دیگر برای شرط‌بندی در دسترس نیست.",
    "err_price": "⚠️ ضریب تغییر کرده است. ضریب جدید: {odds}\nلطفاً دوباره انتخاب کنید.",
    "err_suspended": "⛔ این بازار موقتاً معلق است.",
    "err_limit": "⛔ سقف مجاز مبلغ شرط شما رد می‌شود.",
    "err_excluded": "⛔ حساب شما در حالت محدودیت/خودمحرومی است.",
    "err_generic": "⚠️ خطایی رخ داد. لطفاً بعداً تلاش کنید.",
    "err_rate": "⏳ درخواست‌های شما زیاد است. کمی صبر کنید.",
    "no_bets": "هنوز شرطی ثبت نکرده‌اید.",
    "my_bets": "🎟 شرط‌های من:",
    "results": "📊 آخرین نتایج مسابقات:",
    "no_results": "نتیجه تأییدشده‌ای موجود نیست.",
    "wallet": (
        "💰 کیف پول آزمایشی\n\nموجودی: {bal}\n\n"
        "ℹ️ این کیف پول فقط برای آزمایش است. واریز و برداشت واقعی (USDT BEP20) فعال نیست."
    ),
    "terms": (
        "📋 قوانین و شرایط (نسخهٔ {ver})\n\n"
        "• این ربات در حالت آزمایشی است و پول واقعی استفاده نمی‌شود.\n"
        "• شرط‌بندی فقط پیش از شروع مسابقه ممکن است.\n"
        "• ضریب نهایی هنگام تأیید دوباره بررسی می‌شود.\n"
        "• ضرایب نمایش‌داده‌شده قیمت پیشنهادی سامانه است، نه ضریب یک شرکت مشخص.\n"
        "• پرداخت احتمالی به پایین‌ترین واحد گرد می‌شود.\n"
        "• در صورت لغو/تعویق/ناتمام ماندن مسابقه، شرط باطل و مبلغ بازگردانده می‌شود.\n"
        "• مهلت عملیاتی درخواست جایزه ۱۰ روز است؛ پس از آن جایزه از بین نمی‌رود و "
        "برای بررسی مدیریت علامت‌گذاری می‌شود.\n"
        "• ابزارهای بازی مسئولانه: سقف روزانه، خودمحرومی (در منوی پشتیبانی)."
    ),
    "support": "🆘 پشتیبانی\n\nیکی از گزینه‌ها را انتخاب کنید:",
    "complaint_ask": "متن شکایت یا پیام خود را بنویسید (حداکثر ۱۰۰۰ نویسه):",
    "complaint_ok": "✅ پیام شما ثبت شد. شمارهٔ پیگیری: <code>{id}</code>",
    "excl_ask": "⚠️ خودمحرومی: مدت را انتخاب کنید. در این مدت امکان ثبت شرط نخواهد بود.",
    "excl_ok": "✅ خودمحرومی تا {until} فعال شد.",
    "win_notice": (
        "🎉 شرط شما برنده شد!\n\n🎟 {bet}\n⚽ {title}\n🏁 جایزهٔ آزمایشی: {amount}\n\n"
        "📆 مهلت درخواست: {deadline}\nبرای ثبت درخواست دکمهٔ زیر را بزنید."
    ),
    "claim_reminder": (
        "⏰ یادآوری: برای جایزهٔ آزمایشی {amount} (شرط {bet}) هنوز درخواست ثبت نشده است.\n"
        "مهلت: {deadline}"
    ),
    "claim_ok": "✅ درخواست دریافت جایزه ثبت شد. پس از بررسی نتیجه اعلام می‌شود.",
    "claim_dup": "ℹ️ برای این شرط قبلاً درخواست ثبت شده است.",
    "claim_review": (
        "ℹ️ مهلت ۱۰ روزهٔ درخواست جایزهٔ {amount} (شرط {bet}) گذشته است. "
        "جایزهٔ شما از بین نرفته و برای بررسی مدیریت علامت‌گذاری شد."
    ),
    "loss_notice": "🔴 شرط {bet} بازنده شد.\n⚽ {title}",
    "void_notice": "⚪ شرط {bet} باطل شد و مبلغ {amount} بازگردانده شد.\n⚽ {title}",
    "receipt": (
        "🧾 رسید شرط\n\n"
        "🎟 شمارهٔ شرط: <code>{bet}</code>\n"
        "👤 شمارهٔ مشتری: <code>{cid}</code>\n"
        "⚽ مسابقه: {title}\n🏆 {comp}\n"
        "📊 بازار: {market}\n🎯 انتخاب: {sel}\n"
        "📈 ضریب پذیرفته‌شده: {odds}\n"
        "💵 مبلغ (آزمایشی): {stake}\n🏁 پرداخت احتمالی: {payout}\n✨ سود خالص احتمالی: {profit}\n"
        "🕒 ثبت (UTC): {utc}\n🕒 ثبت (محلی): {local}\n"
        "⏰ شروع مسابقه: {kickoff}\n"
        "📌 وضعیت: {status}\n"
        "📋 نسخهٔ قوانین: {terms}\n"
        "🔐 کد صحت: <code>{hash}</code>\n\n{demo}"
    ),
}

BTN = {
    "matches": "⚽ مسابقات فوتبال",
    "leagues": "🏆 لیگ‌ها",
    "mybets": "🎟 شرط‌های من",
    "results": "📊 نتایج مسابقات",
    "wallet": "💰 کیف پول آزمایشی",
    "terms": "📋 قوانین و شرایط",
    "support": "🆘 پشتیبانی",
    "home": "🏠 منوی اصلی",
    "back": "🔙 بازگشت",
    "cancel": "❌ لغو",
    "confirm": "✅ تأیید",
    "claim": "🎁 درخواست دریافت جایزه",
    "complaint": "📝 ثبت شکایت",
    "exclude": "⛔ خودمحرومی",
    "limit": "📉 سقف روزانه",
}
