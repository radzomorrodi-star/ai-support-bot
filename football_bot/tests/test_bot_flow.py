import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from sqlalchemy import func, select

from app.bot.callbacks import Cb, parse
from app.bot.setup import make_dispatcher
from app.db.models import Bet, Receipt, SecurityEvent
from app.ratelimit import MemoryKV
from tests.fakebot import cb_update, make_bot, msg_update


def test_callback_codec_is_strict():
    assert parse("h") == Cb("h") and parse("sl:123") == Cb("sl", "123") and parse("cp:epl") == Cb("cp", "epl")
    assert parse("dt:5:1x2") == Cb("dt", "5:1x2") and parse("exd:7") == Cb("exd", "7")
    for bad in (None, "", "zz", "sl", "sl:", "sl:abc", "sl:1:2", "sl:-1", "sl:" + "9" * 20, "h:1", "exd:2", "dl:1000000",
                "mk:1:other", "cf:../../x", "cf:abc", "cp:EPL", "sl:١٢٣", "x" * 100, "cl:'; DROP TABLE bets;--",
                "sl:{\"odds\":9999}"):
        assert parse(bad) is None, bad
    with pytest.raises(ValueError):
        Cb("bt", "A" * 70).pack()


@pytest.fixture
def harness(world):
    bot, sess = make_bot()
    dp = make_dispatcher(world.settings, world.sm, MemoryStorage(), MemoryKV(), clock=world.clock)

    async def send(upd: dict):
        await dp.feed_update(bot, Update.model_validate(upd, context={"bot": bot}))

    class H: ...
    h = H()
    h.send, h.sess, h.bot, h.world = send, sess, bot, world
    return h


async def test_full_persian_betting_flow(harness):
    h, w = harness, harness.world
    await h.send(msg_update(111, "/start"))
    t = h.sess.last_text()
    assert "شماره مشتری" in t and "111" in t and "تتر آزمایشی" in t and "۱٬۰۰۰" in t
    assert any(c == "lg" for c in h.sess.callbacks())

    await h.send(cb_update(111, "cp:epl"))
    evcb = next(c for c in h.sess.callbacks() if c.startswith("ev:"))
    await h.send(cb_update(111, evcb))
    card = h.sess.last_text()
    assert "📅 تاریخ مسابقه" in card and "⏰ ساعت شروع" in card and "🔵" in card and "⚪ مساوی" in card and "🔴" in card
    assert "تعداد منابع معتبر" in card and "ضریب هیچ شرکت شرط‌بندی خاصی نیست" in card
    sel = next(c for c in h.sess.callbacks() if c.startswith("sl:"))

    await h.send(cb_update(111, "dt:" + evcb.split(":")[1] + ":1x2"))
    assert "بهترین قیمت بازار" in h.sess.last_text() and "میانه بازار" in h.sess.last_text()
    await h.send(cb_update(111, evcb))

    await h.send(cb_update(111, sel))
    assert "مبلغ شرط آزمایشی" in h.sess.last_text()
    await h.send(msg_update(111, "abc"))
    assert "مبلغ نامعتبر" in h.sess.last_text()
    await h.send(msg_update(111, "۲۵"))                                  # Persian digits accepted
    conf = h.sess.last_text()
    assert "پرداخت احتمالی" in conf and "سود احتمالی" in conf and "۲۵" in conf
    cf = next(c for c in h.sess.callbacks() if c.startswith("cf:"))

    await h.send(cb_update(111, cf))
    assert "شرط شما ثبت شد" in [d["text"] for d in h.sess.of("EditMessageText")][-1]
    receipt = next(d["text"] for d in h.sess.of("SendMessage") if "رسید شرط" in d["text"])
    for needle in ("شمارهٔ شرط", "شمارهٔ مشتری", "ضریب پذیرفته‌شده", "(UTC)", "(محلی)", "نسخهٔ قوانین", "کد صحت"):
        assert needle in receipt
    assert len(h.sess.of("PinChatMessage")) == 1 and h.sess.of("PinChatMessage")[0]["chat_id"] == 111
    assert "پین شد" in h.sess.last_text()
    async with w.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 1
        assert (await s.execute(select(Receipt.pin_status))).scalar() == "pinned"

    await h.send(cb_update(111, cf))              # user double-taps confirm
    async with w.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 1
    assert len(h.sess.of("PinChatMessage")) == 1  # not pinned twice


async def test_pin_failure_notifies_customer_and_keeps_receipt(harness):
    h = harness
    h.sess.pin_error = TelegramBadRequest(method=None, message="not enough rights")
    await h.send(msg_update(111, "/start"))
    await h.send(cb_update(111, "cp:epl"))
    await h.send(cb_update(111, next(c for c in h.sess.callbacks() if c.startswith("ev:"))))
    await h.send(cb_update(111, next(c for c in h.sess.callbacks() if c.startswith("sl:"))))
    await h.send(msg_update(111, "10"))
    await h.send(cb_update(111, next(c for c in h.sess.callbacks() if c.startswith("cf:"))))
    assert "امکان پین‌کردن رسید وجود نداشت" in h.sess.last_text()
    async with h.world.sm() as s:
        assert (await s.execute(select(Receipt.pin_status))).scalar() == "failed"
    await h.send(cb_update(111, "mb"))
    assert any(c.startswith("bt:") for c in h.sess.callbacks())     # still reachable from "my bets"


async def test_duplicate_telegram_update_processed_once(harness):
    h = harness
    u = msg_update(111, "/start", update_id=777)
    await h.send(u)
    n = len(h.sess.calls)
    await h.send(u)
    await h.send(u)
    assert len(h.sess.calls) == n


async def test_forged_and_foreign_callbacks_are_harmless(harness):
    h, w = harness, harness.world
    await h.send(msg_update(111, "/start"))
    await h.send(cb_update(111, "cp:epl"))
    await h.send(cb_update(111, next(c for c in h.sess.callbacks() if c.startswith("ev:"))))
    await h.send(cb_update(111, next(c for c in h.sess.callbacks() if c.startswith("sl:"))))
    await h.send(msg_update(111, "10"))
    cf = next(c for c in h.sess.callbacks() if c.startswith("cf:"))
    for forged in ("sl:99999999", "cf:AAAAAAAAAAAAAAAA", "price=9999", "bt:ABCDEFGHJK", "cl:ABCDEFGHJK", "sl:1' OR '1'='1"):
        await h.send(cb_update(111, forged))
    # a second user replays the first user's confirm button
    await h.send(msg_update(222, "/start"))
    await h.send(cb_update(222, cf))
    async with w.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 0
        assert (await s.execute(select(func.count()).select_from(SecurityEvent).where(
            SecurityEvent.kind == "bad_callback_data"))).scalar() == 2   # only the 2 malformed payloads
    await h.send(cb_update(111, cf))          # the rightful owner can still confirm
    async with w.sm() as s:
        assert (await s.execute(select(func.count()).select_from(Bet))).scalar() == 1


async def test_throttle_limits_flooding(harness):
    h = harness
    for _ in range(40):
        await h.send(msg_update(333, "/start"))
    texts = [d["text"] for d in h.sess.of("SendMessage")]
    assert sum("شماره مشتری" in x for x in texts) == 20            # 20 requests / 10s allowed
    assert sum("درخواست‌های شما زیاد است" in x for x in texts) == 20


async def test_menu_screens_are_persian_and_rtl_safe(harness):
    h = harness
    await h.send(msg_update(111, "/start"))
    for cbd, needle in (("tm", "قوانین و شرایط"), ("wl", "کیف پول آزمایشی"), ("sp", "پشتیبانی"), ("rs", "نتیجه"),
                        ("mb", "شرط"), ("lg", "لیگ"), ("ml", "مسابقه")):
        await h.send(cb_update(111, cbd))
        assert needle in h.sess.last_text()
        assert any(c == "h" for c in h.sess.callbacks()), cbd         # Home always reachable
    await h.send(cb_update(111, "lg"))
    labels = [b["text"] for row in h.sess.last_markup() for b in row]
    assert any("لیگ برتر انگلیس" in l for l in labels) and any("لیگ کنفرانس اروپا" in l for l in labels)
    await h.send(cb_update(111, "cp:epl"))
    labels = [b["text"] for row in h.sess.last_markup() for b in row if "callback_data" in b]
    assert any("⁦" in l for l in labels)                         # Latin team names isolated inside RTL text
