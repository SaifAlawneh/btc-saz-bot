import os
import logging
import asyncio
import requests
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import ta
import random
import json
import re

# ==================== إعدادات ====================
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "")
NEWS_API_KEY   = os.environ.get("NEWS_API_KEY", "")
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY", "")

MIN_CONFIDENCE    = 68
AUTO_SIGNAL_MODE  = os.environ.get("AUTO_SIGNAL_MODE", "balanced").lower()  # conservative | balanced | active
FRAME_MIN_CONFIDENCE = 60  # Minimum confidence required for a timeframe to be counted in confluence
ENTRY_ZONE_ATR_FACTOR = 0.25  # Entry zone width on each side of smart entry, based on ATR
PRICE_EXPIRY_PCT  = 1.0   # Pending signal expires if BTC moves this % away from signal price
SIGNAL_EXPIRY     = 60 * 60  # Pending signal expires after 1 hour
PENDING_SIGNAL_MIN_AGE_BEFORE_EXPIRY = 5 * 60  # Do not expire a fresh signal in the same monitoring cycle
SPAM_COOLDOWN     = 1800
CACHE_TTL         = 900
PENDING_MAX_AGE   = 48      # hours: stale pending auto-cancels after this

def pending_max_age_for_regime(regime="UNKNOWN"):
    """BTC pending setups should expire faster in unstable or unclear conditions."""
    if regime == "VOLATILE":
        return 12 * 60 * 60
    if regime == "RANGING":
        return 24 * 60 * 60
    return PENDING_MAX_AGE * 60 * 60
OVERRIDE_MIN_QUALIFIED_FRAMES = 2  # Higher-risk override still requires 2 qualified frames in the same direction
OVERRIDE_MAX_DISTANCE_FROM_ZONE_PCT = 1.0  # Block override if price is too far beyond the entry zone
# Decision-engine upgrades
MAX_DISTANCE_FROM_ZONE_PCT = 1.5  # Pending setup expires when price moves too far away from the smart entry zone
SETUP_COOLDOWN_HOURS = 6          # Do not re-offer the same cancelled setup during this window
DAILY_STRONG_CONF = 70            # Strong daily trend blocks counter-trend overrides
OVERRIDE_MIN_AVG_CONF = 65        # Higher-risk scenario needs enough average confidence
FRAME_THRESHOLDS = {"1h": 60, "4h": 60, "1d": 65}
FRAME_WEIGHTS = {"1h": 0.20, "4h": 0.30, "1d": 0.50}
WEIGHTED_DIRECT_THRESHOLD = 0.80
WEIGHTED_PARTIAL_THRESHOLD = 0.50
CANCELLED_SETUPS_FILE = "cancelled_setups.json"
SAZ_MEMORY_FILE = "saz_decision_memory.json"
BIAS_ALERT_STATE_FILE = "bias_alert_state.json"
TRADES_FILE       = "active_trades.json"
STATS_FILE        = "trade_stats.json"
LANGUAGES_FILE    = "user_languages.json"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BUILD_ID = "SAZBOT_FINAL_DNA_MORE_OPPORTUNITIES_2026_06_09"

user_languages        = {}
active_trades         = []
active_btc_trade      = {}
pending_trade_replace = {}
last_signal_time      = {}
pending_signals       = {}
trade_counter         = 0
_cache                = {}
_econ_cache           = {"data": None, "ts": 0}
_news_notified        = {}

def load_bias_alert_state():
    try:
        with open(BIAS_ALERT_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_bias_alert_state():
    try:
        with open(BIAS_ALERT_STATE_FILE, "w") as f:
            json.dump(last_bias_alert_state, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("save_bias_alert_state: " + str(e))

last_bias_alert_state = load_bias_alert_state()
cancelled_setups       = []


# ==================== Grade Performance Tracking ====================
def _empty_grade_stats():
    return {
        "A": {"total": 0, "wins": 0, "losses": 0, "breakeven": 0, "total_rr": 0.0},
        "B": {"total": 0, "wins": 0, "losses": 0, "breakeven": 0, "total_rr": 0.0},
        "C": {"total": 0, "wins": 0, "losses": 0, "breakeven": 0, "total_rr": 0.0},
        "REJECT": {"total": 0, "wins": 0, "losses": 0, "breakeven": 0, "total_rr": 0.0},
    }

def normalise_grade_stats(stats):
    gs = stats.setdefault("grade_stats", _empty_grade_stats())
    for g, base in _empty_grade_stats().items():
        gs.setdefault(g, base.copy())
        for k, v in base.items():
            gs[g].setdefault(k, v)
    return stats

def record_grade_result(stats, grade, result, rr=0.0):
    normalise_grade_stats(stats)
    grade = grade if grade in ("A", "B", "C", "REJECT") else "REJECT"
    row = stats["grade_stats"][grade]
    row["total"] += 1
    if result == "win":
        row["wins"] += 1
        row["total_rr"] += float(rr or 0)
    elif result == "breakeven":
        row["breakeven"] += 1
    else:
        row["losses"] += 1
    return stats

def format_grade_edge_report(uid=0):
    lang = user_languages.get(uid, "ar")
    stats = normalise_grade_stats(load_stats())
    lines = []
    if lang == "ar":
        lines += ["📊 SazBot | أداء التصنيفات", ""]
        for g in ["A", "B", "C"]:
            row = stats["grade_stats"].get(g, {})
            total = int(row.get("total", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            losses = int(row.get("losses", 0) or 0)
            be = int(row.get("breakeven", 0) or 0)
            wr = round(wins / total * 100) if total else 0
            avg_rr = round(float(row.get("total_rr", 0.0) or 0.0) / wins, 2) if wins else 0
            lines.append(f"{saz_grade_label(g, uid)}")
            lines.append(f"الصفقات: {total} | رابحة: {wins} | خاسرة: {losses} | تعادل: {be}")
            lines.append(f"نسبة النجاح: {wr}% | متوسط RR: 1:{avg_rr}")
            lines.append("")
        lines.append("كلما زاد عدد الصفقات المسجلة، أصبح تقييم A/B/C أدق.")
    else:
        lines += ["📊 SazBot | Grade Performance", ""]
        for g in ["A", "B", "C"]:
            row = stats["grade_stats"].get(g, {})
            total = int(row.get("total", 0) or 0)
            wins = int(row.get("wins", 0) or 0)
            losses = int(row.get("losses", 0) or 0)
            be = int(row.get("breakeven", 0) or 0)
            wr = round(wins / total * 100) if total else 0
            avg_rr = round(float(row.get("total_rr", 0.0) or 0.0) / wins, 2) if wins else 0
            lines.append(f"{saz_grade_label(g, uid)}")
            lines.append(f"Trades: {total} | Wins: {wins} | Losses: {losses} | BE: {be}")
            lines.append(f"Win Rate: {wr}% | Avg RR: 1:{avg_rr}")
            lines.append("")
        lines.append("The more closed trades are recorded, the more meaningful A/B/C performance becomes.")
    return "\n".join(lines)


# ==================== Runtime State Persistence ====================
def _json_safe_key_dict(d):
    """JSON object keys are strings; keep values as-is."""
    try:
        return {str(k): v for k, v in dict(d).items()}
    except Exception:
        return {}

def _int_key_dict(d):
    out = {}
    try:
        for k, v in dict(d).items():
            try:
                out[int(k)] = v
            except Exception:
                out[k] = v
    except Exception:
        pass
    return out

def save_runtime_state():
    """Persist volatile runtime state so Railway restarts do not wipe bot memory."""
    try:
        state = {
            "active_trades": active_trades,
            "active_btc_trade": active_btc_trade,
            "pending_trade_replace": _json_safe_key_dict(pending_trade_replace),
            "last_signal_time": last_signal_time,
            "pending_signals": _json_safe_key_dict(pending_signals),
            "trade_counter": trade_counter,
            "_news_notified": _news_notified,
            "last_bias_alert_state": last_bias_alert_state,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("save_runtime_state failed: " + str(e))

def load_runtime_state():
    """Load persisted runtime state on startup."""
    global active_trades, active_btc_trade, pending_trade_replace, last_signal_time
    global pending_signals, trade_counter, _news_notified, last_bias_alert_state
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        active_trades = state.get("active_trades", active_trades) or []
        active_btc_trade = state.get("active_btc_trade", active_btc_trade) or {}
        pending_trade_replace = _int_key_dict(state.get("pending_trade_replace", {}))
        last_signal_time = state.get("last_signal_time", last_signal_time) or {}
        pending_signals = _int_key_dict(state.get("pending_signals", {}))
        trade_counter = int(state.get("trade_counter", trade_counter) or 0)
        _news_notified = state.get("_news_notified", _news_notified) or {}
        last_bias_alert_state = state.get("last_bias_alert_state", last_bias_alert_state) or {}
        logger.info("Runtime state loaded successfully.")
    except FileNotFoundError:
        logger.info("No runtime state file found; starting clean.")
    except Exception as e:
        logger.warning("load_runtime_state failed: " + str(e))


# ✅ FIX 1: asyncio lock لحماية active_trades من race conditions
_trades_lock = None

def get_trades_lock():
    """Return the active trades lock. It is initialised in main() inside the running bot context."""
    global _trades_lock
    if _trades_lock is None:
        # Fallback safety: should normally be initialised in main().
        _trades_lock = asyncio.Lock()
    return _trades_lock

ALLOWED_USERS_ENV = os.environ.get("ALLOWED_USERS", "")
if ALLOWED_USERS_ENV.strip():
    ALLOWED_USERS = {int(x.strip()) for x in ALLOWED_USERS_ENV.split(",") if x.strip().isdigit()}
else:
    ALLOWED_USERS = {8490817794, 1548286220}

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing. Please set it as an environment variable.")

def count_qualified_frame_lines(frame_lines):
    """Count only timeframe lines that passed FRAME_MIN_CONFIDENCE.
    This avoids treating low-confidence frames as fully aligned just because the direction text matches.
    """
    buy = sum(1 for f in frame_lines if "BUY" in f and "✅" in f)
    sell = sum(1 for f in frame_lines if "SELL" in f and "✅" in f)
    return buy, sell

def entry_zone_from_trade(entry, atr):
    width = max(float(atr or 0) * ENTRY_ZONE_ATR_FACTOR, float(entry) * 0.0005)
    return round(float(entry) - width, 2), round(float(entry) + width, 2)

def format_entry_zone(entry, atr):
    low, high = entry_zone_from_trade(entry, atr)
    return f"${low:,.2f} — ${high:,.2f}"


def distance_from_entry_zone_pct(price, entry_low, entry_high):
    """Return 0 if price is inside the entry zone, otherwise distance from nearest zone edge in percent."""
    try:
        price = float(price)
        entry_low = float(entry_low)
        entry_high = float(entry_high)
        if price <= 0 or entry_low <= 0 or entry_high <= 0:
            return 0.0
        low = min(entry_low, entry_high)
        high = max(entry_low, entry_high)
        if low <= price <= high:
            return 0.0
        edge = high if price > high else low
        return abs(price - edge) / edge * 100
    except Exception:
        return 0.0


def max_distance_for_setup_grade(res, default_pct=MAX_DISTANCE_FROM_ZONE_PCT):
    """Allow more distance only for stronger setups; keep C strict."""
    try:
        m = res.get("decision_metrics") or {}
        grade = m.get("setup_grade") or saz_setup_grade(m)
        if grade == "A":
            return max(default_pct, 2.0)
        if grade == "B":
            return max(default_pct, 1.5)
        if grade == "C":
            return min(default_pct, 1.0)
        return min(default_pct, 0.8)
    except Exception:
        return default_pct


def is_price_too_far_from_entry_zone(price, entry_low, entry_high, max_pct=MAX_DISTANCE_FROM_ZONE_PCT):
    return distance_from_entry_zone_pct(price, entry_low, entry_high) > max_pct


def _setup_key(asset, direction, entry, atr):
    """Bucket similar setups so cancelled ideas are not offered again immediately."""
    try:
        width = max(float(atr or 0), float(entry) * 0.005)
        bucket = round(float(entry) / width)
        return f"{asset}_{direction}_{bucket}"
    except Exception:
        return f"{asset}_{direction}_{round(float(entry), -2)}"

def load_cancelled_setups():
    try:
        with open(CANCELLED_SETUPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = datetime.now(timezone.utc).timestamp()
        cutoff = SETUP_COOLDOWN_HOURS * 3600
        return [x for x in data if now - float(x.get("ts", 0)) <= cutoff]
    except Exception:
        return []

def save_cancelled_setups():
    try:
        now = datetime.now(timezone.utc).timestamp()
        cutoff = SETUP_COOLDOWN_HOURS * 3600
        valid = [x for x in cancelled_setups if now - float(x.get("ts", 0)) <= cutoff]
        cancelled_setups[:] = valid
        with open(CANCELLED_SETUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(valid, f)
    except Exception as e:
        logger.warning("save_cancelled_setups: " + str(e))

def load_saz_memory():
    try:
        with open(SAZ_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-300:]
        return []
    except Exception:
        return []

def save_saz_memory(data):
    try:
        with open(SAZ_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data[-300:], f, ensure_ascii=False)
    except Exception as e:
        logger.warning("save_saz_memory: " + str(e))

def update_saz_memory(snapshot):
    """Store compact decision snapshots so SazBot can estimate opportunity cost and narrative shifts."""
    try:
        data = load_saz_memory()
        now = now_ts()
        if data and now - float(data[-1].get("ts", 0)) < 300:
            data[-1] = snapshot
        else:
            data.append(snapshot)
        save_saz_memory(data)
    except Exception as e:
        logger.warning("update_saz_memory: " + str(e))

def recent_saz_memory(hours=48):
    try:
        now = now_ts()
        cutoff = hours * 3600
        return [x for x in load_saz_memory() if now - float(x.get("ts", 0)) <= cutoff]
    except Exception:
        return []

def remember_cancelled_setup(trade_or_asset, direction=None, entry=None, atr=None, reason=""):
    try:
        if isinstance(trade_or_asset, dict):
            asset = trade_or_asset.get("asset", "BTC")
            direction = trade_or_asset.get("direction", direction)
            entry = trade_or_asset.get("entry", entry)
            atr = trade_or_asset.get("atr", atr)
        else:
            asset = trade_or_asset
        if not direction or not entry:
            return
        key = _setup_key(asset, direction, entry, atr)
        cancelled_setups.append({"key": key, "ts": datetime.now(timezone.utc).timestamp(), "reason": reason})
        save_cancelled_setups()
    except Exception as e:
        logger.warning("remember_cancelled_setup: " + str(e))

def is_recently_cancelled(asset, direction, entry, atr):
    try:
        key = _setup_key(asset, direction, entry, atr)
        now = datetime.now(timezone.utc).timestamp()
        cutoff = SETUP_COOLDOWN_HOURS * 3600
        for x in list(cancelled_setups):
            if x.get("key") == key and now - float(x.get("ts", 0)) <= cutoff:
                return True
        return False
    except Exception:
        return False

def frame_threshold(label):
    return FRAME_THRESHOLDS.get(label, FRAME_MIN_CONFIDENCE)

def frame_strength(direction, conf):
    if direction == "NEUTRAL":
        return "NEUTRAL"
    if conf >= 75:
        return "Strong " + direction
    return direction

def weighted_frame_decision(results, relaxed=False):
    """Weighted MTF decision: Daily leads, 4H confirms, 1H times entry."""
    buy_weight = sell_weight = 0.0
    buy_frames = sell_frames = 0
    buy_conf = []
    sell_conf = []
    for label, r in results.items():
        direction = r.get("direction", "NEUTRAL")
        conf = r.get("conf", 0)
        if direction == "NEUTRAL" or conf < frame_threshold(label):
            continue
        w = FRAME_WEIGHTS.get(label, 0.0)
        if direction == "BUY":
            buy_weight += w; buy_frames += 1; buy_conf.append(conf)
        elif direction == "SELL":
            sell_weight += w; sell_frames += 1; sell_conf.append(conf)
    daily = results.get("1d", {})
    daily_dir = daily.get("direction", "NEUTRAL")
    daily_conf = daily.get("conf", 0)
    majority = None
    final = "NEUTRAL"
    frames_conf = 0
    conf_txt_key = "no_confluence"
    diff = buy_weight - sell_weight
    if abs(diff) < 1e-9:
        return final, majority, frames_conf, conf_txt_key, buy_frames, sell_frames, buy_weight, sell_weight
    candidate = "BUY" if diff > 0 else "SELL"
    support_frames = buy_frames if candidate == "BUY" else sell_frames
    support_weight = buy_weight if candidate == "BUY" else sell_weight
    avg_conf = (sum(buy_conf) / len(buy_conf)) if candidate == "BUY" and buy_conf else (sum(sell_conf) / len(sell_conf) if sell_conf else 0)
    # Strong daily counter-trend filter
    if daily_dir in ("BUY", "SELL") and daily_dir != candidate and daily_conf >= DAILY_STRONG_CONF:
        return "NEUTRAL", None, 0, "no_confluence", buy_frames, sell_frames, buy_weight, sell_weight
    # Direct signals need strong weighted support. Partial stays as user-controlled scenario.
    if support_weight >= WEIGHTED_DIRECT_THRESHOLD and support_frames >= 2:
        final = candidate
        frames_conf = 85 if support_frames == 3 else max(70, round(avg_conf))
        conf_txt_key = "full_confluence" if support_frames == 3 else "partial_confluence"
    elif support_weight >= WEIGHTED_PARTIAL_THRESHOLD and support_frames >= OVERRIDE_MIN_QUALIFIED_FRAMES:
        if relaxed and avg_conf >= OVERRIDE_MIN_AVG_CONF:
            final = candidate
            frames_conf = max(65, round(avg_conf))
        else:
            majority = candidate
            frames_conf = max(65, round(avg_conf)) if avg_conf else 65
        conf_txt_key = "partial_confluence"
    return final, majority, frames_conf, conf_txt_key, buy_frames, sell_frames, buy_weight, sell_weight

def load_languages():
    try:
        with open(LANGUAGES_FILE) as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        return {}

def save_languages():
    with open(LANGUAGES_FILE, "w") as f:
        json.dump({str(k): v for k, v in user_languages.items()}, f)

def load_trades():
    try:
        with open(TRADES_FILE) as f:
            data = json.load(f)
            return data.get("trades", []), data.get("counter", 0)
    except Exception as e:
        return [], 0

def save_trades():
    with open(TRADES_FILE, "w") as f:
        json.dump({"trades": active_trades, "counter": trade_counter}, f)

_loaded_languages = load_languages()
user_languages.update(_loaded_languages)

def _validate_loaded_trade(t: dict) -> bool:
    """Ensure trade has valid levels, required fields, and is not too old."""
    if t.get("asset") != "BTC" or t.get("entry", 0) <= 10_000: return False
    for k in ["entry", "sl", "tp1", "tp2", "tp3", "direction", "chat_id", "open_time"]:
        if k not in t: return False
    # Reject trades older than 7 days
    try:
        open_dt = datetime.strptime(t["open_time"], "%d/%m/%Y  %H:%M").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - open_dt).days
        if age_days > 7: return False
    except Exception:
        return False
    dire, e, sl = t["direction"], t["entry"], t["sl"]
    tp1, tp2, tp3 = t["tp1"], t["tp2"], t["tp3"]
    if dire == "BUY"  and not (sl < e < tp1 < tp2 < tp3): return False
    if dire == "SELL" and not (tp3 < tp2 < tp1 < e < sl): return False
    return True

_loaded_trades, _loaded_counter = load_trades()
_valid_trades = [t for t in _loaded_trades if _validate_loaded_trade(t)]
_skipped      = len(_loaded_trades) - len(_valid_trades)
if _skipped:
    logger.warning(f"Skipped {_skipped} invalid/stale trades on startup")
active_trades.extend(_valid_trades)
trade_counter = _loaded_counter
cancelled_setups.extend(load_cancelled_setups())

def get_cached(key):
    if key in _cache:
        data, ts = _cache[key]
        if (datetime.now(timezone.utc).timestamp() - ts) < CACHE_TTL:
            return data
    return None

def set_cache(key, data):
    _cache[key] = (data, datetime.now(timezone.utc).timestamp())

GREETINGS = ["مرحبا","هاي","هلا","اهلا","أهلا","السلام","صباح","مساء","كيف","شلونك",
             "hello","hi","hey","good","howdy","sup","morning","evening"]
REPLIES_AR = ["هلا وغلا! 🟡 أنا SazBot — جاهز لتحليل BTC\nاستخدم الأزرار 👇",
              "أهلاً! 📊 تبي تحليل صفقة أو قراءة السوق؟ اختر 👇",
              "هلا! 😊 اختر من القائمة للبدء 👇"]
REPLIES_EN = ["Hello! 🟡 I'm SazBot — ready to analyse BTC.\nUse the buttons below 👇",
              "Hi! 📊 Want a setup or market read? Choose 👇"]
CONFUSED_AR = ["ما فهمت 😅 استخدم الأزرار 👇", "🤔 اختر من القائمة 👇"]
CONFUSED_EN = ["Didn't get that 😅 Use the buttons 👇", "🤔 Choose from the menu 👇"]

TEXTS = {
    "ar": {
        "choose_lang": "🟡 SazBot | BTC Signals\n\nاختر لغتك:",
        "welcome": "🟡 SazBot 2.1 | Decision Intelligence\n\nمرحباً بك في تجربة أذكى لقراءة BTC/USD.\n\nSazBot لا يبحث عن أي صفقة؛ بل يقيّم أولاً هل السوق يستحق المخاطرة أم لا.\n\n🧠 ما يقدمه لك:\n▫️ طبقة قرار ذكية لتصفية الضوضاء\n▫️ تقييم جودة الفرصة قبل الدخول\n▫️ قراءة حالة السوق بوضوح\n▫️ تقييم جودة القرار قبل المخاطرة\n▫️ متابعة منظمة للصفقات والتنبيهات\n\n🚫 أحياناً أفضل قرار هو عدم التداول.\n\n⚠️ تحليل تعليمي فقط — ليست توصية مالية. إدارة المخاطر مسؤوليتك.",
        "btn_btc": "🧠 مركز القرار BTC",
        "btn_analysis_btc": "📖 قراءة السوق",
        "btn_prices": "💰 الأسعار", "btn_about": "ℹ️ عن SazBot",
        "btn_lang": "🌐 اللغة", "btn_trades": "📋 الصفقات النشطة",
        "btn_close_trade": "❌ إغلاق صفقة نشطة", "close_trade_title": "اختر الصفقة التي تريد إغلاقها:",
        "btn_stats": "📊 الإحصائيات",
        "no_open_trades": "📭 لا توجد صفقات مفتوحة حالياً",
        "loading_trade": "⏳ SazBot 2.1 يفحص جودة السوق ويبني القرار...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices": "⏳ جاري جلب الأسعار...",
        "failed": "❌ البيانات غير متاحة حالياً. حاول مرة أخرى بعد دقيقة.",
        "error": "❌ خطأ: ",
        "private_bot": "⛔ هذا البوت خاص",
        "choose_language_intro": "🟡 SazBot | BTC Signals\n\nاختر لغتك / Choose your language:",
        "replace_title": "⚠️ SazBot | تم رصد سيناريو قريب",
        "opposite_title": "⚠️ SazBot | تم رصد سيناريو معاكس",
        "current_trade_word": "الحالي",
        "new_trade_word": "الجديد",
        "btn_replace_yes": "✅ أغلق القديمة وافتح الجديدة",
        "btn_add_new": "➕ أبقِ القديمة وافتح الجديدة أيضاً",
        "btn_keep_old": "❌ أبقِ القديمة فقط",
        "status_pending": "قيد الانتظار",
        "status_active": "نشطة",
        "trade_closed": "✅ SazBot | تم إغلاق الصفقة",
        "signal_expired": "⚠️ انتهت صلاحية الإشارة",
        "update_expired": "⚠️ SazBot | انتهت صلاحية التحديث\n\nتحديث منطقة الدخول لم يعد متاحاً.",
        "entry_zone_updated": "✅ SazBot | تم تحديث منطقة الدخول",
        "pending_expired_title": "⏰ SazBot | انتهت صلاحية السيناريو المعلق",
        "pending_expired_body": "لم يتم تفعيل السيناريو ضمن الفترة المحددة. اطلب تحليلاً جديداً إذا كانت الفرصة لا تزال مناسبة.",
        "smart_market_alert": "⚡ SazBot | تنبيه سوق ذكي",
        "educational_footer": "⚠️ تحليل تعليمي فقط — ليست توصية مالية.",
        "avoid_new_trades": "تجنب فتح صفقات جديدة حتى يهدأ التذبذب.",
        "no_signal": "⏳ لا توجد فرصة عالية الجودة حالياً\n\nSazBot 2.1 يرى أن الانتظار أكثر أماناً من الدخول في فرصة غير مكتملة.",
        "trade_header": "SazBot 2.1 | قرار BTC",
        "auto_header": "SazBot 2.1 | فرصة BTC تلقائية",
        "update_header": "SazBot | تحديث صفقة BTC",
        "analysis_header": "SazBot 2.1 | قراءة السوق",
        "entry": "الدخول المرجعي", "entry_zone": "منطقة الدخول الذكية",
        "direction": "اتجاه السوق",
        "confidence": "مستوى الثقة",
        "entry_basis": "سبب الدخول",
        "weekly": "الأسبوعي", "monthly": "الشهري",
        "bullish": "صاعد", "bearish": "هابط", "neutral": "محايد",
        "counter_trend": "⚠️ فرصة عكس الاتجاه — أهداف أقصر ومخاطرة أضيق.",
        "trend_up": "📈 سوق صاعد", "trend_down": "📉 سوق هابط", "ranging_market": "↔️ سوق عرضي", "high_volatility": "⚡ تذبذب مرتفع",
        "bearish_div": "📉 دايفرجنس RSI هابط ⚠️", "bullish_div": "📈 دايفرجنس RSI صاعد ✅",
        "strong_sell_zone": "🔴 منطقة بيع قوية", "strong_buy_zone": "🟢 منطقة شراء قوية", "liquidity_zone": "🎯 منطقة سيولة",
        "risk_check": "تقييم المخاطر", "risk_level": "مستوى المخاطرة", "key_levels": "المستويات المهمة",
        "active_trade": "الصفقة النشطة", "pending": "قيد الانتظار", "active": "نشطة", "opened": "وقت الفتح",
        "targets": "الأهداف", "market_filters_blocked": "⚪ الفلاتر منعت التحليل أو البيانات غير متوفرة\n\nحاول بعد دقيقتين 🕐",
        "trade_health": "فحص حالة الصفقة", "distance": "المسافة", "above": "فوق", "below": "تحت", "entry_zone_word": "منطقة الدخول",
        "risk_review": "مراجعة المخاطر",
        "dna_conditions_deteriorated": "🧠 طبقة القرار ترى أن جودة الفرصة تراجعت بوضوح.", "recommend_cancel": "🔴 التوصية: إلغاء — الظروف تدهورت بوضوح", "recommend_review": "🟡 التوصية: مراجعة — يوجد عامل خطر أساسي بدون دعم كافٍ", "recommend_keep": "🟢 التوصية: إبقاء — الظروف لا تزال داعمة", "recommend_monitor": "🟡 التوصية: مراقبة — الإشارات مختلطة",
        "full_reversal": "❌ تغيرت ظروف السوق بشكل واضح", "frames_still_support": "ظروف السوق لا تزال تدعم السيناريو", "frames_oppose": "ظروف السوق تغيرت بشكل ملحوظ",
        "monthly_supports": "📆 الميل الشهري يدعم السيناريو", "monthly_against": "📆 الميل الشهري يعاكس السيناريو", "weekly_supports": "🗓️ الاتجاه الأسبوعي يدعم السيناريو", "weekly_against": "🗓️ الاتجاه الأسبوعي يعاكس السيناريو",
        "volatility_risk": "⚡ تذبذب مرتفع — المخاطر زادت", "ranging_risk": "↔️ السوق عرضي — الوصول للأهداف قد يكون أصعب", "regime_supports": "📊 حالة السوق تدعم الاتجاه", "regime_against": "📊 حالة السوق تعاكس الاتجاه", "rsi_against": "⚠️ دايفرجنس RSI يعاكس السيناريو", "rsi_supports": "📈 دايفرجنس RSI يدعم السيناريو",
        "forced_note": "⚠️ تم فتح سيناريو بديل بمخاطرة أعلى.",
        "btn_keep_trade": "✅ إبقاء الصفقة", "btn_keep_setup": "✅ إبقاء السيناريو", "btn_cancel_setup": "❌ إلغاء السيناريو", "btn_activate_setup": "✅ تفعيل السيناريو", "btn_ignore": "❌ تجاهل", "btn_update_setup": "✅ تحديث السيناريو",
        "auto_cancel_timeframes": "❌ تم الإلغاء تلقائياً: تغيرت ظروف السوق بشكل ملحوظ", "auto_cancel_conditions": "❌ تم الإلغاء تلقائياً: الظروف تدهورت",
        "setup_activated": "تم تفعيل السيناريو", "price_reached_entry": "وصل السعر إلى منطقة الدخول الذكية. السيناريو أصبح نشطاً.",
        "setup_cancelled_full": "تم إلغاء السيناريو", "price_bias_changed": "وصل السعر إلى منطقة الدخول، لكن اتجاه السوق تغيّر إلى",
        "invalid_before_entry": "السعر ألغى صلاحية السيناريو قبل الدخول.", "entry_alert": "تنبيه منطقة الدخول", "approaching_entry": "السعر يقترب من منطقة الدخول الذكية.",
        "reference_entry": "الدخول المرجعي", "actual_entry": "سعر الدخول الفعلي", "entry_reference_zone": "منطقة الدخول المرجعية", "override_blocked_distance": "❌ تم رفض الفرصة: السعر ابتعد كثيراً عن منطقة الدخول الذكية، والمخاطرة لم تعد مناسبة.", "override_blocked_frames": "❌ تم رفض الفرصة: ظروف السوق غير داعمة بما يكفي حالياً.", "high_impact_event": "حدث مؤثر عالي الأهمية", "impact_high": "التأثير: 🔴 مرتفع. يرجى إدارة المخاطر بحذر.",
        "entry_update": "تحديث منطقة الدخول", "conditions_changed_before_activation": "تغيرت ظروف السوق قبل التفعيل.", "old_reference": "الدخول السابق", "new_reference": "الدخول الجديد",
        "price_moved_against": "تحرك السعر ضد منطقة الدخول الذكية وتغيرت ظروف السوق.",
        "buy": "شراء  BUY ⬆️", "sell": "بيع  SELL ⬇️",
        "targets_section": "الأهداف المحتملة",
        "tp1": "TP1", "tp2": "TP2", "tp3": "TP3", "sl": "SL",
        "rr": "العائد / المخاطرة",
        "fib_section": "مستويات Fibonacci",
        "support": "دعم", "resistance": "مقاومة",
        "confluence": "توافق الفريمات",
        "frame_1h": "ساعة", "frame_4h": "4 ساعات", "frame_1d": "يومي",
        "full_confluence": "توافق قوي بين الفريمات",
        "partial_confluence": "توافق جزئي بين الفريمات",
        "no_confluence": "⏳ لا توجد فرصة عالية الجودة حالياً",
        "qualified_note": "",
        "low_conf_note": "",
        "partial_title": "⚠️ توافق جزئي",
        "no_quality_title": "⏳ لا توجد فرصة عالية الجودة حالياً",
        "partial_body": "الاتجاه العام واضح، لكن التوافق لم يكتمل بعد.",
        "higher_risk_prompt": "يمكن عرض فرصة متاحة بمخاطرة أعلى فقط عند وجود توافق جزئي كافٍ.",
        "no_trade_better": "عدم الدخول أحياناً أفضل من الدخول في فرصة ضعيفة.",
        "btn_higher_risk": "🎯 عرض الفرصة المتاحة",
        "btn_cancel": "❌ إلغاء",
        "btn_retry": "🔄 إعادة التحليل",
        "request_expired": "⚠️ انتهت صلاحية الطلب\n\nيرجى طلب تحليل جديد.",
        "existing_trade_kept": "✅ تم الاحتفاظ بالصفقة القائمة",
        "setup_kept": "✅ تم الاحتفاظ بالسيناريو",
        "setup_cancelled": "❌ تم إلغاء السيناريو",
        "cancelled_waiting": "✅ تم الإلغاء. بانتظار فرصة أقوى.",
        "preparing_available": "⏳ جاري تجهيز الفرصة المتاحة...",
        "higher_risk_warning": "⚠️ هذا سيناريو أعلى مخاطرة لأنه لا يعتمد على توافق كامل. استخدم حجم أصغر وإدارة مخاطرة صارمة. عدم الدخول أحياناً أفضل من الدخول في فرصة ضعيفة.",
        "duplicate_setup": "⚠️ نفس الفرصة موجودة بالفعل",
        "existing_entry_zone": "منطقة الدخول القائمة",
        "previous_entry_zone": "منطقة الدخول السابقة",
        "no_new_trade_needed": "السعر الحالي قريب — لا داعي لصفقة جديدة",
        "indicators_section": "المؤشرات",
        "risk_low": "🟢 منخفضة", "risk_med": "🟡 متوسطة", "risk_high": "🔴 عالية",
        "risk_low_msg": "إعداد جيد — مخاطرة منخفضة",
        "risk_med_msg": "الإعداد مقبول لكن يحتاج إدارة مخاطرة",
        "risk_high_msg": "مخاطرة أعلى — يفضل تقليل الحجم أو الانتظار",
        "footer": "⚠️ تحليل تعليمي فقط — ليست توصية مالية. إدارة المخاطر مسؤوليتك.",
        "updated_gmt": "آخر تحديث (GMT)",
        "update_tp1_hit": "✅ الهدف الأول تم! تم نقل SL للدخول",
        "update_tp2_hit": "✅✅ الهدف الثاني تم! تم نقل SL للـ TP2",
        "update_sl_moved": "📊 تم تحريك وقف الخسارة للأمان",
        "tp3_hit": "🏆 الهدف الثالث تم — تم إغلاق الصفقة بنجاح.",
        "tp1_hit": "✅ الهدف الأول تم — تم نقل وقف الخسارة إلى الدخول.",
        "tp2_hit": "✅✅ الهدف الثاني تم — تم رفع وقف الخسارة لحماية الربح.",
        "protected_profit": "✅ تم حماية الربح — وصل السعر إلى وقف الخسارة بعد TP2.",
        "breakeven": "🟡 خروج على نقطة الدخول — تم إغلاق الصفقة بدون خسارة.",
        "sl_hit": "🛑 وقف الخسارة تم — أغلقت الصفقة.",
        "trailing_sl": "📊 تم تحديث وقف الخسارة المتحرك",
        "current_price": "السعر الحالي",
        "trend_bull": "📈 الاتجاه: صاعد", "trend_bear": "📉 الاتجاه: هابط",
        "trend_neutral": "➡️ الاتجاه: محايد",
        "rsi_oversold": "تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought": "تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral": "منطقة محايدة",
        "macd_bull": "MACD: زخم صاعد ↗️", "macd_bear": "MACD: زخم هابط ↘️",
        "ema_bull": "EMAs: مرتبة صعوداً 📈", "ema_bear": "EMAs: مرتبة هبوطاً 📉",
        "ema_mixed": "EMAs: إشارات مختلطة ↔️",
        "bb_low": "بولنجر: عند الدعم السفلي",
        "bb_high": "بولنجر: عند المقاومة العلوية",
        "bb_mid": "بولنجر: منتصف النطاق",
        "summary_bull": "✅ الخلاصة: السوق يميل للصعود",
        "summary_bear": "✅ الخلاصة: السوق يميل للهبوط",
        "summary_neutral": "🧭 الخلاصة: السوق في منطقة تردد",
        "prices_title": "💰 الأسعار الحالية", "change_24h": "التغيير 24h",
        "about_text": "ℹ️ عن SazBot 2.1 🟡\n\nوُلد SazBot من شغف حقيقي بالأسواق والتقنية، ليقدّم قراءة أوضح لحركة BTC/USD ويساعدك على متابعة السوق بهدوء ووعي أكبر.\n\nصُمم البوت ليختصر الضوضاء، يراقب تغيرات السوق، ويعرض لك السيناريوهات المهمة بطريقة منظمة وسهلة الفهم.\n\n✨ ما يقدمه لك:\n▫️ قراءة أوضح لاتجاه السوق\n▫️ طبقة قرار ذكية لتصفية الضوضاء وتقييم جودة الفرصة قبل المخاطرة\n▫️ تنبيهات عند تغيّر ظروف السوق\n▫️ متابعة منظمة للصفقات النشطة\n▫️ عرض مبسّط للمخاطر والمستويات المهمة\n\nSazBot لا يعدك بالربح، لكنه يساعدك على اتخاذ قرارات أكثر هدوءاً وانضباطاً.\n\n⚠️ التحليل تعليمي فقط وليس توصية مالية. إدارة المخاطر مسؤوليتك.",
        "ind_rsi_oversold": "RSI تشبع بيعي", "ind_rsi_buy": "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي", "ind_rsi_sell": "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️", "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up": "EMAs صاعدة 📈", "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low": "بولنجر: دعم سفلي 🟢", "ind_bb_high": "بولنجر: مقاومة عليا 🔴",
        "ind_stoch_low": "Stochastic تشبع بيعي", "ind_stoch_high": "Stochastic تشبع شرائي",
        "stats_title": "إحصائيات SazBot", "closed_trades": "الصفقات المغلقة", "total": "الإجمالي", "wins": "رابحة", "breakeven_stat": "تعادل", "losses": "خاسرة", "win_rate": "نسبة النجاح", "avg_rr": "متوسط RR", "existing_trades": "الصفقات القائمة", "no_existing_trades": "لا توجد صفقات قائمة", "waiting_entry": "بانتظار منطقة الدخول", "tp2_done": "TP2 تم", "tp1_done": "TP1 تم", "active_no_target": "نشطة — لم يصل أي هدف بعد",
        "risk_warn_volatile": "⚡ السوق متقلب — استخدم حجم صفقة أصغر", "risk_warn_ranging": "↔️ السوق عرضي — الأهداف قد تكون محدودة", "risk_warn_monthly_bull_sell": "📈 الشهري صاعد — البيع عكس الاتجاه العام", "risk_warn_monthly_bear_buy": "📉 الشهري هابط — الشراء عكس الاتجاه العام", "risk_warn_weekly_bull_sell": "📈 الأسبوعي صاعد — البيع عكس الاتجاه", "risk_warn_weekly_bear_buy": "📉 الأسبوعي هابط — الشراء عكس الاتجاه", "risk_warn_rsi_against": "⚠️ دايفرجنس RSI يعاكس السيناريو", "risk_warn_counter_weekly": "⚠️ سيناريو عكس الاتجاه الأسبوعي — الأفضل التركيز على TP1 وTP2 فقط",
        "signal_expired_price": "السعر ابتعد عن منطقة الدخول الذكية قبل التفعيل.", "signal_expired_timeframes": "تغيّر توافق الفريمات، ولم تعد الإشارة صالحة.", "signal_expired_time": "انتهت مدة صلاحية الإشارة.", "auto_signal_title": "إشارة BTC تلقائية", "event_in": "خلال",
    },
    "en": {
        "choose_lang": "🟡 SazBot | BTC Signals\n\nChoose your language:",
        "welcome": "🟡 SazBot 2.1 | Decision Intelligence\n\nWelcome to a smarter BTC/USD decision experience.\n\nSazBot does not chase every trade. It first evaluates whether the market is worth the risk.\n\n🧠 What it helps with:\n▫️ A decision layer that filters market noise\n▫️ Opportunity quality before entry\n▫️ Clear market-state reading\n▫️ Decision quality before taking risk\n▫️ Structured trade monitoring and alerts\n\n🚫 Sometimes the best decision is not to trade.\n\n⚠️ Educational analysis only — not financial advice. Risk management is your responsibility.",
        "btn_btc": "🧠 BTC Decision Center",
        "btn_analysis_btc": "📖 Market Read",
        "btn_prices": "💰 Prices", "btn_about": "ℹ️ About SazBot",
        "btn_lang": "🌐 Language", "btn_trades": "📋 Active Trades",
        "btn_close_trade": "❌ Close Active Trade", "close_trade_title": "Choose the trade you want to close:",
        "btn_stats": "📊 Statistics",
        "no_open_trades": "📭 No open trades at the moment",
        "loading_trade": "⏳ SazBot 2.1 is scanning market quality and building the decision...",
        "loading_analysis": "⏳ Analyzing...",
        "loading_prices": "⏳ Fetching prices...",
        "failed": "❌ Data is temporarily unavailable. Please try again in a minute.",
        "error": "❌ Error: ",
        "no_signal": "⏳ No high-quality setup yet\n\nSazBot 2.1 sees waiting as safer than entering an incomplete setup.",
        "trade_header": "SazBot 2.1 | BTC Decision",
        "auto_header": "SazBot 2.1 | Auto BTC Opportunity",
        "update_header": "SazBot | BTC Trade Update",
        "analysis_header": "SazBot 2.1 | Market Read",
        "entry": "Reference Entry", "entry_zone": "Smart Entry Zone",
        "direction": "Market Bias",
        "confidence": "Confidence",
        "entry_basis": "Entry Basis",
        "weekly": "Weekly", "monthly": "Monthly",
        "bullish": "Bullish", "bearish": "Bearish", "neutral": "Neutral",
        "counter_trend": "⚠️ Counter-trend setup — shorter targets and tighter risk.",
        "trend_up": "📈 Trending up", "trend_down": "📉 Trending down", "ranging_market": "↔️ Ranging market", "high_volatility": "⚡ High volatility",
        "bearish_div": "📉 Bearish RSI divergence ⚠️", "bullish_div": "📈 Bullish RSI divergence ✅",
        "strong_sell_zone": "🔴 Strong sell zone", "strong_buy_zone": "🟢 Strong buy zone", "liquidity_zone": "🎯 Liquidity zone",
        "risk_check": "Risk Check", "risk_level": "Risk level", "key_levels": "Key Levels",
        "active_trade": "Active Trade", "pending": "Pending", "active": "Active", "opened": "Opened",
        "targets": "Targets", "market_filters_blocked": "⚪ Filters blocked the analysis or data is unavailable\n\nTry again in two minutes 🕐",
        "trade_health": "Trade Health Check", "distance": "Distance", "above": "above", "below": "below", "entry_zone_word": "entry zone",
        "risk_review": "Risk Review",
        "dna_conditions_deteriorated": "🧠 Decision layer sees a clear deterioration in setup quality.", "recommend_cancel": "🔴 Recommendation: Cancel — conditions deteriorated clearly", "recommend_review": "🟡 Recommendation: Review — one key risk without enough support", "recommend_keep": "🟢 Recommendation: Keep — conditions remain supportive", "recommend_monitor": "🟡 Recommendation: Monitor — mixed conditions",
        "full_reversal": "❌ Market conditions changed significantly", "frames_still_support": "Market conditions still support the setup", "frames_oppose": "Market conditions have changed significantly",
        "monthly_supports": "📆 Monthly bias supports the setup", "monthly_against": "📆 Monthly bias is against the setup", "weekly_supports": "🗓️ Weekly trend supports the setup", "weekly_against": "🗓️ Weekly trend is against the setup",
        "volatility_risk": "⚡ High volatility — risk increased", "ranging_risk": "↔️ Ranging market — targets may be harder to reach", "regime_supports": "📊 Market regime supports the direction", "regime_against": "📊 Market regime is against the direction", "rsi_against": "⚠️ RSI divergence is against the setup", "rsi_supports": "📈 RSI divergence supports the setup",
        "forced_note": "⚠️ Alternative higher-risk setup opened manually.",
        "btn_keep_trade": "✅ Keep Trade", "btn_keep_setup": "✅ Keep Setup", "btn_cancel_setup": "❌ Cancel Setup", "btn_activate_setup": "✅ Activate Setup", "btn_ignore": "❌ Ignore", "btn_update_setup": "✅ Update Setup",
        "auto_cancel_timeframes": "❌ Auto-cancelled: market conditions changed significantly", "auto_cancel_conditions": "❌ Auto-cancelled: conditions deteriorated",
        "setup_activated": "Trade Activated", "price_reached_entry": "Price reached the Smart Entry Zone. The setup is now active.",
        "setup_cancelled_full": "Setup Cancelled", "price_bias_changed": "Price reached the entry area, but the market bias changed to",
        "invalid_before_entry": "The price invalidated the setup before entry.", "entry_alert": "Entry Zone Alert", "approaching_entry": "Price is approaching the Smart Entry Zone.",
        "reference_entry": "Reference Entry", "actual_entry": "Actual Entry", "entry_reference_zone": "Reference Entry Zone", "override_blocked_distance": "❌ Setup rejected: price moved too far beyond the Smart Entry Zone and risk is no longer acceptable.", "override_blocked_frames": "❌ Setup rejected: market conditions are not supportive enough right now.", "high_impact_event": "High-Impact Event", "impact_high": "Impact: 🔴 High. Manage risk carefully.",
        "entry_update": "Entry Zone Update", "conditions_changed_before_activation": "Market conditions changed before activation.", "old_reference": "Old Reference", "new_reference": "New Reference",
        "price_moved_against": "The price moved against the Smart Entry Zone and market conditions changed.",
        "buy": "BUY ⬆️", "sell": "SELL ⬇️",
        "targets_section": "Potential Targets",
        "tp1": "TP1", "tp2": "TP2", "tp3": "TP3", "sl": "SL",
        "rr": "Reward / Risk",
        "fib_section": "Fibonacci Levels",
        "support": "Support", "resistance": "Resistance",
        "confluence": "Timeframe Alignment",
        "frame_1h": "1H", "frame_4h": "4H", "frame_1d": "Daily",
        "full_confluence": "Strong timeframe alignment",
        "partial_confluence": "Partial timeframe alignment",
        "no_confluence": "⏳ No high-quality setup yet",
        "qualified_note": "",
        "low_conf_note": "",
        "partial_title": "⚠️ Partial Alignment Detected",
        "no_quality_title": "⏳ No High-Quality Setup Yet",
        "partial_body": "The overall direction is visible, but market alignment is not complete yet.",
        "higher_risk_prompt": "An alternative setup is available, but it carries higher risk.",
        "no_trade_better": "No trade is better than a weak trade.",
        "btn_higher_risk": "🎯 View Available Setup",
        "btn_cancel": "❌ Cancel",
        "btn_retry": "🔄 Re-analyse",
        "request_expired": "⚠️ Request Expired\n\nPlease request a fresh setup.",
        "existing_trade_kept": "✅ Existing Trade Kept",
        "setup_kept": "✅ Setup Kept",
        "setup_cancelled": "❌ Setup Cancelled",
        "cancelled_waiting": "✅ Cancelled. Waiting for a stronger setup.",
        "preparing_available": "⏳ Preparing the available setup...",
        "higher_risk_warning": "⚠️ This setup carries higher risk because alignment is not complete. Consider smaller size and strict risk management. No trade is better than a weak trade.",
        "duplicate_setup": "⚠️ A similar setup is already active",
        "existing_entry_zone": "Existing Entry Zone",
        "previous_entry_zone": "Previous Entry Zone",
        "no_new_trade_needed": "Current price is close — no need for a new trade",
        "indicators_section": "Indicators",
        "risk_low": "🟢 Low", "risk_med": "🟡 Medium", "risk_high": "🔴 High",
        "risk_low_msg": "Clean setup — Lower risk",
        "risk_med_msg": "Acceptable setup, but manage risk carefully",
        "risk_high_msg": "Higher risk — consider smaller size or waiting",
        "footer": "⚠️ Educational analysis only — not financial advice. Risk management is your responsibility.",
        "updated_gmt": "Last update (GMT)",
        "update_tp1_hit": "✅ TP1 reached! SL moved to entry",
        "update_tp2_hit": "✅✅ TP2 reached! SL moved to TP2",
        "update_sl_moved": "📊 Stop Loss moved to safety",
        "tp3_hit": "🏆 TP3 reached — trade closed successfully.",
        "tp1_hit": "✅ TP1 reached — SL moved to entry.",
        "tp2_hit": "✅✅ TP2 reached — SL moved to protect profit.",
        "protected_profit": "✅ Protected profit — SL reached after TP2.",
        "breakeven": "🟡 Breakeven — trade closed without loss.",
        "sl_hit": "🛑 Stop Loss hit — trade closed.",
        "trailing_sl": "📊 Trailing SL updated",
        "current_price": "Current Price",
        "trend_bull": "📈 Trend: Bullish", "trend_bear": "📉 Trend: Bearish",
        "trend_neutral": "➡️ Trend: Neutral",
        "rsi_oversold": "Oversold — Possible buying pressure",
        "rsi_overbought": "Overbought — Possible selling pressure",
        "rsi_neutral": "Neutral zone",
        "macd_bull": "MACD: Positive momentum ↗️", "macd_bear": "MACD: Negative momentum ↘️",
        "ema_bull": "EMAs: Bullish stack 📈", "ema_bear": "EMAs: Bearish stack 📉",
        "ema_mixed": "EMAs: Mixed signals ↔️",
        "bb_low": "Bollinger: At lower support",
        "bb_high": "Bollinger: At upper resistance",
        "bb_mid": "Bollinger: Middle zone",
        "summary_bull": "✅ Summary: Market leaning bullish",
        "summary_bear": "✅ Summary: Market leaning bearish",
        "summary_neutral": "🧭 Summary: Market in consolidation",
        "prices_title": "💰 Current Prices", "change_24h": "24h Change",
        "about_text": "ℹ️ About SazBot 2.1 🟡\n\nSazBot was built by someone genuinely passionate about markets and technology, with one goal: to make BTC/USD market reading clearer, calmer, and easier to follow.\n\nThe bot helps reduce noise, monitor changing market conditions, and present important scenarios in a simple, organised format.\n\n✨ What it helps with:\n▫️ Clear market reading\n▫️ A decision layer that filters market noise and evaluates opportunity quality before risk\n▫️ Alerts when conditions change\n▫️ Structured tracking for active trades\n▫️ Simple risk and level summaries\n\nSazBot does not promise profit. It helps you approach the market with more discipline and clarity.\n\n⚠️ Educational analysis only — not financial advice. Risk management is your responsibility.",
        "ind_rsi_oversold": "RSI Oversold", "ind_rsi_buy": "RSI Buy Zone",
        "ind_rsi_overbought": "RSI Overbought", "ind_rsi_sell": "RSI Sell Zone",
        "ind_macd_pos": "MACD Positive ↗️", "ind_macd_neg": "MACD Negative ↘️",
        "ind_ema_up": "EMAs Bullish 📈", "ind_ema_down": "EMAs Bearish 📉",
        "ind_bb_low": "Bollinger: Lower Support 🟢", "ind_bb_high": "Bollinger: Upper Resistance 🔴",
        "ind_stoch_low": "Stochastic Oversold", "ind_stoch_high": "Stochastic Overbought",
        "stats_title": "SazBot Statistics", "closed_trades": "Closed Trades", "total": "Total", "wins": "Wins", "breakeven_stat": "Breakeven", "losses": "Losses", "win_rate": "Win Rate", "avg_rr": "Average RR", "existing_trades": "Open Trades", "no_existing_trades": "No open trades", "waiting_entry": "Waiting for entry zone", "tp2_done": "TP2 hit", "tp1_done": "TP1 hit", "active_no_target": "Active — no target hit yet",
        "risk_warn_volatile": "⚡ Volatile market — consider smaller size", "risk_warn_ranging": "↔️ Ranging market — targets may be limited", "risk_warn_monthly_bull_sell": "📈 Monthly bias is bullish — SELL is counter-trend", "risk_warn_monthly_bear_buy": "📉 Monthly bias is bearish — BUY is counter-trend", "risk_warn_weekly_bull_sell": "📈 Weekly trend is bullish — SELL is counter-trend", "risk_warn_weekly_bear_buy": "📉 Weekly trend is bearish — BUY is counter-trend", "risk_warn_rsi_against": "⚠️ RSI divergence is against the setup", "risk_warn_counter_weekly": "⚠️ Counter-weekly setup — focus on TP1 and TP2 only",
        "signal_expired_price": "Price moved too far from the Smart Entry Zone before activation.", "signal_expired_timeframes": "Market conditions changed and the setup is no longer valid.", "signal_expired_time": "The signal validity period has expired.", "auto_signal_title": "Auto BTC Signal", "event_in": "in",
    }
}

def t(uid, key):
    lang = user_languages.get(uid, "ar")
    return TEXTS[lang].get(key, key)


def display_frame_line(uid, line: str) -> str:
    """Return a user-facing timeframe line without exposing internal eligibility markers."""
    lang = user_languages.get(uid, "ar")
    remove_tokens = [
        " ✅",
        " ⚪ " + TEXTS.get("ar", {}).get("low_conf_note", "إشارة ضعيفة"),
        " ⚪ " + TEXTS.get("en", {}).get("low_conf_note", "Weak signal"),
        " ⚪ إشارة ضعيفة",
        " ⚪ Weak signal",
    ]
    cleaned = str(line)
    for token in remove_tokens:
        cleaned = cleaned.replace(token, "")
    return cleaned.strip()


# ==================== SazBot 2.0 Decision Intelligence Layer ====================
def _clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return lo

def _frame_snapshot(res):
    """Parse public frame lines into a lightweight direction/confidence snapshot."""
    out = []
    for raw in res.get("frame_lines", []) or []:
        line = display_frame_line(0, raw)
        direction = "NEUTRAL"
        if "BUY" in line:
            direction = "BUY"
        elif "SELL" in line:
            direction = "SELL"
        m = re.search(r"\((\d+)\s*%\)", line)
        conf = int(m.group(1)) if m else 0
        name = line.split(":")[0].strip()
        out.append({"name": name, "direction": direction, "conf": conf, "raw": line})
    return out

def _direction_bias_score(frames):
    """A user-facing bias proxy, not a disclosed trading rule."""
    buy = sum(f["conf"] for f in frames if f["direction"] == "BUY")
    sell = sum(f["conf"] for f in frames if f["direction"] == "SELL")
    total = buy + sell
    if total <= 0:
        return 0, "NEUTRAL"
    if buy > sell:
        return _clamp((buy / total) * 100), "BUY"
    if sell > buy:
        return _clamp((sell / total) * 100), "SELL"
    return 50, "NEUTRAL"

def _saz_regime_from_res(res, uid=0):
    lang = user_languages.get(uid, "ar")
    rg = res.get("regime", "UNKNOWN")
    rsi = float(res.get("rsi", 50) or 50)
    bb = res.get("bb_zone", "mid")
    ema_bull = bool(res.get("ema_bull"))
    ema_bear = bool(res.get("ema_bear"))
    macd_bull = bool(res.get("macd_bull"))
    if rg == "VOLATILE":
        return ("سوق عالي التذبذب" if lang == "ar" else "High-volatility market"), "VOLATILE"
    if rg == "RANGING":
        return ("سوق عرضي / متردد" if lang == "ar" else "Range / indecisive market"), "RANGE"
    if ema_bull and macd_bull and rsi < 72:
        return ("اتجاه صاعد منضبط" if lang == "ar" else "Controlled bullish trend"), "TREND_UP"
    if ema_bear and not macd_bull and rsi > 28:
        return ("اتجاه هابط منضبط" if lang == "ar" else "Controlled bearish trend"), "TREND_DOWN"
    if bb in ("high", "low") and (rsi > 68 or rsi < 32):
        return ("منطقة اندفاع قد تعكس حركة مفاجئة" if lang == "ar" else "Extended move with reversal risk"), "EXTENDED"
    return ("منطقة انتظار وتقييم" if lang == "ar" else "Wait-and-evaluate zone"), "WAIT"


# ==================== SazBot Final ABC Setup Grading ====================
def saz_setup_grade(metrics):
    """Convert internal DNA metrics into a clear setup grade.
    A/B remain selective. C is intentionally wider so SazBot does not miss valid BTC moves.
    """
    try:
        q = float(metrics.get("quality", 0))
        r = float(metrics.get("regret", 100))
        if q >= 80 and r <= 45:
            return "A"
        if q >= 65 and r <= 62:
            return "B"
        if q >= 45 and r <= 82:
            return "C"
        return "REJECT"
    except Exception:
        return "REJECT"

def saz_grade_label(grade, uid=0):
    lang = user_languages.get(uid, "ar")
    if lang == "ar":
        return {
            "A": "🟢 A Setup | فرصة ممتازة",
            "B": "🟡 B Setup | فرصة جيدة",
            "C": "🟠 C Setup | فرصة مضاربة",
            "REJECT": "🚫 لا توجد فرصة مناسبة",
        }.get(grade, "🚫 لا توجد فرصة مناسبة")
    return {
        "A": "🟢 A Setup | Elite opportunity",
        "B": "🟡 B Setup | Good opportunity",
        "C": "🟠 C Setup | Aggressive opportunity",
        "REJECT": "🚫 No suitable setup",
    }.get(grade, "🚫 No suitable setup")

def saz_grade_risk_label(grade, uid=0):
    lang = user_languages.get(uid, "ar")
    if lang == "ar":
        return {"A": "منخفضة", "B": "متوسطة", "C": "مرتفعة", "REJECT": "مرتفعة"}.get(grade, "مرتفعة")
    return {"A": "Low", "B": "Medium", "C": "High", "REJECT": "High"}.get(grade, "High")


def event_risk_adjustment(uid=0):
    """Return (quality_penalty, regret_add, auto_block, label) based on high-impact events."""
    try:
        ev = get_upcoming_event(2)
        if not ev:
            return 0, 0, False, ""
        mins = float(ev.get("mins_left", 9999) or 9999)
        name = ev.get("event", "")
        if mins <= 30:
            return 18, 22, True, name
        if mins <= 120:
            return 10, 12, False, name
        return 0, 0, False, ""
    except Exception as e:
        logger.warning("event_risk_adjustment failed: " + str(e))
        return 0, 0, False, ""


def saz_decision_intelligence(res, uid=0, persist=True, refresh=False):
    """SazBot 2.1: decision intelligence based on live analysis, market memory, and behavioural risk.
    It does not promise outcomes; it ranks whether the current opportunity deserves attention.

    Important: metrics are calculated once per analysis result and reused across UI messages.
    This avoids inconsistent scores between No Setup, Market Read, Trade Signal and Health Check.
    """
    if isinstance(res, dict) and not refresh and isinstance(res.get("decision_metrics"), dict):
        return res["decision_metrics"]
    lang = user_languages.get(uid, "ar")
    frames = _frame_snapshot(res)
    bias_strength, frame_bias = _direction_bias_score(frames)
    final = res.get("final", "NEUTRAL")
    base_conf = float(res.get("base_conf", 0) or 0)
    rr = float(res.get("rr", 0) or 0)
    price = float(res.get("price", 0) or 0)
    entry_low = float(res.get("entry_low", res.get("entry_price", price)) or price or 0)
    entry_high = float(res.get("entry_high", res.get("entry_price", price)) or price or 0)
    atr = float(res.get("atr", 0) or 0)
    rsi = float(res.get("rsi", 50) or 50)
    weekly = res.get("weekly_trend", "NEUTRAL")
    monthly = res.get("monthly_bias", "NEUTRAL")
    regime_txt, regime_code = _saz_regime_from_res(res, uid)

    dist = distance_from_entry_zone_pct(price, entry_low, entry_high) if price and entry_low and entry_high else 0
    atr_pct = (atr / price * 100) if price and atr else 0

    counter_weekly = (final == "BUY" and weekly == "BEAR") or (final == "SELL" and weekly == "BULL")
    counter_monthly = (final == "BUY" and monthly == "BEAR") or (final == "SELL" and monthly == "BULL")
    dirs = [f["direction"] for f in frames if f["direction"] != "NEUTRAL"]
    mixed_frames = len(set(dirs)) > 1

    quality = 45
    if final in ("BUY", "SELL"):
        quality += min(max(base_conf - 50, 0), 35)
    else:
        quality -= 8
    quality += min(max((rr - 1.0) * 10, 0), 15)
    quality += min(max(bias_strength - 50, 0) * 0.25, 12)
    if regime_code in ("TREND_UP", "TREND_DOWN"):
        quality += 8
    if regime_code in ("RANGE", "WAIT"):
        quality -= 8
    if regime_code == "VOLATILE":
        quality -= 12
    if counter_weekly:
        quality -= 8
    if counter_monthly:
        quality -= 5
    if mixed_frames:
        quality -= 5
    # directional_rescue_bonus:
    # If 1H and Daily agree strongly, do not over-penalise only because 4H is temporarily opposite.
    try:
        f1 = next((f for f in frames if "1H" in f.get("name", "") or "ساعة" in f.get("name", "")), {})
        fd = next((f for f in frames if "Daily" in f.get("name", "") or "يومي" in f.get("name", "")), {})
        if f1.get("direction") == fd.get("direction") and f1.get("direction") in ("BUY", "SELL"):
            if f1.get("conf", 0) >= 70 and fd.get("conf", 0) >= 65:
                quality += 8
                regret -= 6
    except Exception:
        pass
    # strong_trend_bonus: very strong lower/higher timeframe readings deserve a small quality boost
    try:
        strong_count = len([f for f in frames if f.get("conf", 0) >= 82 and f.get("direction") in ("BUY", "SELL")])
        if strong_count >= 1:
            quality += min(5 * strong_count, 10)
    except Exception as e:
        logger.warning("silent exception: " + str(e))
    if dist > 0.8:
        quality -= min(dist * 8, 16)
    if rsi > 74 or rsi < 26:
        quality -= 8

    energy = 35 + min(atr_pct * 18, 35)
    if res.get("macd_bull") or res.get("ema_bull") or res.get("ema_bear"):
        energy += 8
    if regime_code == "VOLATILE":
        energy += 20
    if regime_code == "RANGE":
        energy -= 5
    energy = _clamp(energy)

    # Crowd / move conviction: concentration of agreement + momentum alignment.
    conviction = 35 + max(bias_strength - 50, 0) * 0.8
    if not mixed_frames and frame_bias in ("BUY", "SELL"):
        conviction += 15
    if regime_code in ("TREND_UP", "TREND_DOWN"):
        conviction += 10
    if regime_code == "RANGE":
        conviction -= 10
    conviction = _clamp(conviction)

    # Crowd exhaustion: not sentiment scraping; a live market-behaviour proxy.
    exhaustion = 0
    if conviction > 78:
        exhaustion += 30
    if energy > 75:
        exhaustion += 25
    if rsi > 70 or rsi < 30:
        exhaustion += 20
    if dist > 0.8:
        exhaustion += 15
    if regime_code == "EXTENDED":
        exhaustion += 20
    crowd_exhaustion = _clamp(exhaustion)
    if crowd_exhaustion >= 70:
        quality -= 10

    # Market memory: opportunity cost and narrative shift.
    memory = recent_saz_memory(48)
    recent_quality = [float(x.get("quality", 0)) for x in memory]
    recent_avg_quality = sum(recent_quality) / len(recent_quality) if recent_quality else 55
    recent_strong = len([q for q in recent_quality if q >= 78])
    last = memory[-1] if memory else {}
    last_bias = last.get("frame_bias", "NEUTRAL")
    last_regime = last.get("regime_code", "")
    narrative_shift_score = 0
    if last_bias in ("BUY", "SELL") and frame_bias in ("BUY", "SELL") and last_bias != frame_bias:
        narrative_shift_score += 45
    if last_regime and last_regime != regime_code:
        narrative_shift_score += 25
    if mixed_frames:
        narrative_shift_score += 20
    narrative_shift_score = _clamp(narrative_shift_score)

    opportunity_cost = 35
    if quality < recent_avg_quality - 5:
        opportunity_cost += 25
    if recent_strong >= 2 and quality < 75:
        opportunity_cost += 20
    if counter_weekly or counter_monthly or mixed_frames:
        opportunity_cost += 10
    opportunity_cost = _clamp(opportunity_cost)
    # Event risk is part of the DNA, not only a notification.
    ev_q_penalty, ev_regret_add, ev_auto_block, event_risk_label = event_risk_adjustment(uid)
    if ev_q_penalty:
        quality -= ev_q_penalty
        regret += ev_regret_add

    # Opportunity cost affects the final decision, but should not double-penalise quality.
    quality = _clamp(quality)

    regret = 100 - quality
    if dist > 0.8:
        regret += min(dist * 10, 20)
    if counter_weekly or counter_monthly:
        regret += 15
    if regime_code == "VOLATILE":
        regret += 10
    if mixed_frames:
        regret += 8
    if crowd_exhaustion >= 70:
        regret += 16
    if opportunity_cost >= 70:
        regret += 8
    regret = _clamp(regret)

    if narrative_shift_score >= 65:
        narrative = "SHIFTING"
    elif regime_code == "VOLATILE" or crowd_exhaustion >= 75:
        narrative = "UNSTABLE"
    elif final in ("BUY", "SELL") and not mixed_frames:
        narrative = "CONSISTENT"
    else:
        narrative = "UNCLEAR"

    if quality >= 80 and regret <= 35 and opportunity_cost < 65:
        opportunity = "HIGH"
    elif quality >= 62 and regret <= 55:
        opportunity = "MEDIUM"
    else:
        opportunity = "LOW"

    if quality < 55 or regret > 68 or opportunity_cost >= 78 or crowd_exhaustion >= 85 or (final == "NEUTRAL" and mixed_frames):
        decision = "STAY_OUT"
    elif opportunity == "LOW":
        decision = "WAIT"
    elif final in ("BUY", "SELL"):
        decision = "TRADEABLE"
    else:
        decision = "WAIT"

    if lang == "ar":
        labels = {
            "STAY_OUT": "🚫 ابقَ خارج السوق",
            "WAIT": "⏳ انتظر فرصة أنظف",
            "TRADEABLE": "🎯 فرصة قابلة للمتابعة",
            "HIGH": "مرتفعة",
            "MEDIUM": "متوسطة",
            "LOW": "منخفضة",
            "SHIFTING": "الرواية تتغير بين الفريمات",
            "UNSTABLE": "السوق سريع التغير",
            "CONSISTENT": "الرواية متماسكة",
            "UNCLEAR": "الرواية غير واضحة",
        }
        exhaustion_txt = "مرتفع" if crowd_exhaustion >= 70 else "متوسط" if crowd_exhaustion >= 45 else "منخفض"
        opp_cost_txt = "مرتفع" if opportunity_cost >= 70 else "متوسط" if opportunity_cost >= 45 else "منخفض"
        if decision == "STAY_OUT":
            story = "السوق لا يقدم فرصة نظيفة حالياً. حماية رأس المال أفضل من مطاردة حركة غير مكتملة."
        elif decision == "WAIT":
            story = "هناك حركة في السوق، لكن الانتظار يمنح أفضلية أعلى من الاستعجال."
        else:
            story = "الفرصة قابلة للمتابعة، بشرط احترام منطقة الدخول وإدارة المخاطر."
    else:
        labels = {
            "STAY_OUT": "🚫 Stay out",
            "WAIT": "⏳ Wait for a cleaner setup",
            "TRADEABLE": "🎯 Tradeable setup",
            "HIGH": "High",
            "MEDIUM": "Medium",
            "LOW": "Low",
            "SHIFTING": "Narrative is shifting across timeframes",
            "UNSTABLE": "Market is changing quickly",
            "CONSISTENT": "Narrative is consistent",
            "UNCLEAR": "Narrative is unclear",
        }
        exhaustion_txt = "High" if crowd_exhaustion >= 70 else "Medium" if crowd_exhaustion >= 45 else "Low"
        opp_cost_txt = "High" if opportunity_cost >= 70 else "Medium" if opportunity_cost >= 45 else "Low"
        if decision == "STAY_OUT":
            story = "The market is not offering a clean opportunity right now. Protecting capital is better than chasing an incomplete move."
        elif decision == "WAIT":
            story = "There is movement, but waiting offers a better edge than rushing."
        else:
            story = "The setup is worth monitoring, provided entry discipline and risk management are respected."

    snapshot = {
        "ts": now_ts(), "quality": quality, "energy": energy, "regret": regret,
        "conviction": conviction, "frame_bias": frame_bias, "regime_code": regime_code,
        "narrative": narrative, "decision": decision,
    }
    if persist:
        update_saz_memory(snapshot)

    metrics = {
        "quality": quality,
        "energy": energy,
        "regret": regret,
        "conviction": conviction,
        "crowd_exhaustion": crowd_exhaustion,
        "crowd_exhaustion_text": exhaustion_txt,
        "opportunity_cost": opportunity_cost,
        "opportunity_cost_text": opp_cost_txt,
        "narrative_shift_score": narrative_shift_score,
        "regime_text": regime_txt,
        "decision": decision,
        "decision_text": labels[decision],
        "opportunity": opportunity,
        "opportunity_text": labels[opportunity],
        "narrative": narrative,
        "narrative_text": labels[narrative],
        "story": story,
        "event_risk_label": event_risk_label if "event_risk_label" in locals() else "",
        "event_auto_block": ev_auto_block if "ev_auto_block" in locals() else False,
    }
    metrics["setup_grade"] = saz_setup_grade(metrics)
    if isinstance(res, dict):
        res["decision_metrics"] = metrics
    return metrics


def saz_decision_gate(res, uid=0):
    """Final safety gate: SazBot 2.1 DNA is part of the decision engine, not the UI."""
    try:
        if not res or res.get("final") not in ("BUY", "SELL"):
            return res
        return apply_saz_dna_gate(res, uid, mode="manual")
    except Exception as e:
        logger.warning("saz_decision_gate: " + str(e))
        return apply_saz_dna_gate(res, uid, mode="manual")

def saz_intelligence_block(res, uid=0, compact=False):
    """Clean user-facing decision summary. Internal DNA remains richer."""
    lang = user_languages.get(uid, "ar")
    m = saz_decision_intelligence(res, uid)
    quality = int(m.get("quality", 0))
    grade = m.get("setup_grade") or saz_setup_grade(m)
    risk_label = saz_grade_risk_label(grade, uid)
    grade_label = saz_grade_label(grade, uid)

    if lang == "ar":
        lines = [
            "🧠 تقييم SazBot",
            f"🏷️ التصنيف: {grade_label}",
            f"📊 جودة السوق: {quality}/100",
            f"⚠️ مستوى المخاطرة: {risk_label}",
            f"🧭 الحالة: {m['regime_text']}",
            f"🎯 القرار: {m['decision_text']}",
        ]
        if not compact:
            if grade == "REJECT":
                lines.append("السوق لا يقدم فرصة مناسبة حالياً. الانتظار أفضل من الدخول في سيناريو غير مكتمل.")
            elif grade == "C":
                lines.append("هذه فرصة مضاربة وليست من أفضل الفرص. استخدم مخاطرة أقل والتزم بمنطقة الدخول.")
            elif grade == "B":
                lines.append("الفرصة جيدة، لكنها تحتاج التزاماً واضحاً بإدارة المخاطر.")
            else:
                lines.append("الفرصة قوية نسبياً، مع ضرورة الالتزام بمنطقة الدخول وإدارة المخاطر.")
    else:
        lines = [
            "🧠 SazBot Assessment",
            f"🏷️ Grade: {grade_label}",
            f"📊 Market Quality: {quality}/100",
            f"⚠️ Risk Level: {risk_label}",
            f"🧭 State: {m['regime_text']}",
            f"🎯 Decision: {m['decision_text']}",
        ]
        if not compact:
            if grade == "REJECT":
                lines.append("The market is not offering a suitable setup right now. Waiting is better than forcing an incomplete scenario.")
            elif grade == "C":
                lines.append("This is an aggressive setup, not a top-quality opportunity. Use smaller risk and strict entry discipline.")
            elif grade == "B":
                lines.append("This is a good setup, but it still requires disciplined risk management.")
            else:
                lines.append("This is a relatively strong setup, provided entry discipline and risk management are respected.")
    return lines

def safe_saz_intelligence_block(res, uid=0, compact=False):
    """User-facing SazBot 2.1 decision layer.
    This wrapper must never fail silently in UI paths.
    """
    try:
        return saz_intelligence_block(res, uid, compact=compact)
    except Exception as e:
        logger.error("safe_saz_intelligence_block failed: " + str(e))
        lang = user_languages.get(uid, "ar")
        if lang == "ar":
            return [
                "🧠 تقييم SazBot 2.1",
                "📊 جودة السوق: منخفضة",
                "⚠️ مستوى المخاطرة: مرتفعة",
                "🧭 الحالة: غير واضحة",
                "🎯 القرار: 🚫 ابقَ خارج السوق",
                "السوق لا يقدم فرصة نظيفة حالياً. يفضل انتظار وضوح أكبر قبل المخاطرة.",
            ]
        return [
            "🧠 SazBot 2.1 Assessment",
            "📊 Market Quality: Low",
            "⚠️ Risk Level: High",
            "🧭 State: Unclear",
            "🎯 Decision: 🚫 Stay out",
            "The market is not offering a clean opportunity right now. Waiting for more clarity is the better decision.",
        ]


# ==================== SazBot 2.1 DNA Decision Gate ====================
# This is not a UI layer. It is the core decision filter used before any setup is shown,
# auto-sent, overridden, or kept alive.
SAZ_DNA_LIMITS = {
    "manual":   {"min_quality": 45, "max_regret": 82, "max_opp_cost": 78, "max_exhaustion": 84},
    "auto":     {"min_quality": 52, "max_regret": 78, "max_opp_cost": 72, "max_exhaustion": 76},
    "override": {"min_quality": 50, "max_regret": 78, "max_opp_cost": 75, "max_exhaustion": 78},
    "health":   {"min_quality": 50, "max_regret": 76, "max_opp_cost": 82, "max_exhaustion": 88},
}

def saz_dna_assessment(res, uid=0, mode="manual"):
    """Return (allowed, metrics, reason_key). This is the SazBot 2.1 DNA gate."""
    try:
        if not res or res.get("final") not in ("BUY", "SELL"):
            m = saz_decision_intelligence(res or {}, uid, persist=False)
            return False, m, "no_direction"

        m = saz_decision_intelligence(res, uid, persist=False, refresh=False)
        limits = SAZ_DNA_LIMITS.get(mode, SAZ_DNA_LIMITS["manual"])

        grade = m.get("setup_grade") or saz_setup_grade(m)
        m["setup_grade"] = grade

        # ABC model:
        # A/B are approved. C can be approved for manual/override as aggressive, but auto requires B or A.
        if grade == "REJECT":
            return False, m, "grade_reject"

        if mode == "auto" and m.get("event_auto_block"):
            return False, m, "auto_event_block"

        if mode == "auto" and grade not in ("A", "B"):
            # Allow C setups for BTC when risk is still controlled; label keeps it transparent.
            if not (grade == "C" and float(m.get("quality", 0)) >= 45 and float(m.get("regret", 100)) <= 82):
                return False, m, "auto_requires_abc_controlled"

        if mode == "override" and grade not in ("A", "B", "C"):
            return False, m, "override_reject"

        # Hard safety limits still apply, but less binary than before.
        if float(m.get("regret", 100)) > limits["max_regret"] and grade != "A":
            return False, m, "regret_high"
        if float(m.get("opportunity_cost", 100)) > limits["max_opp_cost"] and grade == "C":
            return False, m, "opportunity_cost_high"
        if float(m.get("crowd_exhaustion", 100)) > limits["max_exhaustion"]:
            return False, m, "exhaustion_high"

        return True, m, "allowed"
    except Exception as e:
        logger.error("saz_dna_assessment failed: " + str(e))
        # Fail closed: if the DNA layer breaks, SazBot should not open a trade blindly.
        fallback = {
            "decision": "STAY_OUT",
            "quality": 0,
            "regret": 100,
            "opportunity_cost": 100,
            "crowd_exhaustion": 100,
        }
        return False, fallback, "dna_error"

def apply_saz_dna_gate(res, uid=0, mode="manual"):
    """Convert a technically-valid setup into NEUTRAL if the DNA gate rejects it."""
    allowed, metrics, reason = saz_dna_assessment(res, uid, mode)
    if allowed:
        if isinstance(res, dict):
            res["decision_metrics"] = metrics
            res["saz_dna_reason"] = reason
        return res

    blocked = dict(res or {})
    blocked["blocked_by_saz_dna"] = True
    blocked["decision_metrics"] = metrics
    blocked["saz_dna_reason"] = reason
    blocked["majority"] = None
    blocked["final"] = "NEUTRAL"
    blocked["base_conf"] = 0
    blocked["confidence"] = 0
    blocked["tp1"] = blocked["tp2"] = blocked["tp3"] = blocked["sl"] = 0
    blocked["rr"] = 0
    blocked["confluence_txt"] = ""
    return blocked

def saz_dna_rejection_message(res, uid=0):
    """User-facing explanation that shows the decision, not the internal rule."""
    lang = user_languages.get(uid, "ar")
    lines = []
    if lang == "ar":
        lines += [
            "🚫 SazBot 2.1 لم يعتمد هذه الفرصة",
            "",
        ]
        lines += safe_saz_intelligence_block(res, uid, compact=False)
        lines += [
            "",
            "القرار النهائي: الانتظار أفضل من الدخول في فرصة غير مكتملة.",
        ]
    else:
        lines += [
            "🚫 SazBot 2.1 did not approve this setup",
            "",
        ]
        lines += safe_saz_intelligence_block(res, uid, compact=False)
        lines += [
            "",
            "Final decision: waiting is better than entering an incomplete setup.",
        ]
    return "\n".join(lines)


def can_show_override_option(res, uid=0):
    """Return True only if the available setup can actually be displayed.
    This prevents showing the override button and then rejecting it immediately.
    """
    try:
        if not res or res.get("majority") not in ("BUY", "SELL"):
            return False

        test = dict(res)
        best_dir = res.get("majority")
        test["final"] = best_dir
        test["base_conf"] = max(float(test.get("base_conf", 0) or 0), 65)

        price = float(test.get("price", 0) or 0)
        entry = float(test.get("entry_price", price) or price)
        atr = float(test.get("atr", entry * 0.015) or entry * 0.015)
        entry_low = float(test.get("entry_low", entry - ENTRY_ZONE_ATR_FACTOR * atr) or entry)
        entry_high = float(test.get("entry_high", entry + ENTRY_ZONE_ATR_FACTOR * atr) or entry)

        if not price or not entry:
            return False

        if is_price_too_far_from_entry_zone(price, entry_low, entry_high, OVERRIDE_MAX_DISTANCE_FROM_ZONE_PCT):
            return False

        allowed, _m, _reason = saz_dna_assessment(test, uid, mode="override")
        return bool(allowed)
    except Exception as e:
        logger.warning("can_show_override_option failed: " + str(e))
        return False


def recommended_leverage_by_regime(res):
    """Return conservative educational leverage guidance based on market regime and volatility."""
    try:
        price = float(res.get("price", 0) or 0)
        atr = float(res.get("atr", 0) or 0)
        atr_pct = (atr / price * 100) if price and atr else 1.0
        regime = res.get("regime", "UNKNOWN")
        metrics = res.get("decision_metrics") or {}
        grade = metrics.get("setup_grade") or saz_setup_grade(metrics) if metrics else "REJECT"

        if regime == "VOLATILE" or atr_pct >= 1.8 or grade in ("C", "REJECT"):
            return (
                "3x — 5x\n⚠️ السوق عالي المخاطرة؛ الأفضل تقليل الرافعة أو الانتظار",
                "3x — 5x\n⚠️ Higher-risk conditions; consider lower leverage or waiting",
            )
        if grade == "A" and atr_pct < 0.9:
            return (
                "8x — 12x\n⚠️ لا تتجاوز 12x حتى في الفرص القوية",
                "8x — 12x\n⚠️ Do not exceed 12x even on strong setups",
            )
        if grade == "B":
            return (
                "5x — 8x\n⚠️ استخدم إدارة مخاطرة صارمة",
                "5x — 8x\n⚠️ Use strict risk management",
            )
        return (
            "3x — 6x\n⚠️ الأفضل تقليل الحجم مع الظروف غير المكتملة",
            "3x — 6x\n⚠️ Consider smaller size in incomplete conditions",
        )
    except Exception:
        return (
            "3x — 5x\n⚠️ استخدم أقل رافعة ممكنة عند عدم وضوح السوق",
            "3x — 5x\n⚠️ Use the lowest practical leverage when conditions are unclear",
        )


async def run_blocking(func, *args, **kwargs):
    """Run blocking I/O or CPU-bound helper without freezing the Telegram event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def gmt_now():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M")

def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def _mins_txt(mins: int) -> str:
    """Convert minutes to Arabic readable string."""
    if mins < 60:
        return f"{mins} دقيقة"
    h = mins // 60; m = mins % 60
    return f"{h} ساعة{' و'+str(m)+' دقيقة' if m else ''}"

def _event_key(ev: dict) -> str:
    """Unique key for an economic event to avoid duplicate alerts."""
    return ev.get("event", "") + str(ev.get("time", ""))[:10]


# ==================== البيانات ====================
def get_binance_data(days=30, interval="hourly"):
    try:
        if interval == "hourly":
            binance_interval = "1h"
            limit = min(days * 24, 1000)
        elif interval == "4h":
            binance_interval = "4h"
            limit = min(days * 6, 1000)
        elif interval in ("weekly", "1w"):
            binance_interval = "1w"
            limit = min(max(days // 7, 30), 1000)
        else:
            binance_interval = "1d"
            limit = min(days, 1000)
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": binance_interval, "limit": limit},
            timeout=15
        )
        if r.status_code != 200:
            logger.warning("Binance status: " + str(r.status_code))
            return None
        data = r.json()
        if not data:
            return None
        rows = []
        for k in data:
            rows.append({
                "timestamp": pd.to_datetime(k[0], unit="ms"),
                "Open":   float(k[1]),
                "High":   float(k[2]),
                "Low":    float(k[3]),
                "Close":  float(k[4]),
                "Volume": float(k[5]),
            })
        df = pd.DataFrame(rows).set_index("timestamp").dropna()
        logger.info("Binance fallback OK: BTCUSDT " + binance_interval)
        return df
    except Exception as e:
        logger.warning("Binance failed: " + str(e))
        return None


def get_data(asset="BTC", days=30, interval="hourly"):
    cache_key = asset + "_" + str(days) + "_" + interval
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    if TWELVEDATA_KEY:
        try:
            if interval == "hourly":
                td_interval = "1h"
                outputsize  = min(days * 24, 500)
            elif interval == "4h":
                td_interval = "4h"
                outputsize  = min(days * 6, 500)
            elif interval in ("weekly", "1w"):
                td_interval = "1week"
                outputsize  = min(max(days // 7, 30), 500)
            else:
                td_interval = "1day"
                outputsize  = min(days, 500)
            r = requests.get("https://api.twelvedata.com/time_series",
                params={"symbol": "BTC/USD", "interval": td_interval,
                        "outputsize": outputsize, "apikey": TWELVEDATA_KEY, "format": "JSON"},
                timeout=15)
            data = r.json()
            if "values" in data and len(data["values"]) > 0:
                rows = [{"timestamp": pd.to_datetime(v["datetime"]),
                         "Open": float(v["open"]), "High": float(v["high"]),
                         "Low": float(v["low"]), "Close": float(v["close"]),
                         "Volume": float(v.get("volume", 0))} for v in reversed(data["values"])]
                df = pd.DataFrame(rows).set_index("timestamp").dropna()
                set_cache(cache_key, df)
                return df
            else:
                logger.warning("Twelve Data: " + str(data.get("message", "")))
        except Exception as e:
            logger.warning("Twelve Data failed: " + str(e))

    df_binance = get_binance_data(days=days, interval=interval)
    if df_binance is not None and len(df_binance) >= 20:
        set_cache(cache_key, df_binance)
        return df_binance

    # ✅ FIX 3: 4H resample فقط لو الـ interval فعلاً 4h
    if interval == "4h":
        try:
            df_h = get_data(asset, days=days, interval="hourly")
            if df_h is not None and len(df_h) >= 20:
                df_4h_rs = df_h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
                if len(df_4h_rs) >= 10:
                    set_cache(cache_key, df_4h_rs)
                    logger.info("4H resample fallback used")
                    return df_4h_rs
        except Exception as e:
            logger.warning("4H resample fallback: " + str(e))

    try:
        import time; time.sleep(2)
        r = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": days}, timeout=20)
        if r.status_code == 429:
            time.sleep(60)
            r = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                params={"vs_currency": "usd", "days": days}, timeout=20)
        data = r.json()
        if "prices" not in data:
            return None
        df = pd.DataFrame(data["prices"], columns=["timestamp", "Close"])
        df["Volume"] = [v[1] for v in data["total_volumes"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        df["High"] = df["Close"].rolling(3).max()
        df["Low"]  = df["Close"].rolling(3).min()
        df["Open"] = df["Close"].shift(1)
        result = df.dropna()
        # ✅ FIX 3: resample فقط لو hourly — daily يبقى daily
        if interval == "hourly":
            result = result.resample("1h").interpolate(method="linear").dropna()
        elif interval == "4h":
            result = result.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        elif interval in ("weekly", "1w"):
            result = result.resample("1W").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        # daily: لا resample — البيانات كافية
        set_cache(cache_key, result)
        logger.info("CoinGecko fallback OK")
        return result
    except Exception as e:
        logger.error("CoinGecko error: " + str(e))

    return None


def get_btc_price():
    if TWELVEDATA_KEY:
        try:
            r = requests.get("https://api.twelvedata.com/price",
                params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY}, timeout=10)
            data = r.json()
            if "price" in data:
                return float(data["price"])
        except: pass
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"}, timeout=10)
        if r.status_code == 200:
            return float(r.json()["price"])
    except: pass
    try:
        import time; time.sleep(1)
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10)
        if r.status_code == 200:
            return float(r.json()["bitcoin"]["usd"])
    except: pass
    return None


def get_prices():
    """
    Fetch BTC price with strict validation.
    Priority: Twelve Data -> Binance -> CoinGecko.
    Never returns a zero/invalid price as a valid market price.
    """
    if TWELVEDATA_KEY:
        try:
            r1 = requests.get("https://api.twelvedata.com/price",
                params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY}, timeout=10)
            j1 = r1.json()
            if r1.status_code != 200 or "price" not in j1:
                raise ValueError(f"Invalid Twelve Data price response: {j1}")

            btc_price = float(j1.get("price", 0))
            if btc_price <= 0:
                raise ValueError(f"Invalid Twelve Data price value: {btc_price}")

            r2 = requests.get("https://api.twelvedata.com/time_series",
                params={"symbol": "BTC/USD", "interval": "1day", "outputsize": 2,
                        "apikey": TWELVEDATA_KEY}, timeout=10)
            j2 = r2.json()
            btc_data = j2.get("values", [])
            btc_change = 0.0
            if len(btc_data) >= 2:
                prev = float(btc_data[1]["close"])
                if prev > 0:
                    btc_change = round((btc_price - prev) / prev * 100, 2)

            return {"bitcoin": {"usd": btc_price, "usd_24h_change": btc_change}}
        except Exception as e:
            logger.warning("Twelve Data prices failed, trying Binance: " + str(e))

    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"}, timeout=10)
        r2 = requests.get("https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": "BTCUSDT"}, timeout=10)
        if r1.status_code == 200 and r2.status_code == 200:
            price  = float(r1.json().get("price", 0))
            change = float(r2.json().get("priceChangePercent", 0))
            if price <= 0:
                raise ValueError(f"Invalid Binance price value: {price}")
            return {"bitcoin": {"usd": price, "usd_24h_change": change}}
        raise ValueError(f"Invalid Binance status codes: {r1.status_code}, {r2.status_code}")
    except Exception as e:
        logger.warning("Binance prices failed, trying CoinGecko: " + str(e))

    try:
        import time; time.sleep(1)
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=10)
        if r.status_code == 200:
            j = r.json()
            price = float(j.get("bitcoin", {}).get("usd", 0))
            if price <= 0:
                raise ValueError(f"Invalid CoinGecko price value: {price}")
            return j
        raise ValueError(f"Invalid CoinGecko status code: {r.status_code}")
    except Exception as e:
        logger.warning("CoinGecko prices failed: " + str(e))

    return None


# ==================== Fibonacci ====================
def calculate_fibonacci(df):
    window = min(250, len(df))
    recent = df.tail(window)
    swing_high = float(recent["High"].max())
    swing_low  = float(recent["Low"].min())
    diff = swing_high - swing_low
    levels = {
        "0.0":   round(swing_high, 2),
        "23.6":  round(swing_high - 0.236 * diff, 2),
        "38.2":  round(swing_high - 0.382 * diff, 2),
        "50.0":  round(swing_high - 0.500 * diff, 2),
        "61.8":  round(swing_high - 0.618 * diff, 2),
        "78.6":  round(swing_high - 0.786 * diff, 2),
        "100.0": round(swing_low, 2),
    }
    extensions = {
        "127.2": round(swing_low - 0.272 * diff, 2),
        "161.8": round(swing_low - 0.618 * diff, 2),
        "200.0": round(swing_low - 1.000 * diff, 2),
    }
    return levels, extensions, swing_high, swing_low


def find_nearest_fib(price, levels, direction):
    fib_values = list(levels.values())
    nearest = min(fib_values, key=lambda x: abs(x - price))
    fib_key  = [k for k, v in levels.items() if v == nearest][0]
    dist_pct = abs(nearest - price) / price * 100
    return nearest, fib_key, dist_pct


def get_fib_targets(price, levels, extensions, direction, atr):
    fib_vals = sorted(levels.values())
    if direction == "BUY":
        sl = round(price - 0.8*atr, 2)
        tp1_c = [v for v in fib_vals if v > price + 0.3*atr]
        tp1 = round(tp1_c[0] if tp1_c else price + 0.8*atr, 2)
        tp2_c = [v for v in fib_vals if v > tp1 + 0.2*atr]
        tp2 = round(max(tp2_c[0] if tp2_c else price + 1.5*atr, price + 1.5*atr), 2)
        tp3_raw = round(price + 2.5*atr, 2)
        tp3_min = round(tp2 + 1.0*atr, 2)
        tp3 = round(max(tp3_raw, tp3_min), 2)
    else:
        sl = round(price + 0.8*atr, 2)
        tp1_c = [v for v in reversed(fib_vals) if v < price - 0.3*atr]
        tp1 = round(tp1_c[0] if tp1_c else price - 0.8*atr, 2)
        tp2_c = [v for v in reversed(fib_vals) if v < tp1 - 0.2*atr]
        tp2 = round(min(tp2_c[0] if tp2_c else price - 1.5*atr, price - 1.5*atr), 2)
        tp3_raw = round(price - 2.5*atr, 2)
        tp3_min = round(tp2 - 1.0*atr, 2)
        tp3 = round(min(tp3_raw, tp3_min), 2)
    rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
    return sl, tp1, tp2, tp3, rr


# ==================== المؤشرات ====================
def calc_indicators(df):
    df = df.copy()
    c = df["Close"]; h = df["High"]; l = df["Low"]
    df["EMA9"]   = ta.trend.EMAIndicator(c, window=9).ema_indicator()
    df["EMA21"]  = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df["EMA50"]  = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df["EMA200"] = ta.trend.EMAIndicator(c, window=200).ema_indicator()
    df["RSI"]    = ta.momentum.RSIIndicator(c, window=14).rsi()
    macd = ta.trend.MACD(c)
    df["MACD"]   = macd.macd()
    df["MACD_S"] = macd.macd_signal()
    df["MACD_H"] = macd.macd_diff()
    bb = ta.volatility.BollingerBands(c)
    df["BB_U"] = bb.bollinger_hband()
    df["BB_L"] = bb.bollinger_lband()
    df["ATR"]  = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    stoch = ta.momentum.StochasticOscillator(h, l, c)
    df["Stoch"]  = stoch.stoch()
    df["Stoch_S"]= stoch.stoch_signal()
    df["Pivot"] = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df["R1"] = 2 * df["Pivot"] - l.shift(1)
    df["S1"] = 2 * df["Pivot"] - h.shift(1)
    h9  = h.rolling(9).max();  l9  = l.rolling(9).min()
    h26 = h.rolling(26).max(); l26 = l.rolling(26).min()
    h52 = h.rolling(52).max(); l52 = l.rolling(52).min()
    df["Tenkan"] = (h9 + l9) / 2
    df["Kijun"]  = (h26 + l26) / 2
    df["SpanA"]  = ((df["Tenkan"] + df["Kijun"]) / 2).shift(26)
    df["SpanB"]  = ((h52 + l52) / 2).shift(26)
    try:
        if "Volume" in df.columns and df["Volume"].sum() > 0:
            df["Vol_MA"]  = df["Volume"].rolling(20).mean()
            df["Vol_High"]= df["Volume"] > df["Vol_MA"] * 1.5
        else:
            df["Vol_High"] = False
    except Exception as e:
        df["Vol_High"] = False
    return df


def safe(val, default):
    try:
        v = float(val)
        return default if pd.isna(v) else v
    except Exception as e:
        return default


def analyze_frame(df, uid=0):
    df   = calc_indicators(df)
    last = df.iloc[-1]
    price = float(last["Close"])
    sb = ss = 0
    details = []

    rsi = safe(last["RSI"], 50.0)
    if rsi < 30:   sb += 25; details.append(t(uid,"ind_rsi_oversold") + " (" + str(round(rsi,1)) + ") 🟢")
    elif rsi < 45: sb += 12; details.append(t(uid,"ind_rsi_buy")      + " (" + str(round(rsi,1)) + ")")
    elif rsi > 70: ss += 25; details.append(t(uid,"ind_rsi_overbought")+ " (" + str(round(rsi,1)) + ") 🔴")
    elif rsi > 55: ss += 12; details.append(t(uid,"ind_rsi_sell")      + " (" + str(round(rsi,1)) + ")")

    macd_v = safe(last["MACD"], 0); macd_s = safe(last["MACD_S"], 0); macd_h = safe(last["MACD_H"], 0)
    if macd_v > macd_s and macd_h > 0: sb += 20; details.append(t(uid,"ind_macd_pos"))
    elif macd_v < macd_s and macd_h < 0: ss += 20; details.append(t(uid,"ind_macd_neg"))

    e9  = safe(last["EMA9"],  price)
    e21 = safe(last["EMA21"], price)
    e50 = safe(last["EMA50"], price)
    e200= safe(last["EMA200"],price)
    if e9 > e21 > e50:   sb += 20; details.append(t(uid,"ind_ema_up"))
    elif e9 < e21 < e50: ss += 20; details.append(t(uid,"ind_ema_down"))
    if price > e200: sb += 10
    else: ss += 10

    bb_l = safe(last["BB_L"], price * 0.98)
    bb_u = safe(last["BB_U"], price * 1.02)
    if price <= bb_l:   sb += 15; details.append(t(uid,"ind_bb_low"))
    elif price >= bb_u: ss += 15; details.append(t(uid,"ind_bb_high"))

    stoch_v = safe(last["Stoch"],   50)
    stoch_s = safe(last["Stoch_S"], 50)
    if stoch_v < 20 and stoch_s < 20:   sb += 10; details.append(t(uid,"ind_stoch_low"))
    elif stoch_v > 80 and stoch_s > 80: ss += 10; details.append(t(uid,"ind_stoch_high"))

    try:
        tk = safe(last["Tenkan"], float("nan"))
        kj = safe(last["Kijun"],  float("nan"))
        sa = safe(last["SpanA"],  float("nan"))
        sb2= safe(last["SpanB"],  float("nan"))
        if not any(pd.isna(x) for x in [tk, kj, sa, sb2]):
            ct = max(sa, sb2); cb = min(sa, sb2)
            if price > ct and tk > kj:   sb += 15; details.append("Ichimoku: فوق السحابة ☁️")
            elif price < cb and tk < kj: ss += 15; details.append("Ichimoku: تحت السحابة ☁️")
            elif ct > cb: sb += 5
            else: ss += 5
    except: pass

    try:
        if bool(last.get("Vol_High", False)):
            if sb > ss: sb += 10
            else: ss += 10
    except: pass

    if sb > ss:
        direction = "BUY"
    elif ss > sb:
        direction = "SELL"
    else:
        direction = "NEUTRAL"
    total = sb + ss
    conf  = round(max(sb, ss) / total * 100) if total > 0 else 50
    strength = frame_strength(direction, conf)
    atr   = safe(last["ATR"], price * 0.01)
    e21_s = safe(last["EMA21"], price * 0.99)
    e50_s = safe(last["EMA50"], price * 0.98)
    e200_s= safe(last["EMA200"],price * 0.97)
    emas = sorted([e21_s, e50_s, e200_s])
    support_levels    = [e for e in emas if e < price]
    resistance_levels = [e for e in emas if e > price]
    s1 = round(support_levels[-1], 2)    if support_levels    else round(price * 0.99, 2)
    r1 = round(resistance_levels[0], 2)  if resistance_levels else round(price * 1.01, 2)

    return {
        "direction": direction, "strength": strength, "conf": conf, "rsi": round(rsi, 1),
        "price": round(price, 2), "atr": round(atr, 2),
        "details": details[:4],
        "support": round(s1, 2), "resistance": round(r1, 2),
        "macd_bull": macd_v > macd_s,
        "ema_bull": e9 > e21 > e50, "ema_bear": e9 < e21 < e50,
        "bb_zone": "low" if price <= bb_l else "high" if price >= bb_u else "mid",
    }


# ==================== Market Regime ====================
def detect_market_regime(df):
    try:
        if df is None or len(df) < 50:
            return "UNKNOWN", 0
        df2   = calc_indicators(df.tail(100).copy())
        last  = df2.iloc[-1]
        price = float(last["Close"])
        atr_pct = safe(last["ATR"], price * 0.01) / price * 100
        e9  = safe(last["EMA9"],  price)
        e21 = safe(last["EMA21"], price)
        e50 = safe(last["EMA50"], price)
        ema_spread = abs(e9 - e50) / price * 100
        bb_u = safe(last["BB_U"], price * 1.02)
        bb_l = safe(last["BB_L"], price * 0.98)
        bb_width = (bb_u - bb_l) / price * 100
        if atr_pct > 3.0:
            return "VOLATILE", min(round(atr_pct * 10), 95)
        elif ema_spread > 1.5 and e9 > e21 > e50:
            return "TRENDING_UP", min(round(ema_spread * 30), 95)
        elif ema_spread > 1.5 and e9 < e21 < e50:
            return "TRENDING_DOWN", min(round(ema_spread * 30), 95)
        else:
            return "RANGING", 50
    except Exception as e:
        logger.warning("Regime: " + str(e))
        return "UNKNOWN", 0


# ==================== Monthly Bias ====================
def get_monthly_bias(df_daily):
    try:
        if df_daily is None or len(df_daily) < 30:
            return "NEUTRAL"
        df_m = df_daily.resample("ME").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna().tail(3)
        if len(df_m) < 2:
            return "NEUTRAL"
        lc = float(df_m["Close"].iloc[-1])
        pc = float(df_m["Close"].iloc[-2])
        tc = float(df_m["Close"].iloc[0]) if len(df_m) >= 3 else pc
        if lc > pc > tc: return "BULL"
        elif lc < pc < tc: return "BEAR"
        return "NEUTRAL"
    except Exception as e:
        return "NEUTRAL"


# ==================== RSI Divergence ====================
def detect_rsi_divergence(df, lookback=20):
    try:
        if len(df) < lookback + 5 or "RSI" not in df.columns:
            return "NONE"
        recent = df.tail(lookback)
        prices = recent["Close"].values
        rsi    = recent["RSI"].values
        if any(pd.isna(rsi)):
            return "NONE"
        if prices[-1] > max(prices[:-5]) and rsi[-1] < max(rsi[:-5]) and rsi[-1] > 55:
            return "BEARISH"
        if prices[-1] < min(prices[:-5]) and rsi[-1] > min(rsi[:-5]) and rsi[-1] < 45:
            return "BULLISH"
        return "NONE"
    except Exception as e:
        return "NONE"


# ==================== Order Blocks ====================
def find_order_blocks(df, lookback=50):
    try:
        if len(df) < lookback:
            return [], []
        recent = df.tail(lookback).copy()
        bull_obs = []; bear_obs = []
        for i in range(2, len(recent) - 2):
            c = recent.iloc[i]; n = recent.iloc[i+1:i+3]
            if c["Close"] < c["Open"] and all(n["Close"] > n["Open"]) and n["Close"].max() > c["Open"] * 1.005:
                bull_obs.append({"high": float(c["Open"]), "low": float(c["Close"])})
            if c["Close"] > c["Open"] and all(n["Close"] < n["Open"]) and n["Close"].min() < c["Open"] * 0.995:
                bear_obs.append({"high": float(c["Close"]), "low": float(c["Open"])})
        return bull_obs[-3:], bear_obs[-3:]
    except Exception as e:
        return [], []


# ==================== Liquidity Zones ====================
def find_liquidity_zones(df, lookback=50):
    try:
        if len(df) < lookback:
            return [], []
        recent = df.tail(lookback)
        highs  = recent["High"].values; lows = recent["Low"].values
        buy_liq = []; sell_liq = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
                buy_liq.append(round(float(highs[i]), 2))
            if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                sell_liq.append(round(float(lows[i]), 2))
        return sorted(buy_liq)[-3:], sorted(sell_liq)[:3]
    except Exception as e:
        return [], []


# 
#  SMART ENTRY — Confluence-based Entry Zone
# 
def find_smart_entry(price: float, direction: str,
                     fib_levels: dict, fib_ext: dict, atr: float,
                     support: float, resistance: float,
                     bull_obs: list, bear_obs: list) -> tuple:
    """
    Confluence-based entry logic:
    - Prioritises the closest technical level away from current market price.
    - Uses Fibonacci levels/extensions as technical levels, then ATR fallback.
    - Never returns market price unless no safe calculation is available elsewhere.
    """
    MIN_DIST = 0.003  # 0.3% minimum distance from current price
    all_fibs = {**fib_levels, **fib_ext}

    if direction == "BUY":
        # All Fib levels meaningfully below price
        candidates = [
            (v, k) for k, v in all_fibs.items()
            if v < price and (price - v) / price >= MIN_DIST
        ]
        if candidates:
            # Pick closest below price
            v, k = max(candidates, key=lambda x: x[0])
            return round(v, 2), f"Technical level {k}%"
        # Fallback: 1.5 ATR below price
        return round(price - 1.5 * atr, 2), "دعم ATR"

    else:  # SELL
        # All Fib levels meaningfully above price
        candidates = [
            (v, k) for k, v in all_fibs.items()
            if v > price and (v - price) / price >= MIN_DIST
        ]
        if candidates:
            # Pick closest above price
            v, k = min(candidates, key=lambda x: x[0])
            return round(v, 2), f"Technical level {k}%"
        # Fallback: 1.5 ATR above price
        return round(price + 1.5 * atr, 2), "مقاومة ATR"


# ==================== Session ====================
def get_current_session():
    hour = datetime.now(timezone.utc).hour
    if 13 <= hour < 16:   return "OVERLAP", 100
    elif 16 <= hour < 21: return "NY", 85
    elif 8 <= hour < 13:  return "LONDON", 85
    else:                 return "ASIAN", 40


# ==================== الأحداث الاقتصادية ====================
def get_economic_events():
    if not FINNHUB_KEY:
        return []
    now_ts = datetime.now(timezone.utc).timestamp()
    if _econ_cache["data"] is not None and (now_ts - _econ_cache["ts"]) < 1800:
        return _econ_cache["data"]
    try:
        from datetime import timedelta
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get("https://finnhub.io/api/v1/calendar/economic",
            params={"from": today, "to": tomorrow, "token": FINNHUB_KEY},
            timeout=10)
        if r.status_code != 200:
            return []
        data = r.json().get("economicCalendar", [])
        keywords = ["CPI", "Fed", "Federal Reserve", "GDP", "NFP", "PPI",
                    "Interest Rate", "Inflation", "Employment", "FOMC"]
        high_events = []
        for ev in data:
            if ev.get("impact", "").upper() == "HIGH" and \
               ev.get("country", "").upper() in ["US", "USD"] and \
               any(kw.lower() in ev.get("event", "").lower() for kw in keywords):
                high_events.append({
                    "event": ev.get("event", ""),
                    "time": ev.get("time", ""),
                    "impact": ev.get("impact", "")
                })
        _econ_cache["data"] = high_events
        _econ_cache["ts"]   = now_ts
        logger.info(f"Economic events: {len(high_events)} high impact events")
        return high_events
    except Exception as e:
        logger.warning("Finnhub economic: " + str(e))
        return []


def get_upcoming_event(hours=2):
    try:
        events = get_economic_events()
        if not events:
            return None
        now_ts = datetime.now(timezone.utc).timestamp()
        for ev in events:
            try:
                ev_time = datetime.fromisoformat(ev["time"].replace("Z", "+00:00"))
                ev_ts   = ev_time.timestamp()
                mins_left = (ev_ts - now_ts) / 60
                if 0 < mins_left <= hours * 60:
                    ev["mins_left"] = int(mins_left)
                    return ev
            except: continue
        return None
    except Exception as e:
        logger.warning("get_upcoming_event: " + str(e))
        return None


# ==================== Full Analysis ====================
def full_analysis(asset="BTC", uid=0, relaxed=False):
    try:
        df_1h = get_data(asset, days=30,  interval="hourly")
        df_4h = get_data(asset, days=60,  interval="4h")
        df_1d = get_data(asset, days=365, interval="daily")
        df_1w = get_data(asset, days=1000, interval="weekly")
    except Exception as e:
        logger.error("Data fetch: " + str(e))
        return None

    if df_1h is None or len(df_1h) < 20:
        logger.warning("Insufficient 1H data for " + asset)
        return None

    session, session_score = get_current_session()

    frames  = {"1h": df_1h, "4h": df_4h, "1d": df_1d}
    results = {}
    for label, df in frames.items():
        if df is not None and len(df) >= 20:
            try:
                results[label] = analyze_frame(df, uid)
            except Exception as e:
                logger.warning("Frame " + label + ": " + str(e))

    if len(results) < 2:
        return None

    final, majority, frames_conf, conf_key, buy_c, sel_c, buy_w, sell_w = weighted_frame_decision(results, relaxed=relaxed)
    conf_txt = t(uid, conf_key)

    if session == "ASIAN" and max(buy_c, sel_c) < 2:
        return None

    # Two-frame: return NEUTRAL with majority so button_handler shows override button
    if final == "NEUTRAL" and majority:
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h)
        nf2, fk2, _ = find_nearest_fib(main2["price"], fib_l2, "NEUTRAL") if fib_l2 else (main2["price"],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x:float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            qualified = r["conf"] >= frame_threshold(k) and r["direction"] != "NEUTRAL"
            status_note = " ✅" if qualified else " ⚪ " + t(uid,"low_conf_note")
            icon = "🟢" if r["direction"]=="BUY" else "🔴" if r["direction"]=="SELL" else "➡️"
            fl2.append(icon+" "+icons2.get(k,"")+": "+r.get("strength", r["direction"])+" ("+str(r["conf"])+"%)"+status_note)
        return {"final":"NEUTRAL","majority":majority,"asset":asset,
                "confluence_txt":conf_txt,"base_conf":frames_conf,
                "price":main2["price"],"tp1":0,"tp2":0,"tp3":0,"sl":0,"rr":0,"atr":main2["atr"],
                "risk_pct":50,"risk_label":"","risk_msg":"",
                "frame_lines":fl2,"rsi":main2["rsi"],"support":main2["support"],"resistance":main2["resistance"],
                "macd_bull":main2["macd_bull"],"ema_bull":main2["ema_bull"],
                "ema_bear":main2["ema_bear"],"bb_zone":main2["bb_zone"],
                "fib_levels":fib_l2,"fib_ext":fib_e2,"key_fibs":kf2,
                "nearest_fib":nf2,"fib_key":fk2,"swing_h":sh2,"swing_l":sl2,
                "weekly_trend":"NEUTRAL","regime":"UNKNOWN","regime_strength":0,"monthly_bias":"NEUTRAL",
                "divergence":"NONE","session":session,"bull_obs":[],"bear_obs":[],"buy_liq":[],"sell_liq":[],
                "entry_low":main2["price"],"entry_high":main2["price"],
                "entry_price":main2["price"],"nearest_fib_val":nf2}

    if final == "NEUTRAL":
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h)
        nf2, fk2, _ = find_nearest_fib(main2["price"], fib_l2, "NEUTRAL") if fib_l2 else (main2["price"],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x:float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            qualified = r["conf"] >= frame_threshold(k) and r["direction"] != "NEUTRAL"
            status_note = " ✅" if qualified else " ⚪ " + t(uid,"low_conf_note")
            icon = "🟢" if r["direction"]=="BUY" else "🔴" if r["direction"]=="SELL" else "➡️"
            fl2.append(icon+" "+icons2.get(k,"")+": "+r.get("strength", r["direction"])+" ("+str(r["conf"])+"%)"+status_note)
        return {"final":"NEUTRAL","asset":asset,"confluence_txt":t(uid,"no_confluence"),"base_conf":0,"majority":majority,
                "price":main2["price"],"tp1":0,"tp2":0,"tp3":0,"sl":0,"rr":0,"atr":main2["atr"],
                "risk_pct":50,"risk_label":t(uid,"risk_med"),"risk_msg":t(uid,"risk_med_msg"),
                "frame_lines":fl2,"rsi":main2["rsi"],"support":main2["support"],"resistance":main2["resistance"],
                "macd_bull":main2["macd_bull"],"ema_bull":main2["ema_bull"],
                "ema_bear":main2["ema_bear"],"bb_zone":main2["bb_zone"],
                "fib_levels":fib_l2,"fib_ext":fib_e2,"key_fibs":kf2,
                "nearest_fib":nf2,"fib_key":fk2,"swing_h":sh2,"swing_l":sl2,
                "weekly_trend":"NEUTRAL","regime":"UNKNOWN","regime_strength":0,"monthly_bias":"NEUTRAL",
                "divergence":"NONE","session":session,"bull_obs":[],"bear_obs":[],"buy_liq":[],"sell_liq":[],
                "entry_low":main2["price"],"entry_high":main2["price"],
                "leverage_ar":"","leverage_en":"","tf_ar":"","tf_en":"","hold_ar":"","hold_en":""}

    main  = results.get("1h") or list(results.values())[0]
    price = main["price"]
    atr   = main["atr"]
    base_conf = max(50, min(round(frames_conf * 0.6 + main["conf"] * 0.4), 89))

    fib_levels, fib_ext, swing_h, swing_l = calculate_fibonacci(df_1h)
    nearest_fib, fib_key, dist_pct = find_nearest_fib(price, fib_levels, final) if fib_levels else (price,"50.0",0)

    # Calculate order blocks BEFORE smart entry
    bull_obs, bear_obs = find_order_blocks(df_1h)
    buy_liq, sell_liq  = find_liquidity_zones(df_1h)

    # Smart entry: Fib + Support/Resistance + Order Blocks confluence
    support    = main.get("support",    price * 0.99)
    resistance = main.get("resistance", price * 1.01)
    entry_price, entry_reason = find_smart_entry(
        price, final, fib_levels, fib_ext, atr,
        support, resistance, bull_obs, bear_obs
    )

    # ── Safety: never allow entry = market price ──
    if abs(entry_price - price) / price * 100 < 0.05:  # within 0.05% = essentially same price
        all_fibs_flat = {**fib_levels, **fib_ext}
        if final == "BUY":
            below = [(v, k) for k, v in all_fibs_flat.items() if v < price * 0.999]
            if below:
                entry_price, entry_reason = min(below, key=lambda x: abs(x[0]-price))[0], ("أقرب مستوى دعم فني" if user_languages.get(uid, "ar") == "ar" else "Nearest technical support")
                entry_price = round(entry_price, 2)
            else:
                entry_price = round(price - 1.5 * atr, 2)
                entry_reason = ("دعم ATR" if user_languages.get(uid, "ar") == "ar" else "ATR support")
        else:  # SELL
            above = [(v, k) for k, v in all_fibs_flat.items() if v > price * 1.001]
            if above:
                entry_price, entry_reason = min(above, key=lambda x: abs(x[0]-price))[0], ("أقرب مستوى مقاومة فني" if user_languages.get(uid, "ar") == "ar" else "Nearest technical resistance")
                entry_price = round(entry_price, 2)
            else:
                entry_price = round(price + 1.5 * atr, 2)
                entry_reason = ("مقاومة ATR" if user_languages.get(uid, "ar") == "ar" else "ATR resistance")

    entry_zone_buffer = max(atr * ENTRY_ZONE_ATR_FACTOR, price * 0.0005)
    entry_low = round(entry_price - entry_zone_buffer, 2)
    entry_high = round(entry_price + entry_zone_buffer, 2)

    sl, tp1, tp2, tp3, rr = get_fib_targets(entry_price, fib_levels, fib_ext, final, atr)

    risk = 100 - base_conf
    if main["rsi"] < 25 or main["rsi"] > 75: risk += 10
    if dist_pct > 2: risk += 5
    risk = min(risk, 99)
    if risk < 30:   rl=t(uid,"risk_low");  rm=t(uid,"risk_low_msg")
    elif risk < 55: rl=t(uid,"risk_med");  rm=t(uid,"risk_med_msg")
    else:           rl=t(uid,"risk_high"); rm=t(uid,"risk_high_msg")

    frame_lines = []
    icons = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
    for k, r in results.items():
        qualified = r["conf"] >= frame_threshold(k) and r["direction"] != "NEUTRAL"
        status_note = " ✅" if qualified else " ⚪ " + t(uid,"low_conf_note")
        icon = "🟢" if r["direction"]=="BUY" else "🔴" if r["direction"]=="SELL" else "➡️"
        frame_lines.append(icon+" "+icons.get(k,"")+": "+r.get("strength", r["direction"])+" ("+str(r["conf"])+"%)"+status_note)

    key_fibs = ["Fib "+pct+"%  $"+"{:,.2f}".format(val) for pct,val in sorted(fib_levels.items(), key=lambda x:float(x[0]))]

    regime, regime_strength = detect_market_regime(df_1h)

    divergence = "NONE"
    try:
        df_div = calc_indicators(df_1h.tail(30).copy())
        divergence = detect_rsi_divergence(df_div)
        if   divergence == "BEARISH" and final == "SELL": base_conf = min(base_conf + 8, 89)
        elif divergence == "BULLISH" and final == "BUY":  base_conf = min(base_conf + 8, 89)
        elif divergence == "BEARISH" and final == "BUY":  base_conf = max(base_conf - 10, 50)
        elif divergence == "BULLISH" and final == "SELL": base_conf = max(base_conf - 10, 50)
    except: pass

    try:
        if final == "SELL" and buy_liq:
            liq_above = [lv for lv in buy_liq if lv > entry_price]
            if liq_above:
                liq_sl = round(min(liq_above) * 1.002, 2)
                sl = round(min(sl, liq_sl), 2) if liq_sl < sl * 1.01 else sl
        elif final == "BUY" and sell_liq:
            liq_below = [lv for lv in sell_liq if lv < entry_price]
            if liq_below:
                liq_sl = round(max(liq_below) * 0.998, 2)
                sl = round(max(sl, liq_sl), 2) if liq_sl > sl * 0.99 else sl
        rr = round(abs(tp2 - entry_price) / abs(sl - entry_price), 2) if abs(sl - entry_price) > 0 else 0
    except: pass

    monthly_bias = get_monthly_bias(df_1d)

    weekly_trend = "NEUTRAL"
    try:
        if df_1w is not None and len(df_1w) >= 20:
            df_w = calc_indicators(df_1w.tail(200).copy())
            lw   = df_w.iloc[-1]
            wp   = float(lw["Close"])
            we20 = safe(lw["EMA21"], wp)
            we50 = safe(lw["EMA50"], wp)
            if wp > we20 and we20 > we50:   weekly_trend = "BULL"
            elif wp < we20 and we20 < we50: weekly_trend = "BEAR"
    except Exception as e:
        logger.warning("Weekly: " + str(e))

    ep = entry_price
    if is_recently_cancelled(asset, final, entry_price, atr):
        # Same direction/zone was cancelled recently; do not re-offer it during cooldown.
        return {"final":"NEUTRAL","asset":asset,"confluence_txt":t(uid,"no_confluence"),"base_conf":0,"majority":None,
                "price":price,"tp1":0,"tp2":0,"tp3":0,"sl":0,"rr":0,"atr":atr,
                "risk_pct":60,"risk_label":t(uid,"risk_med"),"risk_msg":t(uid,"risk_med_msg"),
                "frame_lines":frame_lines,"rsi":main["rsi"],"support":main["support"],"resistance":main["resistance"],
                "macd_bull":main["macd_bull"],"ema_bull":main["ema_bull"],"ema_bear":main["ema_bear"],"bb_zone":main["bb_zone"],
                "fib_levels":fib_levels,"fib_ext":fib_ext,"key_fibs":key_fibs[:5],"nearest_fib":nearest_fib,"fib_key":fib_key,
                "swing_h":swing_h,"swing_l":swing_l,"weekly_trend":weekly_trend,"regime":regime,"regime_strength":regime_strength,
                "monthly_bias":monthly_bias,"divergence":divergence,"session":session,"bull_obs":bull_obs,"bear_obs":bear_obs,
                "buy_liq":buy_liq,"sell_liq":sell_liq,"entry_low":entry_low,"entry_high":entry_high,"entry_price":entry_price}

    if final == "BUY":
        if not (sl < ep < tp1 < tp2 < tp3):
            sl=round(ep-atr,2); tp1=round(ep+atr,2); tp2=round(ep+2*atr,2); tp3=round(ep+2.5*atr,2)
    else:
        if not (tp3 < tp2 < tp1 < ep < sl):
            sl=round(ep+atr,2); tp1=round(ep-atr,2); tp2=round(ep-2*atr,2); tp3=round(ep-2.5*atr,2)

    rr = round(abs(tp2 - ep) / abs(sl - ep), 2) if abs(sl - ep) > 0 else 0
    if rr < 1.0:
        sl = round(ep-1.2*atr,2) if final=="BUY" else round(ep+1.2*atr,2)
        rr = round(abs(tp2-ep)/abs(sl-ep),2) if abs(sl-ep)>0 else 1.0

    risk_warnings = []
    if regime == "VOLATILE":
        risk_warnings.append(t(uid, "risk_warn_volatile"))
    elif regime == "RANGING":
        risk_warnings.append(t(uid, "risk_warn_ranging"))
    if monthly_bias == "BULL" and final == "SELL":
        risk_warnings.append(t(uid, "risk_warn_monthly_bull_sell"))
    elif monthly_bias == "BEAR" and final == "BUY":
        risk_warnings.append(t(uid, "risk_warn_monthly_bear_buy"))
    if weekly_trend == "BULL" and final == "SELL":
        risk_warnings.append(t(uid, "risk_warn_weekly_bull_sell"))
    elif weekly_trend == "BEAR" and final == "BUY":
        risk_warnings.append(t(uid, "risk_warn_weekly_bear_buy"))
    if divergence == "BEARISH" and final == "BUY":
        risk_warnings.append(t(uid, "risk_warn_rsi_against"))
    elif divergence == "BULLISH" and final == "SELL":
        risk_warnings.append(t(uid, "risk_warn_rsi_against"))
    is_counter_trend = (final=="BUY" and weekly_trend=="BEAR") or \
                       (final=="SELL" and weekly_trend=="BULL")
    if is_counter_trend:
        risk_warnings.append(t(uid, "risk_warn_counter_weekly"))
        if final == "BUY":
            tp3 = round(tp2 + abs(tp2-tp1)*0.5, 2)
        else:
            tp3 = round(tp2 - abs(tp1-tp2)*0.5, 2)

    warn_count = len(risk_warnings)
    if warn_count == 0:   overall_risk = t(uid, "risk_low")
    elif warn_count <= 2: overall_risk = t(uid, "risk_med")
    else:                 overall_risk = t(uid, "risk_high")

    result = {
        "final": final, "asset": asset,
        "risk_warnings": risk_warnings, "overall_risk": overall_risk,
        "weekly_trend": weekly_trend, "regime": regime, "regime_strength": regime_strength,
        "monthly_bias": monthly_bias, "divergence": divergence,
        "session": session, "session_score": session_score,
        "bull_obs": bull_obs, "bear_obs": bear_obs,
        "buy_liq": buy_liq, "sell_liq": sell_liq,
        "confluence_txt": conf_txt, "base_conf": base_conf,
        "price": price, "entry_price": entry_price, "entry_low": entry_low, "entry_high": entry_high, "entry_reason": entry_reason, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": atr,
        "risk_pct": risk, "risk_label": rl, "risk_msg": rm,
        "frame_lines": frame_lines, "rsi": main["rsi"],
        "support": main["support"], "resistance": main["resistance"],
        "macd_bull": main["macd_bull"], "ema_bull": main["ema_bull"],
        "ema_bear": main["ema_bear"], "bb_zone": main["bb_zone"],
        "fib_levels": fib_levels, "fib_ext": fib_ext, "key_fibs": key_fibs[:5],
        "nearest_fib": nearest_fib, "fib_key": fib_key,
        "swing_h": swing_h, "swing_l": swing_l,
        "leverage_ar": "",
        "leverage_en": "",
        "tf_ar": "1 ساعة", "tf_en": "1 Hour",
        "hold_ar": "2 — 8 ساعات", "hold_en": "2 — 8 Hours",
    }
    # Calculate once per analysis result and reuse everywhere.
    try:
        saz_decision_intelligence(result, uid, persist=True, refresh=True)
        lev_ar, lev_en = recommended_leverage_by_regime(result)
        result["leverage_ar"] = lev_ar
        result["leverage_en"] = lev_en
    except Exception as e:
        logger.warning("decision metrics attach failed: " + str(e))
    return saz_decision_gate(result, uid)


# ==================== بناء الرسائل ====================
def build_trade_msg(res, uid=0, auto=False):
    ai      = "₿" if res["asset"] == "BTC" else "🥇"
    an      = "BTC/USD"
    is_sell = res["final"] == "SELL"
    dir_emoji = "🔴" if is_sell else "🟢"
    dir_txt   = t(uid,"sell") if is_sell else t(uid,"buy")
    header    = t(uid,"auto_header") if auto else t(uid,"trade_header")
    trade_num = res.get("id","")
    num_str   = " #"+str(trade_num) if trade_num else ""

    entry_display  = res.get("entry_price", res["price"])
    entry_low      = res.get("entry_low", entry_display)
    entry_high     = res.get("entry_high", entry_display)
    entry_reason_d = res.get("entry_reason", "")
    entry_zone_txt = "$"+"{:,.2f}".format(entry_low)+" — $"+"{:,.2f}".format(entry_high)

    confidence = res.get('confidence', res.get('base_conf', None))
    lines = [
        f"🟡 {header}{num_str}",
        f"₿ {an}",
        "",
        f"📊 {t(uid,'direction')}: {dir_emoji} {dir_txt}",
    ]
    if confidence is not None:
        lines.append(f"🔥 {t(uid,'confidence')}: {confidence}%")
    lines += [
        f"💵 {t(uid,'current_price')}: ${res['price']:,.2f}",
        "",
    ]
    lines += safe_saz_intelligence_block(res, uid, compact=True)
    lines += [
        "",
        f"🎯 {t(uid,'entry_zone')}",
        entry_zone_txt,
    ]
    if entry_reason_d and entry_reason_d not in ("سعر السوق", "Market price"):
        lines.append(f"📍 {t(uid,'entry_basis')}: {entry_reason_d}")
    lines += [
        f"📌 {t(uid,'entry')}: ${entry_display:,.2f}",
        "",
        f"🎯 {t(uid,'targets_section')}",
        f"TP1: ${res['tp1']:,.2f}",
        f"TP2: ${res['tp2']:,.2f}",
        f"TP3: ${res['tp3']:,.2f}",
        "",
        f"🛑 {t(uid,'sl')}: ${res['sl']:,.2f}",
        f"⚖️ {t(uid,'rr')}: 1:{res['rr']}",
        "",
        f"🧭 {t(uid,'confluence')}",
    ]

    wt = res.get("weekly_trend","NEUTRAL")
    is_counter = (res["final"]=="BUY" and wt=="BEAR") or (res["final"]=="SELL" and wt=="BULL")
    if is_counter:
        lines.append(t(uid,"counter_trend"))
    lines.append(("📈" if wt=="BULL" else "📉" if wt=="BEAR" else "➡️") + " " + t(uid,"weekly") + ": " + (t(uid,"bullish") if wt=="BULL" else t(uid,"bearish") if wt=="BEAR" else t(uid,"neutral")))

    rg = res.get("regime","UNKNOWN")
    rg_map = {"TRENDING_UP":t(uid,"trend_up"),"TRENDING_DOWN":t(uid,"trend_down"),"RANGING":t(uid,"ranging_market"),"VOLATILE":t(uid,"high_volatility"),"UNKNOWN":""}
    if rg_map.get(rg, rg):
        lines.append(rg_map.get(rg, rg))

    mb = res.get("monthly_bias","NEUTRAL")
    lines.append(("📈" if mb=="BULL" else "📉" if mb=="BEAR" else "➡️") + " " + t(uid,"monthly") + ": " + (t(uid,"bullish") if mb=="BULL" else t(uid,"bearish") if mb=="BEAR" else t(uid,"neutral")))

    div = res.get("divergence","NONE")
    if div == "BEARISH": lines.append(t(uid,"bearish_div"))
    elif div == "BULLISH": lines.append(t(uid,"bullish_div"))

    obs = res.get("bear_obs" if is_sell else "bull_obs", [])
    if obs:
        ob = obs[-1]
        lines.append((t(uid,"strong_sell_zone") if is_sell else t(uid,"strong_buy_zone")) + f": ${ob['low']:,.0f} — ${ob['high']:,.0f}")

    liq = res.get("sell_liq" if is_sell else "buy_liq", [])
    if liq:
        lines.append(f"{t(uid,'liquidity_zone')}: ${liq[0]:,.0f}")

    for fl in res.get("frame_lines", []):
        lines.append(display_frame_line(uid, fl))
    if res.get("confluence_txt"):
        lines.append(res["confluence_txt"])

    overall_risk = res.get("overall_risk", "🟡 Medium")
    risk_warnings = res.get("risk_warnings", [])
    lines += ["", "⚠️ " + t(uid,"risk_check"), f"{t(uid,'risk_level')}: {overall_risk}"]
    for w in risk_warnings:
        lines.append(w)

    lines += [
        "",
        "📡 " + t(uid,"key_levels"),
        f"🟢 {t(uid,'support')}: ${res['support']:,.2f}",
        f"🔴 {t(uid,'resistance')}: ${res['resistance']:,.2f}",
        "",
        f"🕐 {t(uid,'updated_gmt')}: {gmt_now()}",
        t(uid,"footer"),
    ]
    return "\n".join(lines)

def build_update_msg(trade, current_price, update_type, uid=0):
    dir_txt = t(uid,"buy") if trade["direction"] == "BUY" else t(uid,"sell")
    entry_lines = [f"🎯 {t(uid,'entry_zone')}: {format_entry_zone(trade['entry'], trade.get('atr', 0))}"]
    if trade.get("status") == "active" and trade.get("actual_entry"):
        entry_lines.insert(0, f"📍 {t(uid,'actual_entry')}: ${float(trade.get('actual_entry')):,.2f}")
    else:
        entry_lines.append(f"📌 {t(uid,'entry')}: ${trade['entry']:,.2f}")
    lines = [
        f"🟡 {t(uid,'update_header')}",
        "₿ BTC/USD",
        "",
        f"📊 {t(uid,'direction')}: {dir_txt}",
        *entry_lines,
        f"💵 {t(uid,'current_price')}: ${current_price:,.2f}",
        "",
        update_type,
        "",
        f"🎯 {t(uid,'targets_section')}",
        f"TP1: ${trade['tp1']:,.2f}",
        f"TP2: ${trade['tp2']:,.2f}",
        f"TP3: ${trade['tp3']:,.2f}",
        f"🛑 SL: ${trade['sl']:,.2f}",
        "",
        f"🕐 {t(uid,'updated_gmt')}: {gmt_now()}",
        t(uid,"footer"),
    ]
    return "\n".join(lines)

def build_analysis_msg(res, uid=0):
    """Build a cleaner market-read message.

    Notes:
    - Shows only the nearest Fibonacci levels to avoid overwhelming users with old/wide swings.
    - Gives a practical summary when short-term frames conflict with the Daily trend.
    - Does not change trading logic; this is display/UX only.
    """
    lang = user_languages.get(uid, "ar")
    ai = "₿" if res["asset"] == "BTC" else "🥇"
    an = "BTC/USD"

    if res["final"] == "BUY" and res["base_conf"] > 60:
        trend = t(uid,"trend_bull")
        summary = t(uid,"summary_bull")
    elif res["final"] == "SELL" and res["base_conf"] > 60:
        trend = t(uid,"trend_bear")
        summary = t(uid,"summary_bear")
    else:
        trend = t(uid,"trend_neutral")
        summary = _market_read_summary(res, uid)

    rsi      = res["rsi"]
    rsi_txt  = t(uid,"rsi_oversold") if rsi < 30 else t(uid,"rsi_overbought") if rsi > 70 else t(uid,"rsi_neutral")
    macd_txt = t(uid,"macd_bull") if res["macd_bull"] else t(uid,"macd_bear")
    ema_txt  = t(uid,"ema_bull") if res["ema_bull"] else t(uid,"ema_bear") if res["ema_bear"] else t(uid,"ema_mixed")
    bb_txt   = t(uid,"bb_low") if res["bb_zone"]=="low" else t(uid,"bb_high") if res["bb_zone"]=="high" else t(uid,"bb_mid")

    # Show the nearest Fibonacci levels only. The full swing may be wide and visually misleading.
    fib_lines = []
    fib_levels = res.get("fib_levels", {}) or {}
    price = float(res.get("price", 0) or 0)
    if fib_levels and price:
        nearest = sorted(fib_levels.items(), key=lambda x: abs(float(x[1]) - price))[:3]
        nearest = sorted(nearest, key=lambda x: float(x[1]), reverse=True)
        for pct, val in nearest:
            fib_lines.append("  Fib "+str(pct)+"%  $"+"{:,.2f}".format(float(val)))
    else:
        for f in res.get("key_fibs", [])[:3]:
            fib_lines.append("  "+f)

    fib_title = "أقرب مستويات Fibonacci" if lang == "ar" else "Nearest Fibonacci Levels"
    support_label = "أقرب دعم" if lang == "ar" else "Nearest Support"
    resistance_label = "أقرب مقاومة" if lang == "ar" else "Nearest Resistance"

    lines = [
        "",
        "  "+ai+" "+an+"  |  "+t(uid,"analysis_header"),
        "",
        "  "+trend,
        "  💵 "+t(uid,"current_price") + ":  $"+"{:,.2f}".format(res["price"]),
        "  🟢 "+support_label+":      $"+"{:,.2f}".format(res["support"]),
        "  🔴 "+resistance_label+":   $"+"{:,.2f}".format(res["resistance"]),
        "",
    ]
    lines += ["  " + x for x in safe_saz_intelligence_block(res, uid, compact=False)]
    lines += [
        "",
        "  📐 "+fib_title,
    ]
    lines += fib_lines
    lines += ["", "  🔗 "+t(uid,"confluence")]
    for fl in res.get("frame_lines", []):
        lines.append("  "+display_frame_line(uid, fl))
    lines += [
        "",
        "  📊 "+t(uid,"indicators_section"),
        "  RSI ("+str(rsi)+"):  "+rsi_txt,
        "  "+macd_txt,
        "  "+ema_txt,
        "  "+bb_txt,
        "",
    ]
    lines += summary
    lines += [
        "",
        "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
        t(uid,"footer"),
    ]
    return "\n".join(lines)


def _market_read_summary(res, uid=0):
    """Practical market-read summary for neutral/mixed conditions."""
    lang = user_languages.get(uid, "ar")
    frame_lines = res.get("frame_lines", []) or []

    def _dir_from_line(line):
        if "BUY" in line:
            return "BUY"
        if "SELL" in line:
            return "SELL"
        return "NEUTRAL"

    def _find_line(*tokens):
        for line in frame_lines:
            if any(tok in line for tok in tokens):
                return line
        return ""

    h1 = _dir_from_line(_find_line("ساعة", "1H"))
    h4 = _dir_from_line(_find_line("4 ساعات", "4H"))
    d1 = _dir_from_line(_find_line("يومي", "Daily", "1D"))

    if h1 == h4 and h1 in ("BUY", "SELL") and d1 in ("BUY", "SELL") and d1 != h1:
        if lang == "ar":
            short_txt = "إيجابي" if h1 == "BUY" else "سلبي"
            return [
                "  🧭 الخلاصة",
                "",
                f"  الاتجاه قصير المدى {short_txt}،",
                "  لكن الاتجاه اليومي ما زال غير داعم بشكل كامل.",
                "",
                "  ⏳ يفضل انتظار توافق أقوى قبل الدخول.",
            ]
        else:
            short_txt = "positive" if h1 == "BUY" else "negative"
            return [
                "  🧭 Summary",
                "",
                f"  Short-term momentum is {short_txt},",
                "  but the Daily trend is not fully supportive yet.",
                "",
                "  ⏳ Waiting for stronger alignment is preferred.",
            ]

    if lang == "ar":
        return [
            "  🧭 الخلاصة",
            "",
            "  السوق في منطقة تردد حالياً.",
            "  ⏳ يفضل انتظار إشارة أوضح قبل الدخول.",
        ]
    return [
        "  🧭 Summary",
        "",
        "  The market is currently indecisive.",
        "  ⏳ Waiting for a clearer setup is preferred.",
    ]


# ==================== لوحات المفاتيح ====================
def main_keyboard(uid):
    rows = [
        [InlineKeyboardButton(t(uid,"btn_btc"),          callback_data="trade_BTC")],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"), callback_data="analysis_BTC")],
        [InlineKeyboardButton(t(uid,"btn_prices"),  callback_data="prices"),
         InlineKeyboardButton(t(uid,"btn_trades"),  callback_data="open_trades")],
    ]
    if active_trades:
        rows.append([InlineKeyboardButton(t(uid,"btn_close_trade"), callback_data="close_trade_menu")])
    rows += [
        [InlineKeyboardButton(t(uid,"btn_stats"),   callback_data="stats"),
         InlineKeyboardButton(t(uid,"btn_about"),   callback_data="about")],
        [InlineKeyboardButton(t(uid,"btn_lang"),    callback_data="change_lang")],
    ]
    return InlineKeyboardMarkup(rows)

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data="lang_ar"),
        InlineKeyboardButton("English", callback_data="lang_en"),
    ]])

def confirm_keyboard(uid=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_replace_yes"), callback_data="confirm_replace_yes")],
        [InlineKeyboardButton(t(uid,"btn_add_new"), callback_data="confirm_add_new")],
        [InlineKeyboardButton(t(uid,"btn_keep_old"), callback_data="confirm_replace_no")],
    ])


# ==================== هاندلرز ====================

async def why_command(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return
    try:
        res = await run_blocking(full_analysis, "BTC", uid)
        if not res:
            await update.message.reply_text(t(uid, "failed"))
            return
        m = res.get("decision_metrics") or saz_decision_intelligence(res, uid)
        lang = user_languages.get(uid, "ar")
        grade = m.get("setup_grade") or saz_setup_grade(m)
        lines = []
        if lang == "ar":
            lines += [
                "🧠 لماذا هذا القرار؟",
                "",
                f"🏷️ التصنيف: {saz_grade_label(grade, uid)}",
                f"📊 جودة السوق: {int(m.get('quality', 0))}/100",
                f"⚠️ مستوى المخاطرة: {saz_grade_risk_label(grade, uid)}",
                f"🧭 الحالة: {m.get('regime_text', 'غير واضحة')}",
                f"🎯 القرار: {m.get('decision_text', '')}",
                "",
                "أهم العوامل:",
            ]
            if m.get("event_risk_label"):
                lines.append(f"• حدث اقتصادي قريب: {m.get('event_risk_label')}")
            if res.get("frame_lines"):
                for fl in res.get("frame_lines", [])[:3]:
                    lines.append("• " + display_frame_line(uid, fl))
            if grade == "REJECT":
                lines.append("• الجودة أو المخاطرة لا تسمح بفتح صفقة حالياً.")
            elif grade == "C":
                lines.append("• الفرصة مضاربية وتحتاج التزاماً صارماً بمنطقة الدخول.")
            else:
                lines.append("• الفرصة مقبولة بشرط الالتزام بإدارة المخاطر.")
        else:
            lines += [
                "🧠 Why this decision?",
                "",
                f"🏷️ Grade: {saz_grade_label(grade, uid)}",
                f"📊 Market Quality: {int(m.get('quality', 0))}/100",
                f"⚠️ Risk Level: {saz_grade_risk_label(grade, uid)}",
                f"🧭 State: {m.get('regime_text', 'Unclear')}",
                f"🎯 Decision: {m.get('decision_text', '')}",
                "",
                "Key factors:",
            ]
            if m.get("event_risk_label"):
                lines.append(f"• Upcoming event risk: {m.get('event_risk_label')}")
            if res.get("frame_lines"):
                for fl in res.get("frame_lines", [])[:3]:
                    lines.append("• " + display_frame_line(uid, fl))
            if grade == "REJECT":
                lines.append("• Quality or risk does not justify opening a trade now.")
            elif grade == "C":
                lines.append("• This is an aggressive setup and requires strict entry discipline.")
            else:
                lines.append("• The setup is acceptable if risk management is respected.")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error("why_command: " + str(e))
        await update.message.reply_text(t(uid, "failed"))


async def edge_command(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return
    await update.message.reply_text(format_grade_edge_report(uid))


async def version_command(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return
    lang = user_languages.get(uid, "ar")
    if lang == "ar":
        msg = (
            f"🧩 SazBot System\n\n"
            f"Build ID: {BUILD_ID}\n"
            f"DNA Gate: Enabled\n"
            f"Early Bias: Enabled\n"
            f"Override Guard: Enabled\n"
            f"Decision Metrics: Consistent"
        )
    else:
        msg = (
            f"🧩 SazBot System\n\n"
            f"Build ID: {BUILD_ID}\n"
            f"DNA Gate: Enabled\n"
            f"Early Bias: Enabled\n"
            f"Override Guard: Enabled\n"
            f"Decision Metrics: Consistent"
        )
    await update.message.reply_text(msg)


async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        await update.message.reply_text(t(uid,"private_bot")); return
    if uid not in user_languages:
        await update.message.reply_text(t(uid,"choose_language_intro"), reply_markup=lang_keyboard())
    else:
        await update.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text or ""
    if uid not in ALLOWED_USERS: return
    kb   = main_keyboard(uid) if uid in user_languages else lang_keyboard()
    lang = user_languages.get(uid, "ar")
    if any(g in text.lower() for g in GREETINGS):
        reply = random.choice(REPLIES_AR if lang == "ar" else REPLIES_EN)
    else:
        reply = random.choice(CONFUSED_AR if lang == "ar" else CONFUSED_EN)
    await update.message.reply_text(reply, reply_markup=kb)


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    global trade_counter
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    await query.answer()
    if uid not in ALLOWED_USERS: return

    if data == "lang_ar":
        user_languages[uid] = "ar"
        save_languages()
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == "lang_en":
        user_languages[uid] = "en"
        save_languages()
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == "change_lang":
        await query.message.reply_text(t(uid,"choose_lang"), reply_markup=lang_keyboard())

    elif data.startswith("trade_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            current_price_check = await run_blocking(get_btc_price)
            if current_price_check:
                early_similar = next((
                    tr for tr in active_trades
                    if tr["asset"] == asset and
                    abs(tr["entry"] - current_price_check) < 0.5 * tr.get("atr", current_price_check * 0.015)
                ), None)
                if early_similar:
                    await query.message.reply_text(
                        t(uid,"duplicate_setup")+"\n"
                        +t(uid,"existing_entry_zone")+": "+format_entry_zone(early_similar["entry"], early_similar.get("atr", 0))+"\n"
                        +t(uid,"no_new_trade_needed"))
                    return

            keys_to_clear = [k for k in _cache if k.startswith(asset)]
            for k in keys_to_clear:
                _cache.pop(k, None)
            res = await run_blocking(full_analysis, asset, uid)
            if not res:
                await query.message.reply_text(t(uid,"failed")); return
            if isinstance(res, dict) and res.get("blocked_by_saz_dna"):
                await query.message.reply_text(saz_dna_rejection_message(res, uid))
                return
            if res["final"] == "NEUTRAL":
                fls = res.get("frame_lines", [])
                lang = user_languages.get(uid, "ar")
                buy_f, sell_f = count_qualified_frame_lines(fls)
                q_count = max(buy_f, sell_f)
                is_two_frame = q_count == 2

                # Majority is only actionable for the 2/3 partial-alignment case.
                majority = res.get("majority")
                if not majority:
                    majority = "BUY" if buy_f > sell_f else "SELL" if sell_f > buy_f else None

                def _line_dir(line):
                    if "BUY" in line:
                        return "BUY"
                    if "SELL" in line:
                        return "SELL"
                    return "NEUTRAL"

                def _find_frame(*tokens):
                    for line in fls:
                        if any(tok in line for tok in tokens):
                            return line
                    return ""

                h1_dir = _line_dir(_find_frame("ساعة", "1H"))
                h4_dir = _line_dir(_find_frame("4 ساعات", "4H"))
                d1_dir = _line_dir(_find_frame("يومي", "Daily", "1D"))
                short_bias = h1_dir if h1_dir == h4_dir and h1_dir in ("BUY", "SELL") else majority
                daily_against_short = short_bias in ("BUY", "SELL") and d1_dir in ("BUY", "SELL") and d1_dir != short_bias

                if is_two_frame and majority:
                    parts = [
                        t(uid,"partial_title"),
                        "",
                        t(uid,"partial_body"),
                        "",
                    ]
                else:
                    if lang == "ar":
                        parts = [
                            "⏳ لا توجد فرصة عالية الجودة حالياً",
                            "",
                        ]
                    else:
                        parts = [
                            "⏳ No High-Quality Setup Yet",
                            "",
                        ]

                # Always show SazBot 2.1 decision layer in no-setup / partial setup states.
                parts.append("")
                parts += safe_saz_intelligence_block(res, uid, compact=False)
                parts.append("")

                if fls:
                    parts.append("📊 " + ("حالة السوق" if lang == "ar" else "Market State"))
                    parts.append("")
                    for fl in fls:
                        parts.append(display_frame_line(uid, fl))
                    parts.append("")

                show_override = is_two_frame and majority and can_show_override_option(res, uid)

                if show_override:
                    parts.append("🎯 " + ("يوجد سيناريو بديل متاح، لكنه يحمل مستوى مخاطرة أعلى." if lang == "ar" else "An alternative setup is available, but it carries higher risk."))
                    kb_override = InlineKeyboardMarkup([[
                        InlineKeyboardButton(t(uid,"btn_higher_risk"), callback_data=f"override_trade_{asset}"),
                        InlineKeyboardButton(t(uid,"btn_cancel"), callback_data="override_cancel"),
                    ]])
                    pending_trade_replace[uid] = {"override_res": res}
                    await query.message.reply_text("\n".join(parts), reply_markup=kb_override)
                else:
                    if daily_against_short:
                        parts.append("🧭 " + ("الاتجاه اليومي ما زال يعاكس الاتجاه قصير المدى." if lang == "ar" else "The Daily trend is still against the short-term direction."))
                        parts.append("")
                    parts.append("⏳ " + ("يفضل انتظار توافق أقوى قبل الدخول." if lang == "ar" else "Waiting for stronger market alignment before entering."))
                    if is_two_frame and majority:
                        parts.append("")
                        parts.append("🚫 " + ("لا توجد فرصة بديلة مناسبة الآن؛ السعر أو المخاطرة لم تعد ضمن نطاق مقبول." if lang == "ar" else "No suitable alternative setup now; price or risk is no longer within an acceptable range."))
                    pending_trade_replace.pop(uid, None)
                    await query.message.reply_text("\n".join(parts))
                return
            entry_p = res.get("entry_price", res["price"])
            market_p = res["price"]

            avg_atr = res.get("atr", entry_p * 0.015)
            similar_recent = next((
                tr for tr in active_trades
                if tr["asset"] == res["asset"] and
                tr["direction"] == res["final"] and
                abs(tr["entry"] - entry_p) < 0.5 * avg_atr
            ), None)

            if similar_recent:
                await query.message.reply_text(
                    t(uid,"duplicate_setup")+"\n"
                    +t(uid,"previous_entry_zone")+": "+format_entry_zone(similar_recent["entry"], similar_recent.get("atr", 0))+"\n"
                    +t(uid,"no_new_trade_needed"))
                return

            trade_counter += 1
            res["id"] = trade_counter
            await query.message.reply_text(build_trade_msg(res, uid))

            dist_to_entry = abs(entry_p - market_p) / market_p * 100
            is_pending = dist_to_entry > 0.1
            frame_snapshot = {
                "buy": count_qualified_frame_lines(res.get("frame_lines", []))[0],
                "sell": count_qualified_frame_lines(res.get("frame_lines", []))[1],
            }
            new_trade = {
                "id": trade_counter, "asset": res["asset"],
                "direction": res["final"], "entry": entry_p,
                "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"], "tp3": res["tp3"],
                "atr": res["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res["sl"], "entry_ref": entry_p,
                "status": "pending" if is_pending else "active",
                "actual_entry": market_p if not is_pending else None,
                "chat_id": query.message.chat_id, "open_time": gmt_now(),
                "frame_snapshot": frame_snapshot,
            }
            already_open = next((tr for tr in active_trades
                if tr["asset"] == new_trade["asset"] and tr["direction"] == new_trade["direction"]), None)
            opposite_open = next((tr for tr in active_trades
                if tr["asset"] == new_trade["asset"] and tr["direction"] != new_trade["direction"]), None)

            if already_open:
                ai_sym  = "₿ BTC" if new_trade["asset"] == "BTC" else "🥇 GOLD"
                pending_trade_replace[uid] = {"new": new_trade, "old": already_open, "res": res}
                if user_languages.get(uid, "ar") == "ar":
                    dir_txt_exists = "شراء BUY" if new_trade["direction"] == "BUY" else "بيع SELL"
                    msg_exists = "⚠️ SazBot | توجد صفقة نشطة\n\n" + ai_sym + " — " + dir_txt_exists + "\n\nهل تريد إغلاق الصفقة الحالية وفتح السيناريو الجديد؟"
                else:
                    dir_txt_exists = "BUY ⬆️" if new_trade["direction"] == "BUY" else "SELL ⬇️"
                    msg_exists = "⚠️ SazBot | Active Trade Exists\n\n" + ai_sym + " — " + dir_txt_exists + "\n\nClose the existing trade and open the new setup?"
                await query.message.reply_text(msg_exists, reply_markup=confirm_keyboard(uid))
            elif opposite_open:
                old_dir  = "شراء BUY ⬆️" if opposite_open["direction"] == "BUY" else "بيع SELL ⬇️"
                new_dir  = "بيع SELL ⬇️" if new_trade["direction"] == "SELL" else "شراء BUY ⬆️"
                ai_sym   = "₿ BTC" if new_trade["asset"] == "BTC" else "🥇 GOLD"
                pending_trade_replace[uid] = {"new": new_trade, "old": opposite_open, "res": res}
                await query.message.reply_text(
                    t(uid,"opposite_title")+"\n\n"+ai_sym+"\n"+t(uid,"current_trade_word")+": "+old_dir+"\n"+t(uid,"new_trade_word")+": "+new_dir,
                    reply_markup=confirm_keyboard(uid))
            else:
                # ✅ FIX 1: lock عند التعديل على active_trades
                async with get_trades_lock():
                    active_trades.append(new_trade)
                    if res["asset"] == "BTC":
                        active_btc_trade["data"] = new_trade
                    save_trades()
                    save_runtime_state()
        except Exception as e:
            logger.error("Trade handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "confirm_replace_yes":
        pending = pending_trade_replace.pop(uid, None)
        if pending:
            old_tr = pending["old"]
            res_old = pending["res"]
            new_tr  = pending["new"]
            async with get_trades_lock():
                if old_tr in active_trades:
                    active_trades.remove(old_tr)
                active_trades.append(new_tr)
                if new_tr["asset"] == "BTC":
                    active_btc_trade["data"] = new_tr
                save_trades()
                save_runtime_state()
            await query.message.reply_text(build_trade_msg(res_old, uid))
        else:
            await query.message.reply_text(t(uid,"request_expired"))

    elif data == "confirm_add_new":
        pending = pending_trade_replace.pop(uid, None)
        if pending:
            new_tr  = pending["new"]
            res_stored = pending["res"]
            async with get_trades_lock():
                active_trades.append(new_tr)
                if new_tr["asset"] == "BTC":
                    active_btc_trade["data"] = new_tr
                save_trades()
                save_runtime_state()
            await query.message.reply_text(build_trade_msg(res_stored, uid))
        else:
            await query.message.reply_text(t(uid,"request_expired"))

    elif data == "confirm_replace_no":
        pending_trade_replace.pop(uid, None)
        await query.message.reply_text(t(uid,"existing_trade_kept"))

    elif data.startswith("analysis_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            keys_to_clear = [k for k in _cache if k.startswith(asset)]
            for k in keys_to_clear:
                _cache.pop(k, None)
            res = await run_blocking(full_analysis, asset, uid)
            if not res:
                await query.message.reply_text(t(uid,"market_filters_blocked")); return
            await query.message.reply_text(build_analysis_msg(res, uid))
        except Exception as e:
            logger.error("Analysis handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "prices":
        try:
            d = await run_blocking(get_prices)
            if not d:
                await query.message.reply_text(t(uid,"failed")); return
            btc = d.get("bitcoin", {})
            bp  = float(btc.get("usd", 0) or 0)
            bc  = float(btc.get("usd_24h_change", 0) or 0)
            if bp <= 0:
                await query.message.reply_text(t(uid,"failed")); return
            lines = [
                "",
                "  "+t(uid,"prices_title"),
                "",
                "",
                "  ₿ BTC/USD:   $"+"{:,.0f}".format(bp),
                "  "+("📈" if bc > 0 else "📉")+" "+t(uid,"change_24h")+":  "+"{:+.2f}".format(bc)+"%",
                "",
                "",
                "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
            ]
            await query.message.reply_text("\n".join(lines))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "open_trades":
        if not active_trades:
            await query.message.reply_text(t(uid,"no_open_trades"))
        else:
            current_price = await run_blocking(get_btc_price)
            for tr in active_trades:
                tid     = tr.get("id","?")
                de      = "🔴 SELL" if tr["direction"]=="SELL" else "🟢 BUY"
                ai2     = "₿" if tr["asset"]=="BTC" else "🥇"
                tp1_hit = "✅" if tr.get("tp1_hit") else "⏳"
                tp2_hit = "✅" if tr.get("tp2_hit") else "⏳"
                st      = "⏳ " + t(uid,"status_pending") if tr.get("status")=="pending" else "🟢 " + t(uid,"status_active")
                rows = [
                    f"🟡 SazBot | {t(uid,'active_trade')} #{tid}",
                    st,
                    "",
                    f"📊 {t(uid,'direction')}: {de}",
                ]
                if tr.get("status") == "active" and tr.get("actual_entry"):
                    rows.append(f"📍 {t(uid,'actual_entry')}: ${float(tr.get('actual_entry')):,.2f}")
                    rows.append(f"🎯 {t(uid,'entry_reference_zone')}: "+format_entry_zone(tr["entry"], tr.get("atr", 0)))
                else:
                    rows.append(f"🎯 {t(uid,'entry_zone')}: "+format_entry_zone(tr["entry"], tr.get("atr", 0)))
                if current_price and tr["asset"] == "BTC":
                    rows.append("💵 "+t(uid,"current_price")+": $"+"{:,.2f}".format(current_price))
                rows += [
                    "",
                    f"🎯 {t(uid,'targets')}",
                    tp1_hit+" TP1: $"+"{:,.2f}".format(tr["tp1"]),
                    tp2_hit+" TP2: $"+"{:,.2f}".format(tr["tp2"]),
                    "⏳ TP3: $"+"{:,.2f}".format(tr["tp3"]),
                    "🛑 SL: $"+"{:,.2f}".format(tr["sl"]),
                    "",
                    "🕐 "+t(uid,"opened")+": "+tr.get("open_time",""),
                ]
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(t(uid,"btn_close_trade"), callback_data=f"close_active_{tid}")
                ]])
                await query.message.reply_text("\n".join(rows), reply_markup=kb)

    elif data == "stats":
        stats    = load_stats()
        wins     = stats.get("wins", 0)
        losses   = stats.get("losses", 0)
        total_rr = stats.get("total_rr", 0.0)
        total_closed = stats.get("total", 0)
        win_rate = round(wins / total_closed * 100) if total_closed > 0 else 0
        avg_rr   = round(total_rr / wins, 2) if wins > 0 else 0
        bar_w    = "█" * (win_rate // 10) + "░" * (10 - win_rate // 10)
        lines = [
            f"📊 {t(uid,'stats_title')}",
            "",
            f"📈 {t(uid,'closed_trades')}",
            f"{t(uid,'total')}: {total_closed}",
            f"🏆 {t(uid,'wins')}: {wins}",
            f"🟡 {t(uid,'breakeven_stat')}: {stats.get('breakeven', 0)}",
            f"🛑 {t(uid,'losses')}: {losses}",
            "",
            f"🎯 {t(uid,'win_rate')}: {win_rate}%",
            bar_w,
            f"⚖️ {t(uid,'avg_rr')}: 1:{avg_rr}",
        ]
        if active_trades:
            lines += ["", f"📋 {t(uid,'existing_trades')}"]
            for tr in active_trades:
                ai2  = "₿" if tr.get("asset") == "BTC" else "🥇"
                dire = "🔴 SELL" if tr.get("direction") == "SELL" else "🟢 BUY"
                if tr.get("status") == "pending":
                    status = "⏳ " + t(uid,"waiting_entry") + ": " + format_entry_zone(tr["entry"], tr.get("atr", 0))
                elif tr.get("tp2_hit"):
                    status = "✅✅ " + t(uid,"tp2_done")
                elif tr.get("tp1_hit"):
                    status = "✅ " + t(uid,"tp1_done")
                else:
                    status = "🟢 " + t(uid,"active_no_target")
                lines += [
                    "",
                    f"{ai2} #{tr.get('id','?')} | {dire}",
                    f"🎯 {t(uid,'entry_zone')}: {format_entry_zone(tr['entry'], tr.get('atr', 0))}",
                    status,
                    f"TP1: ${tr['tp1']:,.2f} | TP2: ${tr['tp2']:,.2f}",
                    f"TP3: ${tr['tp3']:,.2f} | SL: ${tr['sl']:,.2f}",
                ]
        else:
            lines += ["", "📭 " + t(uid,"no_existing_trades")]
        lines += ["", "🕐 " + t(uid,"updated_gmt") + ": " + gmt_now()]
        await query.message.reply_text("\n".join(lines))

    elif data.startswith("keep_pending_"):
        trade_id = int(data.split("_")[2])
        pending_trade_replace.pop(trade_id, None)
        await query.message.reply_text(t(uid,"setup_kept") + " #"+str(trade_id))

    elif data.startswith("cancel_pending_"):
        trade_id = int(data.split("_")[2])
        pending_trade_replace.pop(trade_id, None)
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            async with get_trades_lock():
                active_trades.remove(trade)
                remember_cancelled_setup(trade, reason="manual_cancel")
                save_trades()
                save_runtime_state()
        await query.message.reply_text(t(uid,"setup_cancelled") + " #"+str(trade_id))

    elif data.startswith("activate_signal_"):
        sig_id = int(data.split("_")[2])
        sig = pending_signals.pop(sig_id, None)
        if sig:
            res_sig   = sig["res"]
            entry_p   = sig["entry_p"]
            chat_ids_s = sig.get("chat_ids", [uid])
            chat_id_s  = chat_ids_s[0] if chat_ids_s else uid
            dist_to_entry = abs(entry_p - res_sig["price"]) / res_sig["price"] * 100
            is_pending = dist_to_entry > 0.1
            sig_frame_snapshot = {
                "buy": count_qualified_frame_lines(res_sig.get("frame_lines", []))[0],
                "sell": count_qualified_frame_lines(res_sig.get("frame_lines", []))[1],
            }
            new_trade = {
                "id": sig_id, "asset": "BTC",
                "direction": res_sig["final"], "entry": entry_p,
                "sl": res_sig["sl"], "tp1": res_sig["tp1"],
                "tp2": res_sig["tp2"], "tp3": res_sig["tp3"],
                "atr": res_sig["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res_sig["sl"], "entry_ref": entry_p,
                "status": "pending" if is_pending else "active",
                "actual_entry": res_sig.get("price") if not is_pending else None,
                "chat_id": chat_id_s, "open_time": gmt_now(),
                "frame_snapshot": sig_frame_snapshot,
                "entry_update_sent": False,
            }
            async with get_trades_lock():
                active_trades.append(new_trade)
                if res_sig["asset"] == "BTC":
                    active_btc_trade["data"] = new_trade
                save_trades()
                save_runtime_state()
            status_txt = "⏳ " + t(uid,"pending") + " — " + t(uid,"entry_zone") + " " + format_entry_zone(entry_p, res_sig.get("atr", 0)) if is_pending else "🟢 " + t(uid,"active")
            confirm_msg = "✅ SazBot | " + t(uid,"setup_activated") + " #"+str(sig_id)+"\n"+status_txt
            for cid in chat_ids_s:
                try:
                    await context.bot.send_message(chat_id=cid, text=confirm_msg)
                except: pass
        else:
            await query.message.reply_text(t(uid,"signal_expired"))

    elif data.startswith("ignore_signal_"):
        sig_id = int(data.split("_")[2])
        pending_signals.pop(sig_id, None)

    elif data.startswith("update_entry_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade and "pending_update" in trade:
            upd = trade["pending_update"]
            old_entry = trade["entry"]
            async with get_trades_lock():
                trade["entry"]  = upd["entry"]
                trade["sl"]     = upd["sl"]
                trade["tp1"]    = upd["tp1"]
                trade["tp2"]    = upd["tp2"]
                trade["tp3"]    = upd["tp3"]
                trade["orig_sl"]= upd["sl"]
                trade.pop("pending_update", None)
                trade["entry_update_sent"] = False
                save_trades()
                save_runtime_state()
            await query.message.reply_text(
                t(uid,"entry_zone_updated")+" #"+str(trade_id)+"\n\n"
                + t(uid,"old_reference") + ": $"+"{:,.2f}".format(old_entry)+"\n"
                + t(uid,"new_reference") + ": $"+"{:,.2f}".format(upd["entry"]))
        else:
            await query.message.reply_text(t(uid,"update_expired"))

    elif data.startswith("ignore_entry_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            trade.pop("pending_update", None)
            trade["entry_update_sent"] = False

    elif data.startswith("keep_active_"):
        pass  # صمت — المستخدم قرر يبقيها

    elif data == "close_trade_menu":
        if not active_trades:
            await query.message.reply_text(t(uid,"no_open_trades"))
        else:
            buttons = []
            for tr in active_trades:
                tid = tr.get("id", "?")
                direction = tr.get("direction", "?")
                asset = tr.get("asset", "BTC")
                label = f"❌ #{tid} {asset} {direction}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"close_active_{tid}")])
            await query.message.reply_text(t(uid,"close_trade_title"), reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("close_active_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            async with get_trades_lock():
                active_trades.remove(trade)
                save_trades()
                save_runtime_state()
            await query.message.reply_text(t(uid,"trade_closed")+" #"+str(trade_id))

    elif data in ("override_cancel", "cancel_request", "noop_cancel"):
        pending_trade_replace.pop(uid, None)
        # Remove inline buttons from the old message so the user sees the action was handled.
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.warning("silent action failed: " + str(e))
        await query.message.reply_text(t(uid,"cancelled_waiting"))
        return

    elif data.startswith("override_trade_"):
        # Format: override_trade_{asset}
        asset_ov = data.replace("override_trade_", "", 1)
        stored   = pending_trade_replace.pop(uid, {})
        res_ov   = stored.get("override_res")

        if not res_ov:
            await query.message.reply_text(t(uid,"request_expired"))
            return

        await query.message.reply_text(t(uid,"preparing_available"))
        try:
            keys_to_clear = [k for k in _cache if k.startswith(asset_ov)]
            for k in keys_to_clear: _cache.pop(k, None)

            # Use relaxed=True so 2-frame gives real SL/TP instead of NEUTRAL
            res_fresh = await run_blocking(full_analysis, asset_ov, uid, relaxed=True)
            res_use   = res_fresh if res_fresh and res_fresh.get("final") != "NEUTRAL" else None

            # Fallback only when there is a real 2-frame majority. Never force a setup from a tie or 1/3.
            if not res_use:
                res_use = res_ov
                fls     = res_use.get("frame_lines", [])
                buy_f, sell_f = count_qualified_frame_lines(fls)
                if buy_f >= OVERRIDE_MIN_QUALIFIED_FRAMES and buy_f > sell_f:
                    res_use["final"] = "BUY"
                    res_use["base_conf"] = max(res_use.get("base_conf", 0), 65)
                    res_use["confidence"] = max(res_use.get("confidence", 0), 65)
                    res_use["confluence_txt"] = t(uid,"partial_confluence")
                elif sell_f >= OVERRIDE_MIN_QUALIFIED_FRAMES and sell_f > buy_f:
                    res_use["final"] = "SELL"
                    res_use["base_conf"] = max(res_use.get("base_conf", 0), 65)
                    res_use["confidence"] = max(res_use.get("confidence", 0), 65)
                    res_use["confluence_txt"] = t(uid,"partial_confluence")
                else:
                    await query.message.reply_text(t(uid,"override_blocked_frames") + "\n\n" + t(uid,"no_trade_better"))
                    return

            best_dir = res_use["final"]
            fl_check = res_use.get("frame_lines", [])
            buy_check, sell_check = count_qualified_frame_lines(fl_check)
            support_check = buy_check if best_dir == "BUY" else sell_check
            oppose_check  = sell_check if best_dir == "BUY" else buy_check
            if support_check < OVERRIDE_MIN_QUALIFIED_FRAMES or oppose_check >= support_check:
                await query.message.reply_text(t(uid,"override_blocked_frames") + "\n\n" + t(uid,"no_trade_better"))
                return

            # Always use CURRENT price — never the cached/old price
            cur_price = await run_blocking(get_btc_price)
            live_price = cur_price if cur_price else res_use.get("price", 0)
            avg_atr  = res_use.get("atr", live_price * 0.015)

            # Recalculate entry using find_smart_entry with current price
            fib_l = res_use.get("fib_levels", {})
            fib_e = res_use.get("fib_ext", {})
            if fib_l:
                entry_p, entry_rsn = find_smart_entry(
                    live_price, best_dir, fib_l, fib_e, avg_atr,
                    res_use.get("support", live_price*0.99),
                    res_use.get("resistance", live_price*1.01),
                    res_use.get("bull_obs", []), res_use.get("bear_obs", [])
                )
                res_use["entry_price"] = entry_p
                res_use["entry_reason"] = entry_rsn
                res_use["entry_low"], res_use["entry_high"] = entry_zone_from_trade(entry_p, avg_atr)
            else:
                entry_p = live_price
                res_use["entry_low"], res_use["entry_high"] = entry_zone_from_trade(entry_p, avg_atr)
            # Reject higher-risk overrides when price has already moved too far beyond the proposed entry zone.
            ez_low = res_use.get("entry_low", entry_p)
            ez_high = res_use.get("entry_high", entry_p)
            too_far_buy = best_dir == "BUY" and live_price > ez_high * (1 + OVERRIDE_MAX_DISTANCE_FROM_ZONE_PCT/100)
            too_far_sell = best_dir == "SELL" and live_price < ez_low * (1 - OVERRIDE_MAX_DISTANCE_FROM_ZONE_PCT/100)
            if too_far_buy or too_far_sell:
                await query.message.reply_text(t(uid,"override_blocked_distance") + "\n\n" + t(uid,"no_trade_better"))
                return

            res_use["price"] = live_price

            # Safety: if SL/TP still zero, calculate from ATR
            if not res_use.get("sl") or res_use.get("sl", 0) == 0:
                atr = avg_atr
                if best_dir == "BUY":
                    res_use["sl"]  = round(entry_p - 1.5 * atr, 2)
                    res_use["tp1"] = round(entry_p + 1.5 * atr, 2)
                    res_use["tp2"] = round(entry_p + 3.0 * atr, 2)
                    res_use["tp3"] = round(entry_p + 4.5 * atr, 2)
                else:
                    res_use["sl"]  = round(entry_p + 1.5 * atr, 2)
                    res_use["tp1"] = round(entry_p - 1.5 * atr, 2)
                    res_use["tp2"] = round(entry_p - 3.0 * atr, 2)
                    res_use["tp3"] = round(entry_p - 4.5 * atr, 2)
                res_use["rr"]      = 1.0
                res_use["orig_sl"] = res_use["sl"]

            similar = next((tr for tr in active_trades
                            if tr["asset"] == asset_ov and tr["direction"] == best_dir
                            and abs(tr["entry"] - entry_p) < 0.5 * avg_atr), None)
            if similar:
                await query.message.reply_text(
                    t(uid,"duplicate_setup") + "\n" + t(uid,"existing_entry_zone") + ": " + format_entry_zone(similar["entry"], similar.get("atr", 0)))
                return

            trade_counter += 1
            res_use["id"]     = trade_counter
            res_use["forced"] = True

            allowed_override, _m_override, _reason_override = saz_dna_assessment(res_use, uid, mode="override")
            if not allowed_override:
                res_use["decision_metrics"] = _m_override
                res_use["saz_dna_reason"] = _reason_override
                await query.message.reply_text(saz_dna_rejection_message(res_use, uid))
                return

            trade_msg = build_trade_msg(res_use, uid)
            fl_now    = res_use.get("frame_lines", [])
            warning = "\n\n" + t(uid,"higher_risk_warning")
            await query.message.reply_text(trade_msg + warning)

            is_p = abs(entry_p - res_use["price"]) / res_use["price"] * 100 > 0.1
            snap = {
                "buy":  count_qualified_frame_lines(fl_now)[0],
                "sell": count_qualified_frame_lines(fl_now)[1],
            }
            nt = {
                "id": trade_counter, "asset": asset_ov,
                "direction": best_dir, "entry": entry_p,
                "sl": res_use["sl"], "tp1": res_use["tp1"],
                "tp2": res_use["tp2"], "tp3": res_use["tp3"],
                "atr": res_use["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res_use["sl"],
                "status": "pending" if is_p else "active",
                "actual_entry": res_use.get("price") if not is_p else None,
                "chat_id": query.message.chat_id, "open_time": gmt_now(),
                "frame_snapshot": snap, "entry_update_sent": False,
                "entry_alert_sent": False, "last_news_event": "",
                "last_frame_alert": "", "last_active_alert": "",
                "forced": True,
                "setup_grade": (res_sig.get("decision_metrics", {}) or {}).get("setup_grade", ""),
                "setup_grade": (res_use.get("decision_metrics", {}) or {}).get("setup_grade", ""),
            }
            async with get_trades_lock():
                active_trades.append(nt)
                if asset_ov == "BTC": active_btc_trade["data"] = nt
                save_trades()
                save_runtime_state()
        except Exception as e:
            logger.error(f"Override trade: {e}")
            await query.message.reply_text(t(uid, "error") + str(e))
        return

    elif data == "about":
        await query.message.reply_text(t(uid,"about_text"))


# 
#  PENDING TRADE HEALTH REPORT
# 
def _build_health_report(trade: dict, res: dict, current: float):
    """
    Returns (msg_text, n_cancel_reasons).
    Used to review pending and active trades when market conditions change.
    """
    uid = trade.get("chat_id", 0)
    tid   = trade.get("id", "?")
    dire  = trade.get("direction", "")
    entry = trade.get("entry", 0)  # Smart/reference entry used for original SL/TP plan
    status = trade.get("status", "active")
    actual_entry = trade.get("actual_entry")
    # Pending trades are measured versus the reference zone. Active trades show actual entry separately.
    dist_ref = entry
    dist = abs(current - dist_ref) / dist_ref * 100 if dist_ref else 0
    if dire == "BUY":
        dist_dir = t(uid,"above") if current > dist_ref else t(uid,"below")
    else:
        dist_dir = t(uid,"below") if current < dist_ref else t(uid,"above")

    frame_lines = res.get("frame_lines", [])
    buy_f, sell_f = count_qualified_frame_lines(frame_lines)
    match = buy_f if dire == "BUY" else sell_f
    opposite = sell_f if dire == "BUY" else buy_f

    hold_r = []
    cancel_r = []

    # SazBot 2.1 DNA health check: if the trade quality deteriorates, it becomes a real risk reason.
    try:
        _ok_health, _m_health, _r_health = saz_dna_assessment(res, uid, mode="health")
        if not _ok_health and _m_health.get("decision") == "STAY_OUT":
            cancel_r.append(t(uid, "dna_conditions_deteriorated"))
    except Exception as _e:
        logger.warning("DNA health check failed: " + str(_e))

    if match >= 2:
        hold_r.append("✅ " + t(uid,"frames_still_support"))
    if opposite >= 2:
        cancel_r.append("⚠️ " + t(uid,"frames_oppose"))
    if opposite == 3:
        cancel_r.append(t(uid,"full_reversal"))

    mb = res.get("monthly_bias", "NEUTRAL")
    wt = res.get("weekly_trend", "NEUTRAL")
    rg = res.get("regime", "UNKNOWN")
    div = res.get("divergence", "NONE")

    if (dire == "BUY" and mb == "BULL") or (dire == "SELL" and mb == "BEAR"):
        hold_r.append(t(uid,"monthly_supports"))
    elif (dire == "BUY" and mb == "BEAR") or (dire == "SELL" and mb == "BULL"):
        cancel_r.append(t(uid,"monthly_against"))

    if (dire == "BUY" and wt == "BULL") or (dire == "SELL" and wt == "BEAR"):
        hold_r.append(t(uid,"weekly_supports"))
    elif (dire == "BUY" and wt == "BEAR") or (dire == "SELL" and wt == "BULL"):
        cancel_r.append(t(uid,"weekly_against"))

    if rg == "VOLATILE":
        cancel_r.append(t(uid,"volatility_risk"))
    elif rg == "RANGING":
        cancel_r.append(t(uid,"ranging_risk"))
    elif (dire == "BUY" and rg == "TRENDING_UP") or (dire == "SELL" and rg == "TRENDING_DOWN"):
        hold_r.append(t(uid,"regime_supports"))
    elif rg in ("TRENDING_UP", "TRENDING_DOWN"):
        cancel_r.append(t(uid,"regime_against"))

    if (div == "BEARISH" and dire == "BUY") or (div == "BULLISH" and dire == "SELL"):
        cancel_r.append(t(uid,"rsi_against"))
    elif (div == "BULLISH" and dire == "BUY") or (div == "BEARISH" and dire == "SELL"):
        hold_r.append(t(uid,"rsi_supports"))

    nc = len(cancel_r)
    nh = len(hold_r)
    if nc >= 2:
        verdict = t(uid,"recommend_cancel")
    elif nc == 1 and nh == 0:
        verdict = t(uid,"recommend_review")
    elif nh >= 2 and nc == 0:
        verdict = t(uid,"recommend_keep")
    else:
        verdict = t(uid,"recommend_monitor")

    st = ("⏳ " + t(uid,"pending")) if status == "pending" else ("🟢 " + t(uid,"active"))
    dir_line = t(uid,"buy") if dire == "BUY" else t(uid,"sell")

    lines = [
        f"🟡 SazBot | {t(uid,'trade_health')} #{tid}",
        st,
        "",
        dir_line,
    ]
    if trade.get("forced"):
        lines.append(t(uid,"forced_note"))
    if status == "active" and actual_entry:
        lines += [
            f"📍 {t(uid,'actual_entry')}: ${float(actual_entry):,.2f}",
            f"🎯 {t(uid,'entry_reference_zone')}: {format_entry_zone(entry, trade.get('atr', 0))}",
        ]
    else:
        lines.append(f"🎯 {t(uid,'entry_zone')}: {format_entry_zone(entry, trade.get('atr', 0))}")
    lines += [
        f"💵 {t(uid,'current_price')}: ${current:,.2f}",
        f"📏 {t(uid,'distance')}: {dist:.2f}% {dist_dir} {t(uid,'entry_zone_word')}",
        "",
    ]
    lines += safe_saz_intelligence_block(res, uid, compact=True)
    lines += [
        "",
        f"🧭 {t(uid,'confluence')}",
    ]
    for fl in frame_lines:
        lines.append(display_frame_line(uid, fl))
    lines += ["", "📊 " + t(uid,"risk_review")]
    for h in hold_r:
        lines.append(h)
    for c in cancel_r:
        lines.append(c)
    lines += [
        "",
        verdict,
        "",
        f"🛑 SL: ${trade['sl']:,.2f}",
        f"🎯 TP1: ${trade['tp1']:,.2f} | TP2: ${trade['tp2']:,.2f} | TP3: ${trade['tp3']:,.2f}",
        "",
        f"🕐 {gmt_now()}",
        t(uid,"footer"),
    ]
    return "\n".join(lines), nc

async def check_pending_trades(context):
    """
    Single full_analysis call per cycle.
    • Pending trades: rich health report → auto-cancel if ≥2 strong reasons
    • Active trades: frame-change alert with verdict
    • Stale pending (>48h): auto-cancel with notification
    • All alerts deduplicated via last_frame_alert key
    """
    if not active_trades:
        return

    cur = await run_blocking(get_btc_price)
    res = None
    try:
        res = await run_blocking(full_analysis, "BTC", 0)
    except Exception as e:
        logger.error(f"check_pending_trades analysis: {e}")

    if not res or not cur:
        return

    frame_lines = res.get("frame_lines", [])
    buy_f, sell_f = count_qualified_frame_lines(frame_lines)
    total_f = buy_f + sell_f
    n = now_ts()

    for trade in list(active_trades):
        tid       = trade.get("id", "?")
        chat_id   = trade["chat_id"]
        dire      = trade["direction"]
        status    = trade.get("status", "active")
        match     = buy_f if dire == "BUY" else sell_f
        opposite  = sell_f if dire == "BUY" else buy_f

        try:
            # ── 1. Stale pending: auto-cancel after PENDING_MAX_AGE hours ──
            if status == "pending":
                try:
                    open_dt = datetime.strptime(
                        trade.get("open_time", ""), "%d/%m/%Y  %H:%M"
                    ).replace(tzinfo=timezone.utc)
                    age_h = (n - open_dt.timestamp()) / 3600
                    if age_h > PENDING_MAX_AGE:
                        async with get_trades_lock():
                            if trade in active_trades:
                                active_trades.remove(trade)
                            save_trades()
                            save_runtime_state()
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"{t(chat_id,'pending_expired_title')} #{tid}\n\n{t(chat_id,'pending_expired_body')}")
                        continue
                except Exception as e:
                    logger.warning("silent exception: " + str(e))

            # ── 2. Full reversal: all frames flipped ──
            if total_f > 0 and opposite == total_f:
                alert_key = f"flip_{buy_f}_{sell_f}"
                if trade.get("last_frame_alert") != alert_key:
                    trade["last_frame_alert"] = alert_key
                    opp_dir = "SELL ⬇️" if dire == "BUY" else "BUY ⬆️"
                    local_res = (await run_blocking(full_analysis, "BTC", chat_id)) or res
                    msg, nc = _build_health_report(trade, local_res, cur)
                    if status == "pending":
                        async with get_trades_lock():
                            if trade in active_trades:
                                active_trades.remove(trade)
                            save_trades()
                            save_runtime_state()
                        await context.bot.send_message(chat_id=chat_id,
                            text=msg + f"\n\n{t(chat_id,'auto_cancel_timeframes')} {opp_dir}")
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(t(chat_id,"btn_keep_trade"), callback_data=f"keep_active_{tid}"),
                            InlineKeyboardButton(t(chat_id,"btn_close_trade"), callback_data=f"close_active_{tid}"),
                        ]])
                        await context.bot.send_message(chat_id=chat_id,
                            text=msg, reply_markup=kb)
                continue

            # ── 3. Partial change: send rich health report if frames changed ──
            if total_f > 0:
                snap      = trade.get("frame_snapshot", {})
                snap_buy  = snap.get("buy", -1)
                snap_sell = snap.get("sell", -1)
                frames_changed = (buy_f != snap_buy or sell_f != snap_sell)
                alert_key = f"partial_{buy_f}_{sell_f}"

                if frames_changed and trade.get("last_frame_alert") != alert_key:
                    trade["last_frame_alert"] = alert_key
                    local_res = (await run_blocking(full_analysis, "BTC", chat_id)) or res
                    msg, nc = _build_health_report(trade, local_res, cur)

                    if status == "pending":
                        if nc >= 2:
                            # Auto-cancel: 2+ strong reasons against
                            async with get_trades_lock():
                                if trade in active_trades:
                                    active_trades.remove(trade)
                                save_trades()
                                save_runtime_state()
                            await context.bot.send_message(chat_id=chat_id,
                                text=msg + "\n\n" + t(chat_id,"auto_cancel_conditions"))
                        else:
                            kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton(t(chat_id,"btn_keep_setup"), callback_data=f"keep_pending_{tid}"),
                                InlineKeyboardButton(t(chat_id,"btn_cancel_setup"), callback_data=f"cancel_pending_{tid}"),
                            ]])
                            await context.bot.send_message(chat_id=chat_id,
                                text=msg, reply_markup=kb)
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(t(chat_id,"btn_keep_trade"), callback_data=f"keep_active_{tid}"),
                            InlineKeyboardButton(t(chat_id,"btn_close_trade"), callback_data=f"close_active_{tid}"),
                        ]])
                        await context.bot.send_message(chat_id=chat_id,
                            text=msg, reply_markup=kb)

        except Exception as e:
            logger.error(f"check_pending_trades trade #{tid}: {e}")


# ==================== مراقبة BTC ====================
async def _check_auto_signal(context):
    """Auto-signal: fires only when RSI is extended, price is near Fib, confidence passes MIN_CONFIDENCE, and 3 qualified timeframes agree."""
    n = now_ts()
    if (n - last_signal_time.get("BTC", 0)) < SPAM_COOLDOWN:
        return
    try:
        df_q = await run_blocking(get_data, "BTC", days=3, interval="hourly")
        if df_q is None or len(df_q) < 20:
            return
        dq     = calc_indicators(df_q.tail(50).copy())
        lq     = dq.iloc[-1]
        price_q= float(lq["Close"])
        rsi_q  = safe(lq["RSI"], 50)
        fib_q, *_ = calculate_fibonacci(df_q)

        # Soft pre-filter only: do not kill valid BTC moves before DNA sees them.
        near_fib_q = any(abs(price_q - v) / price_q * 100 < 0.7 for v in fib_q.values())
        rsi_extended_q = (rsi_q < 40 or rsi_q > 60)
        if not (near_fib_q or rsi_extended_q):
            return

        no_buy  = not any(tr["asset"]=="BTC" and tr["direction"]=="BUY"  for tr in active_trades)
        no_sell = not any(tr["asset"]=="BTC" and tr["direction"]=="SELL" for tr in active_trades)

        res = await run_blocking(full_analysis, "BTC", 0)
        if not res or res.get("final") == "NEUTRAL":
            return
        # Auto-signals must pass the strictest SazBot 2.1 DNA gate before being sent.
        res = apply_saz_dna_gate(res, 0, mode="auto")
        if not res or res.get("final") == "NEUTRAL" or res.get("blocked_by_saz_dna"):
            return

        fl = res.get("frame_lines", [])
        buy_f, sell_f = count_qualified_frame_lines(fl)

        # Auto-signals remain selective, but not impossible:
        # Prefer full alignment; allow a clean strong setup if the DNA gate approves it.
        three = (res["final"] == "BUY" and buy_f == 3 and sell_f == 0) or (res["final"] == "SELL" and sell_f == 3 and buy_f == 0)
        # For BTC, do not kill every setup just because one timeframe is temporarily opposite.
        # Full alignment is best; strong directional agreement can still be tradable if DNA approves.
        strong_partial = (
            (res["final"] == "BUY" and buy_f >= 2 and sell_f <= 1) or
            (res["final"] == "SELL" and sell_f >= 2 and buy_f <= 1)
        )

        # Timing rescue: 1H + Daily alignment can be a valid BTC scalp/swing even when 4H is lagging.
        frame_txt = " ".join(res.get("frame_lines", []))
        timing_rescue = (
            (res["final"] == "SELL" and "1H: SELL" in frame_txt and "Daily: SELL" in frame_txt) or
            (res["final"] == "BUY" and "1H: BUY" in frame_txt and "Daily: BUY" in frame_txt) or
            (res["final"] == "SELL" and "ساعة: SELL" in frame_txt and "يومي: SELL" in frame_txt) or
            (res["final"] == "BUY" and "ساعة: BUY" in frame_txt and "يومي: BUY" in frame_txt)
        )

        if not (three or strong_partial or timing_rescue):
            return

        dir_ok = (res["final"]=="BUY" and no_buy) or (res["final"]=="SELL" and no_sell)
        ep = float(res["entry_price"])
        sig_atr = float(res.get("atr", ep * 0.015) or ep * 0.015)
        entry_low = float(res.get("entry_low", ep))
        entry_high = float(res.get("entry_high", ep))

        # Do not send a new signal if price is already too far away from the Smart Entry Zone.
        if is_price_too_far_from_entry_zone(res.get("price", price_q), entry_low, entry_high, max_distance_for_setup_grade(res)):
            return

        # Do not re-offer a recently cancelled setup in the same zone/direction.
        if is_recently_cancelled("BTC", res["final"], ep, sig_atr):
            return

        dup = any(tr["asset"]=="BTC" and tr["direction"]==res["final"]
                  and abs(tr["entry"] - ep) < 0.5 * sig_atr
                  for tr in active_trades)

        if not (dir_ok and not dup):
            return

        global trade_counter
        last_signal_time["BTC"] = n
        trade_counter += 1
        res["id"] = trade_counter

        ev = await run_blocking(get_upcoming_event, 2)
        pending_signals[trade_counter] = {
            "res": res, "entry_p": ep, "timestamp": n,
            "entry_low": res.get("entry_low", ep),
            "entry_high": res.get("entry_high", ep),
            "price": res["price"], "chat_ids": [],
        }
        for uid in ALLOWED_USERS:
            try:
                sig_msg = build_trade_msg(res, uid, auto=True)
                if ev:
                    sig_msg += f"\n\n⚠️ {t(uid,'high_impact_event')}: {ev.get('event','')} {t(uid,'event_in')} {_mins_txt(ev['mins_left'])}"
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(t(uid,"btn_activate_setup"), callback_data=f"activate_signal_{trade_counter}"),
                    InlineKeyboardButton(t(uid,"btn_ignore"), callback_data=f"ignore_signal_{trade_counter}"),
                ]])
                await context.bot.send_message(chat_id=uid, text=sig_msg, reply_markup=kb)
                pending_signals[trade_counter]["chat_ids"].append(uid)
            except Exception as e:
                logger.warning("silent send/action failed: " + str(e))
    except Exception as e:
        logger.error(f"Auto-signal: {e}")


async def _expire_pending_signals(context):
    """Expire pending signals only after a short grace period, using Smart Entry Zone distance and timeframe validation."""
    if not pending_signals:
        return
    try:
        n = now_ts()
        cur = await run_blocking(get_btc_price)
        fresh = None
        try:
            fresh = await run_blocking(full_analysis, "BTC", 0)
        except Exception:
            fresh = None

        to_exp = []
        for sid, sig in list(pending_signals.items()):
            expired = False
            reason_key = ""
            age = n - float(sig.get("timestamp", n))

            # Avoid the bad UX where a fresh signal is generated and expired in the same cycle.
            if age < PENDING_SIGNAL_MIN_AGE_BEFORE_EXPIRY:
                continue

            sig_res = sig.get("res", {})
            sig_dir = sig_res.get("final")
            sig_entry = float(sig.get("entry_p", sig_res.get("entry_price", 0)) or 0)
            sig_atr = float(sig_res.get("atr", sig_entry * 0.015) or sig_entry * 0.015)
            entry_low = float(sig.get("entry_low", sig_res.get("entry_low", sig_entry)) or sig_entry)
            entry_high = float(sig.get("entry_high", sig_res.get("entry_high", sig_entry)) or sig_entry)

            # Expire by distance from Smart Entry Zone, not from the market price at signal creation.
            if cur and is_price_too_far_from_entry_zone(cur, entry_low, entry_high, MAX_DISTANCE_FROM_ZONE_PCT):
                expired = True
                reason_key = "signal_expired_price"

            # Expire if the fresh decision is no longer supportive of the original direction.
            elif fresh:
                fresh_final = fresh.get("final", "NEUTRAL")
                fresh_lines = fresh.get("frame_lines", [])
                fresh_buy, fresh_sell = count_qualified_frame_lines(fresh_lines)
                supportive = (
                    sig_dir == "BUY" and fresh_final == "BUY" and fresh_buy == 3 and fresh_sell == 0
                ) or (
                    sig_dir == "SELL" and fresh_final == "SELL" and fresh_sell == 3 and fresh_buy == 0
                )
                if not supportive:
                    expired = True
                    reason_key = "signal_expired_timeframes"

            elif age > SIGNAL_EXPIRY:
                expired = True
                reason_key = "signal_expired_time"

            if expired:
                to_exp.append(sid)
                remember_cancelled_setup("BTC", sig_dir, sig_entry, sig_atr, reason=reason_key)
                for cid in sig.get("chat_ids", list(ALLOWED_USERS)):
                    lang = user_languages.get(cid, "ar")
                    if lang == "ar":
                        msg = f"⏰ SazBot | انتهت صلاحية الإشارة #{sid}"
                        if reason_key:
                            msg += f"\n\n{t(cid, reason_key)}"
                        msg += "\n\n⏳ سيتم انتظار فرصة جديدة بجودة أعلى."
                    else:
                        msg = f"⏰ SazBot | Signal Expired #{sid}"
                        if reason_key:
                            msg += f"\n\n{t(cid, reason_key)}"
                        msg += "\n\n⏳ Waiting for a higher-quality setup."
                    try:
                        await context.bot.send_message(chat_id=cid, text=msg)
                    except Exception as e:
                        logger.warning("silent exception: " + str(e))

        for sid in to_exp:
            pending_signals.pop(sid, None)
    except Exception as e:
        logger.error(f"Expire signals: {e}")

async def _economic_alert_no_trades(context):
    """Alert about upcoming high-impact event when no trades are open."""
    if active_trades:
        return
    try:
        ev30 = await run_blocking(get_upcoming_event, 0.5)
        if not ev30:
            return
        ek = _event_key(ev30)
        if _news_notified.get(ek):
            return
        _news_notified[ek] = True
        for uid in ALLOWED_USERS:
            if user_languages.get(uid, "ar") == "ar":
                nm = (f"📰 تنبيه اقتصادي مهم\n"
                      f"{ev30['event']} — خلال {_mins_txt(ev30['mins_left'])}\n"
                      f"التأثير المتوقع: 🔴 عالي\n"
                      f"{t(uid,'avoid_new_trades')}")
            else:
                nm = (f"📰 Important Economic Alert\n"
                      f"{ev30['event']} — in {_mins_txt(ev30['mins_left'])}\n"
                      f"Expected impact: 🔴 High\n"
                      f"Avoid opening new trades until the event passes.")
            try:
                await context.bot.send_message(chat_id=uid, text=nm)
            except Exception as e:
                logger.warning("silent send/action failed: " + str(e))
    except Exception as e:
        logger.warning(f"Econ alert: {e}")

async def _monitor_active_trades(context):
    """Monitor SL/TP on all active trades, send updates, remove closed ones."""
    if not active_trades:
        return
    cur = await run_blocking(get_btc_price)
    if not cur:
        return

    to_remove = []
    _session, _ = get_current_session()

    for trade in list(active_trades):
        try:
            chat_id   = trade["chat_id"]
            direction = trade["direction"]
            entry     = trade["entry"]
            atr       = trade["atr"]
            tp1       = trade["tp1"]; tp2 = trade["tp2"]; tp3 = trade["tp3"]
            sl        = trade["sl"]
            trade_id  = trade.get("id", "?")
            update_msg= None; closed = False

            # ── Pending: wait for price to reach entry ──
            if trade.get("status") == "pending":
                low_z, high_z = entry_zone_from_trade(entry, atr)
                if direction == "BUY":
                    zone_dist = ((cur - high_z) / entry * 100) if cur > high_z else ((low_z - cur) / entry * 100 if cur < low_z else 0)
                else:
                    zone_dist = ((low_z - cur) / entry * 100) if cur < low_z else ((cur - high_z) / entry * 100 if cur > high_z else 0)
                if zone_dist > MAX_DISTANCE_FROM_ZONE_PCT:
                    to_remove.append(trade)
                    remember_cancelled_setup(trade, reason="price_moved_too_far")
                    await context.bot.send_message(chat_id=chat_id,
                        text=(
                            f"⚠️ SazBot | {t(chat_id,'setup_cancelled_full')} #{trade_id}\n\n"
                            f"{t(chat_id,'price_moved_against')}\n\n"
                            f"🎯 {t(chat_id,'entry_zone')}: {format_entry_zone(entry, atr)}\n"
                            f"💵 {t(chat_id,'current_price')}: ${cur:,.2f}"
                        ))
                    continue
                arrived = (direction=="BUY"  and low_z <= cur <= high_z) or (direction=="SELL" and low_z <= cur <= high_z)
                if arrived:
                    try:
                        fresh = await run_blocking(full_analysis, trade["asset"], 0)
                        if fresh is None:
                            trade["status"] = "active"
                            trade["actual_entry"] = cur
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🟢 SazBot | {t(chat_id,'setup_activated')} #{trade_id}\n\n{t(chat_id,'price_reached_entry')}")
                        elif fresh["final"] != direction:
                            to_remove.append(trade)
                            remember_cancelled_setup(trade, reason="bias_changed_at_entry")
                            nd = "BUY ⬆️" if fresh["final"]=="BUY" else "SELL ⬇️"
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"⚠️ SazBot | {t(chat_id,'setup_cancelled_full')} #{trade_id}\n\n{t(chat_id,'price_bias_changed')} {nd}.")
                        else:
                            trade.update({"status":"active","actual_entry":cur,"sl":fresh["sl"],
                                          "tp1":fresh["tp1"],"tp2":fresh["tp2"],
                                          "tp3":fresh["tp3"],"atr":fresh["atr"],
                                          "orig_sl":fresh["sl"]})
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🟢 SazBot | {t(chat_id,'setup_activated')} #{trade_id}\n\n"
                                     f"{t(chat_id,'price_reached_entry')}\n\n"
                                     f"🛑 SL: ${fresh['sl']:,.2f}\n"
                                     f"🎯 TP1: ${fresh['tp1']:,.2f} | TP2: ${fresh['tp2']:,.2f} | TP3: ${fresh['tp3']:,.2f}")
                            async with get_trades_lock():
                                save_trades()
                                save_runtime_state()
                    except Exception as e:
                        logger.error(f"Pending arrival: {e}")
                        trade["status"] = "active"
                        trade["actual_entry"] = cur
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"🟢 SazBot | {t(chat_id,'setup_activated')} #{trade_id}\n\n{t(chat_id,'price_reached_entry')}")
                else:
                    # SL hit before entry
                    sl_pre = (direction=="BUY" and cur <= sl) or (direction=="SELL" and cur >= sl)
                    if sl_pre:
                        to_remove.append(trade)
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"⚠️ SazBot | {t(chat_id,'setup_cancelled_full')} #{trade_id}\n\n"
                                 f"{t(chat_id,'invalid_before_entry')}\n\n"
                                 f"🛑 SL: ${sl:,.2f}\n💵 {t(chat_id,'current_price')}: ${cur:,.2f}")
                    else:
                        dist_pct = abs(cur - entry) / entry * 100
                        if dist_pct <= 0.5 and not trade.get("entry_alert_sent"):
                            trade["entry_alert_sent"] = True
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🎯 SazBot | {t(chat_id,'entry_alert')} #{trade_id}\n\n"
                                     f"{t(chat_id,'approaching_entry')}\n\n"
                                     f"📌 {t(chat_id,'reference_entry')}: ${entry:,.2f}\n💵 {t(chat_id,'current_price')}: ${cur:,.2f}\n📏 {t(chat_id,'distance')}: {dist_pct:.2f}%")
                        # News alert
                        try:
                            ev = await run_blocking(get_upcoming_event, 2)
                            if ev:
                                ek = ev.get("event","")
                                if ek != trade.get("last_news_event",""):
                                    trade["last_news_event"] = ek
                                    await context.bot.send_message(chat_id=chat_id,
                                        text=f"⚠️ SazBot | {t(chat_id,'high_impact_event')} #{trade_id}\n\n"
                                             f"{ek} {t(chat_id,'event_in')} {_mins_txt(ev['mins_left'])}.\n"
                                             f"{t(chat_id,'impact_high')}")
                        except Exception: pass
                        # Entry-passed update
                        ep_passed = (direction=="SELL" and cur < entry*0.99) or                                     (direction=="BUY"  and cur > entry*1.01)
                        if ep_passed and not trade.get("entry_update_sent"):
                            try:
                                fe = await run_blocking(full_analysis, trade["asset"], chat_id)
                                if fe and fe["final"] == direction:
                                    ne = fe.get("entry_price", fe["price"])
                                    if abs(ne - entry) / entry * 100 > 0.1:
                                        trade["entry_update_sent"] = True
                                        trade["pending_update"] = {
                                            "entry":ne,"sl":fe["sl"],"tp1":fe["tp1"],
                                            "tp2":fe["tp2"],"tp3":fe["tp3"],
                                        }
                                        kb_upd = InlineKeyboardMarkup([[
                                            InlineKeyboardButton(t(chat_id,"btn_update_setup"), callback_data=f"update_entry_{trade_id}"),
                                            InlineKeyboardButton(t(chat_id,"btn_ignore"), callback_data=f"ignore_entry_{trade_id}"),
                                        ]])
                                        await context.bot.send_message(chat_id=chat_id,
                                            text=f"📊 SazBot | {t(chat_id,'entry_update')} #{trade_id}\n\n"
                                                 f"{t(chat_id,'conditions_changed_before_activation')}\n\n"
                                                 f"{t(chat_id,'old_reference')}: ${entry:,.2f}\n{t(chat_id,'new_reference')}: ${ne:,.2f}\n\n"
                                                 f"🛑 SL: ${fe['sl']:,.2f}\n🎯 TP1: ${fe['tp1']:,.2f} | TP2: ${fe['tp2']:,.2f}",
                                            reply_markup=kb_upd)
                            except Exception as e:
                                logger.warning(f"Entry update: {e}")
                        # Counter-move cancel
                        ctr = (direction=="SELL" and cur > entry*1.02) or                               (direction=="BUY"  and cur < entry*0.98)
                        if ctr:
                            try:
                                fc = await run_blocking(full_analysis, trade["asset"], chat_id)
                                if fc and fc["final"] != direction:
                                    to_remove.append(trade)
                                    remember_cancelled_setup(trade, reason="counter_move")
                                    nd = "BUY ⬆️" if fc["final"]=="BUY" else "SELL ⬇️"
                                    moved = abs(cur-entry)/entry*100
                                    await context.bot.send_message(chat_id=chat_id,
                                        text=f"⚠️ SazBot | {t(chat_id,'setup_cancelled_full')} #{trade_id}\n\n"
                                             f"{t(chat_id,'price_moved_against')} {nd}.")
                            except Exception as e:
                                logger.warning(f"Counter-move: {e}")
                continue  # done with pending

            # ── Active: TP / SL logic ──
            if direction == "BUY":
                if cur >= tp3:
                    update_msg = f"🏆 SazBot | {t(chat_id,'tp3_hit')} #{trade_id}"
                    record_trade_result(trade_id, "win", trade.get("rr",0), direction, _session); closed=True
                elif not trade["tp1_hit"] and cur >= tp1:
                    trade["tp1_hit"]=True; trade["sl"]=entry
                    update_msg = f"✅ SazBot | {t(chat_id,'tp1_hit')} #{trade_id}\n${entry:,.2f}"
                elif trade["tp1_hit"] and not trade["tp2_hit"] and cur >= tp2:
                    trade["tp2_hit"]=True
                    nsl = round(tp2-0.25*abs(tp1-tp2), 2); trade["sl"]=nsl
                    update_msg = f"✅✅ SazBot | {t(chat_id,'tp2_hit')} #{trade_id}\n${nsl:,.2f}"
                elif cur <= trade["sl"]:
                    if trade.get("tp2_hit"):
                        rp = round(abs(tp2-entry)/abs(entry-trade.get("orig_sl",sl)),2) if abs(entry-trade.get("orig_sl",sl))>0 else 1.0
                        update_msg = f"✅ SazBot | {t(chat_id,'protected_profit')} #{trade_id}"
                        record_trade_result(trade_id, "win", rp, direction, _session)
                    elif trade.get("tp1_hit"):
                        update_msg = f"🟡 SazBot | {t(chat_id,'breakeven')} #{trade_id}"
                        record_trade_result(trade_id, "breakeven", 0, direction, _session)
                    else:
                        update_msg = f"🛑 SazBot | {t(chat_id,'sl_hit')} #{trade_id}"
                        record_trade_result(trade_id, "loss", 0, direction, _session)
                    closed=True
                elif trade["tp1_hit"] and cur > tp1+0.5*atr:
                    nsl = round(cur-0.8*atr, 2)
                    if nsl > trade["sl"] and nsl-trade["sl"] >= atr:
                        trade["sl"]=nsl
                        update_msg = f"📊 #{trade_id} {t(chat_id,'trailing_sl')} → ${nsl:,.2f}"
            else:  # SELL
                if cur <= tp3:
                    update_msg = f"🏆 SazBot | {t(chat_id,'tp3_hit')} #{trade_id}"
                    record_trade_result(trade_id, "win", trade.get("rr",0), direction, _session); closed=True
                elif not trade["tp1_hit"] and cur <= tp1:
                    trade["tp1_hit"]=True; trade["sl"]=entry
                    update_msg = f"✅ SazBot | {t(chat_id,'tp1_hit')} #{trade_id}\n${entry:,.2f}"
                elif trade["tp1_hit"] and not trade["tp2_hit"] and cur <= tp2:
                    trade["tp2_hit"]=True
                    nsl = round(tp2+0.25*abs(tp1-tp2), 2); trade["sl"]=nsl
                    update_msg = f"✅✅ SazBot | {t(chat_id,'tp2_hit')} #{trade_id}\n${nsl:,.2f}"
                elif cur >= trade["sl"]:
                    if trade.get("tp2_hit"):
                        rp = round(abs(tp2-entry)/abs(entry-trade.get("orig_sl",sl)),2) if abs(entry-trade.get("orig_sl",sl))>0 else 1.0
                        update_msg = f"✅ SazBot | {t(chat_id,'protected_profit')} #{trade_id}"
                        record_trade_result(trade_id, "win", rp, direction, _session)
                    elif trade.get("tp1_hit"):
                        update_msg = f"🟡 SazBot | {t(chat_id,'breakeven')} #{trade_id}"
                        record_trade_result(trade_id, "breakeven", 0, direction, _session)
                    else:
                        update_msg = f"🛑 SazBot | {t(chat_id,'sl_hit')} #{trade_id}"
                        record_trade_result(trade_id, "loss", 0, direction, _session)
                    closed=True
                elif trade["tp1_hit"] and cur < tp1-0.5*atr:
                    nsl = round(cur+0.8*atr, 2)
                    if nsl < trade["sl"] and trade["sl"]-nsl >= atr:
                        trade["sl"]=nsl
                        update_msg = f"📊 #{trade_id} {t(chat_id,'trailing_sl')} → ${nsl:,.2f}"

            if update_msg:
                await context.bot.send_message(chat_id=chat_id,
                    text=build_update_msg(trade, cur, update_msg, chat_id))
            if closed:
                to_remove.append(trade)

        except Exception as e:
            logger.error(f"Monitor trade #{trade.get('id','?')}: {e}")

    if to_remove:
        async with get_trades_lock():
            for tr in to_remove:
                if tr in active_trades: active_trades.remove(tr)
            save_trades()
            save_runtime_state()


async def monitor_btc(context):
    """
    Main 60-second job — orchestrates 4 sub-tasks:
    1. Auto-signal detection
    2. Expire stale pending signals
    3. Economic event alert (no open trades)
    4. SL/TP monitoring on active trades
    """
    await _check_auto_signal(context)
    await _expire_pending_signals(context)
    await _economic_alert_no_trades(context)
    await _monitor_active_trades(context)



# ==================== Early Bias Alerts ====================
def saz_directional_bias(res):
    """Return directional bias based on the current SazBot analysis and DNA metrics.
    This is an early-bias engine, not a trade signal.
    """
    try:
        metrics = res.get("decision_metrics") or saz_decision_intelligence(res, 0, persist=False, refresh=False)
        quality = float(metrics.get("quality", 0))
        risk = float(metrics.get("regret", 100))
        frames = _frame_snapshot(res)
        buy_score = sell_score = 0.0

        for f in frames:
            d = f.get("direction", "NEUTRAL")
            c = float(f.get("conf", 0) or 0)
            name = f.get("name", "")
            # Public names vary by language, so infer weight from name text.
            if "Daily" in name or "يومي" in name:
                w = 0.50
            elif "4H" in name or "4 ساعات" in name:
                w = 0.30
            elif "1H" in name or "ساعة" in name:
                w = 0.20
            else:
                w = 0.10
            if d == "BUY":
                buy_score += w * c
            elif d == "SELL":
                sell_score += w * c

        # Higher-timeframe bias nudges, without exposing internal rules.
        if res.get("weekly_trend") == "BULL":
            buy_score += 8
        elif res.get("weekly_trend") == "BEAR":
            sell_score += 8
        if res.get("monthly_bias") == "BULL":
            buy_score += 5
        elif res.get("monthly_bias") == "BEAR":
            sell_score += 5

        # Momentum structure nudges.
        if res.get("macd_bull"):
            buy_score += 4
        else:
            sell_score += 2
        if res.get("ema_bull"):
            buy_score += 5
        elif res.get("ema_bear"):
            sell_score += 5

        total = buy_score + sell_score
        if total <= 0:
            return {"bias": "NEUTRAL", "confidence": 0, "quality": quality, "risk": risk}
        if buy_score > sell_score:
            bias = "BUY"
            confidence = int(round((buy_score / total) * 100))
        elif sell_score > buy_score:
            bias = "SELL"
            confidence = int(round((sell_score / total) * 100))
        else:
            bias = "NEUTRAL"
            confidence = 50

        # DNA quality limits enthusiasm.
        if quality < 45 or risk > 82:
            bias = "NEUTRAL"
            confidence = min(confidence, 55)
        return {"bias": bias, "confidence": confidence, "quality": quality, "risk": risk}
    except Exception as e:
        logger.warning("saz_directional_bias failed: " + str(e))
        return {"bias": "NEUTRAL", "confidence": 0, "quality": 0, "risk": 100}

def build_early_bias_alert(uid, res, trigger_label, price, bias_data=None):
    lang = user_languages.get(uid, "ar")
    b = bias_data or saz_directional_bias(res)
    bias = b["bias"]
    conf = int(b["confidence"])
    metrics = res.get("decision_metrics") or saz_decision_intelligence(res, uid, persist=False, refresh=False)
    decision = metrics.get("decision_text", "")
    quality = int(metrics.get("quality", 0))

    if lang == "ar":
        if bias == "BUY":
            bias_line = f"📈 أفضلية الاتجاه: BUY ({conf}%)"
            read = "قراءة SazBot تميل للصعود، لكن الصفقة لم تكتمل بعد."
        elif bias == "SELL":
            bias_line = f"📉 أفضلية الاتجاه: SELL ({conf}%)"
            read = "قراءة SazBot تميل للهبوط، لكن الصفقة لم تكتمل بعد."
        else:
            bias_line = "↔️ أفضلية الاتجاه: محايد"
            read = "لا توجد أفضلية واضحة للشراء أو البيع حالياً."

        return "\n".join([
            "⚡ SazBot 2.2 | تنبيه مبكر",
            "",
            f"💵 السعر الحالي: ${price:,.2f}",
            "",
            "📌 ماذا يحدث؟",
            trigger_label,
            "",
            "🧠 قراءة SazBot:",
            read,
            bias_line,
            f"📊 جودة السوق: {quality}/100",
            "",
            "🎯 القرار:",
            decision,
            "⏳ بانتظار اكتمال شروط الصفقة قبل إصدار إشارة دخول.",
            "",
            f"🕐 {t(uid,'updated_gmt')}: {gmt_now()}",
            t(uid,"educational_footer"),
        ])

    else:
        if bias == "BUY":
            bias_line = f"📈 Directional Bias: BUY ({conf}%)"
            read = "SazBot currently leans bullish, but a trade setup is not confirmed yet."
        elif bias == "SELL":
            bias_line = f"📉 Directional Bias: SELL ({conf}%)"
            read = "SazBot currently leans bearish, but a trade setup is not confirmed yet."
        else:
            bias_line = "↔️ Directional Bias: Neutral"
            read = "There is no clear edge for BUY or SELL at the moment."

        return "\n".join([
            "⚡ SazBot 2.2 | Early Bias Alert",
            "",
            f"💵 Current Price: ${price:,.2f}",
            "",
            "📌 What is happening?",
            trigger_label,
            "",
            "🧠 SazBot Read:",
            read,
            bias_line,
            f"📊 Market Quality: {quality}/100",
            "",
            "🎯 Decision:",
            decision,
            "⏳ Waiting for full trade conditions before issuing an entry signal.",
            "",
            f"🕐 {t(uid,'updated_gmt')}: {gmt_now()}",
            t(uid,"educational_footer"),
        ])

def should_send_bias_alert(uid, bias, confidence, trigger_key):
    """Avoid spamming the same early-bias alert."""
    if bias == "NEUTRAL" and confidence < 60:
        return False
    now = now_ts()
    key = str(uid)
    old = last_bias_alert_state.get(key, {})
    same = old.get("bias") == bias and old.get("trigger") == trigger_key
    if same and now - float(old.get("ts", 0)) < 45 * 60:
        return False
    last_bias_alert_state[key] = {"bias": bias, "confidence": confidence, "trigger": trigger_key, "ts": now}
    save_bias_alert_state()
    return True


async def send_smart_alerts(context):
    """Smart alerts now act as Early Bias Alerts.
    They describe what changed, SazBot's preferred direction if any, and whether a real trade signal is ready.
    """
    try:
        df = await run_blocking(get_data, "BTC", days=7, interval="hourly")
        if df is None or len(df) < 30:
            return
        df    = calc_indicators(df)
        last  = df.iloc[-1]
        price = float(last["Close"])
        rsi   = safe(last["RSI"], 50)
        fib_levels, _, _, _ = calculate_fibonacci(df)

        # Pull full SazBot analysis so alerts use the same DNA and decision engine.
        res = await run_blocking(full_analysis, "BTC", 0)
        if not res:
            return

        # Build high-level triggers without exposing indicator internals.
        bb_u = safe(last["BB_U"], price * 1.02)
        bb_l = safe(last["BB_L"], price * 0.98)
        squeeze = (bb_u - bb_l) / bb_u * 100 < 2

        def trigger_for(uid):
            lang = user_languages.get(uid, "ar")
            trigger_key = None
            label = None

            if squeeze:
                trigger_key = "compression"
                label = ("السوق يتحرك داخل نطاق ضيق، وقد تزداد الحركة خلال الفترة القادمة."
                         if lang == "ar" else
                         "The market is moving inside a tight range, and volatility may expand soon.")
            elif rsi < 28:
                trigger_key = "oversold"
                label = ("السعر تحت ضغط بيعي واضح وقد تظهر محاولة ارتداد، لكن ننتظر تأكيداً."
                         if lang == "ar" else
                         "Price is under clear selling pressure and may attempt a rebound, but confirmation is still needed.")
            elif rsi > 72:
                trigger_key = "overbought"
                label = ("السعر ممتد للأعلى وقد يظهر تباطؤ أو انعكاس، لكن ننتظر تأكيداً."
                         if lang == "ar" else
                         "Price is extended to the upside and may slow or reverse, but confirmation is still needed.")
            else:
                for pct, level in fib_levels.items():
                    if abs(price - level) / price * 100 < 0.3:
                        trigger_key = "key_level"
                        label = (f"السعر يقترب من مستوى فني مهم قرب ${level:,.2f}."
                                 if lang == "ar" else
                                 f"Price is approaching an important technical area near ${level:,.2f}.")
                        break
            return trigger_key, label

        # Economic event alert remains separate.
        if not active_trades:
            try:
                ev30 = await run_blocking(get_upcoming_event, hours=0.5)
                if ev30:
                    ev30_key = ev30.get("event", "") + ev30.get("time", "")[:10]
                    if not _news_notified.get(ev30_key):
                        _news_notified[ev30_key] = True
                        for user_id in ALLOWED_USERS:
                            mins_txt = _mins_txt(ev30["mins_left"])
                            if user_languages.get(user_id, "ar") == "ar":
                                news_msg = (f"⚠️ SazBot | {t(user_id,'high_impact_event')}\n\n"
                                            f"{ev30['event']} — خلال {mins_txt}\n"
                                            f"{t(user_id,'impact_high')}\n"
                                            f"{t(user_id,'avoid_new_trades')}")
                            else:
                                news_msg = (f"⚠️ SazBot | {t(user_id,'high_impact_event')}\n\n"
                                            f"{ev30['event']} — in {mins_txt}\n"
                                            f"{t(user_id,'impact_high')}\n"
                                            f"Avoid opening new trades until the event passes.")
                            try:
                                await context.bot.send_message(chat_id=user_id, text=news_msg)
                            except Exception as e:
                                logger.warning("silent exception: " + str(e))
            except Exception as e:
                logger.warning("silent send/action failed: " + str(e))

        for user_id in ALLOWED_USERS:
            trigger_key, label = trigger_for(user_id)
            if not trigger_key or not label:
                continue

            b = saz_directional_bias(res)
            if not should_send_bias_alert(user_id, b["bias"], b["confidence"], trigger_key):
                continue

            msg = build_early_bias_alert(user_id, res, label, price, bias_data=b)
            try:
                await context.bot.send_message(chat_id=user_id, text=msg)
            except Exception as e:
                logger.warning("silent send/action failed: " + str(e))
    except Exception as e:
        logger.error("Smart alerts: " + str(e))

# ==================== أخبار ====================

def fetch_market_news():
    """Blocking news fetcher. Called via run_blocking() from async send_news."""
    r = requests.get("https://newsapi.org/v2/everything",
        params={"q":"bitcoin OR Federal Reserve OR inflation OR CPI",
                "language":"en","sortBy":"publishedAt","pageSize":5,"apiKey":NEWS_API_KEY},
        timeout=10)
    data = r.json()
    if data.get("status") != "ok":
        return []
    return data.get("articles", []) or []


async def send_news(context):
    try:
        articles = await run_blocking(fetch_market_news)
        if not articles:
            return
        lines = ["","  📰 أخبار السوق - SazBot","",""]
        for i, a in enumerate(articles[:5], 1):
            lines.append(str(i)+". "+a.get("title","")[:80])
            lines.append("   📌 "+a.get("source",{}).get("name","")+"  |  "+a.get("publishedAt","")[:10])
            lines.append("")
        lines += [""*24,"🕐 "+gmt_now(),t(CHANNEL_ID,"educational_footer")]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
    except Exception as e:
        logger.error("News: " + str(e))

# 
#  STATS — Advanced tracking
# 
def load_stats() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "total": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "total_rr": 0.0, "trades": [],
            # Per-direction
            "buy_total": 0, "buy_wins": 0,
            "sell_total": 0, "sell_wins": 0,
            # Per-session
            "session_stats": {},   # {"NY": {"total":n,"wins":n}, ...}
            # Streak
            "current_streak": 0, "best_streak": 0, "worst_streak": 0,
            "last_result": None,
            "grade_stats": _empty_grade_stats(),
        }

def save_stats(stats: dict):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, ensure_ascii=False)

def record_trade_result(trade_id, result: str, rr: float = 0.0,
                        direction: str = "", session: str = "", setup_grade: str = ""):
    stats = normalise_grade_stats(load_stats())
    stats["total"] = stats.get("total", 0) + 1

    # ── result counters ──
    if result == "win":
        stats["wins"] = stats.get("wins", 0) + 1
        stats["total_rr"] = stats.get("total_rr", 0.0) + rr
    elif result == "breakeven":
        stats["breakeven"] = stats.get("breakeven", 0) + 1
    else:
        stats["losses"] = stats.get("losses", 0) + 1

    # ── per-direction ──
    if direction == "BUY":
        stats["buy_total"] = stats.get("buy_total", 0) + 1
        if result == "win":
            stats["buy_wins"] = stats.get("buy_wins", 0) + 1
    elif direction == "SELL":
        stats["sell_total"] = stats.get("sell_total", 0) + 1
        if result == "win":
            stats["sell_wins"] = stats.get("sell_wins", 0) + 1

    # ── per-session ──
    if session:
        ss = stats.setdefault("session_stats", {})
        se = ss.setdefault(session, {"total": 0, "wins": 0})
        se["total"] += 1
        if result == "win":
            se["wins"] += 1

    # ── streak ──
    last = stats.get("last_result")
    cur  = stats.get("current_streak", 0)
    if result == "win":
        cur = cur + 1 if last == "win" else 1
        stats["best_streak"] = max(stats.get("best_streak", 0), cur)
    elif result == "loss":
        cur = cur - 1 if last == "loss" else -1
        stats["worst_streak"] = min(stats.get("worst_streak", 0), cur)
    else:
        cur = 0
    stats["current_streak"] = cur
    stats["last_result"] = result

    # ── trade log ──
    stats.setdefault("trades", []).append({
        "id": trade_id, "result": result, "rr": rr,
        "direction": direction, "session": session,
        "grade": setup_grade,
        "time": gmt_now(),
    })
    stats["trades"] = stats["trades"][-100:]
    if setup_grade:
        record_grade_result(stats, setup_grade, result, rr)
    save_stats(stats)
    logger.info(f"Trade #{trade_id} closed: {result} | RR={rr} | {direction} | {session}")


# 
#  DAILY SUMMARY — Advanced stats
# 
async def send_daily_summary(context):
    try:
        s  = load_stats()
        tc = s.get("total", 0)
        wins = s.get("wins", 0); losses = s.get("losses", 0)
        be   = s.get("breakeven", 0); tr_rr = s.get("total_rr", 0.0)
        wr   = round(wins / tc * 100) if tc > 0 else 0
        ar   = round(tr_rr / wins, 2) if wins > 0 else 0
        bar  = "█" * (wr // 10) + "░" * (10 - wr // 10)
        streak = s.get("current_streak", 0)
        best   = s.get("best_streak", 0)
        worst  = s.get("worst_streak", 0)
        streak_txt = (f"🔥 {streak} رابحة متتالية" if streak > 0
                      else f"⚠️ {abs(streak)} خاسرة متتالية" if streak < 0
                      else "—")
        lines = [
            "",
            "  📊 الملخص اليومي — SazBot",
            "", "",
            "  📈 الأداء الإجمالي  ",
            f"  إجمالي:      {tc}",
            f"  🏆 رابحة:    {wins}",
            f"  🟡 تعادل:    {be}",
            f"  🛑 خاسرة:    {losses}", "",
            f"  {bar}  {wr}%",
            f"  ⚖️ متوسط RR:  1:{ar}",
            f"  🔄 السلسلة:   {streak_txt}",
            f"  🏅 أفضل: {best}   أسوأ: {worst}", "",
        ]
        bt = s.get("buy_total", 0); bw = s.get("buy_wins", 0)
        st2 = s.get("sell_total", 0); sw = s.get("sell_wins", 0)
        if bt > 0 or st2 > 0:
            lines += ["  📊 حسب الاتجاه  "]
            if bt > 0:
                lines.append(f"  🟢 BUY:   {bw}/{bt}  ({round(bw/bt*100)}%)")
            if st2 > 0:
                lines.append(f"  🔴 SELL:  {sw}/{st2}  ({round(sw/st2*100)}%)")
            lines.append("")
        ss = s.get("session_stats", {})
        if ss:
            lines += ["  🕐 حسب الجلسة  "]
            for sname, sv in ss.items():
                stot = sv.get("total", 0); swin = sv.get("wins", 0)
                swr2 = round(swin / stot * 100) if stot else 0
                lines.append(f"  {sname:10s}: {swin}/{stot}  ({swr2}%)")
            lines.append("")
        if active_trades:
            lines += [f"  🔓 صفقات مفتوحة: {len(active_trades)}  "]
            cur = await run_blocking(get_btc_price)
            for tr in active_trades:
                dire = "🔴 SELL" if tr["direction"] == "SELL" else "🟢 BUY"
                st3  = "⏳ معلقة" if tr.get("status") == "pending" else "🟢 نشطة"
                pnl_txt = ""
                if cur and tr.get("status") == "active":
                    pnl = (cur - tr["entry"]) / tr["entry"] * 100
                    if tr["direction"] == "SELL": pnl = -pnl
                    pnl_txt = f"  ({'+' if pnl>=0 else ''}{pnl:.1f}%)"
                lines.append(f"  ₿ #{tr.get('id','?')}  {dire}  {st3}  ${tr['entry']:,.0f}{pnl_txt}")
            lines.append("")
        lines += ["", f"🕐 {gmt_now()}", "⚠️ Educational only — not financial advice."]
        full_msg = "\n".join(lines)
        try: await context.bot.send_message(chat_id=CHANNEL_ID, text=full_msg)
        except Exception: pass
        for uid in ALLOWED_USERS:
            try: await context.bot.send_message(chat_id=uid, text=full_msg)
            except Exception: pass
    except Exception as e:
        logger.error(f"Daily summary: {e}")


# ==================== Main ====================
def main():
    global _trades_lock
    load_runtime_state()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Initialise the lock during bot startup instead of at module import time.
    if _trades_lock is None:
        _trades_lock = asyncio.Lock()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("version", version_command))
    app.add_handler(CommandHandler("why", why_command))
    app.add_handler(CommandHandler("edge", edge_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(monitor_btc,          interval=60,      first=30)
    app.job_queue.run_repeating(check_pending_trades, interval=15*60,  first=60)
    app.job_queue.run_repeating(send_smart_alerts,    interval=45*60,  first=120)
    app.job_queue.run_repeating(send_news,            interval=4*60*60, first=300)
    app.job_queue.run_daily(send_daily_summary, time=__import__("datetime").time(6, 0, 0))
    logger.info("🟡 SazBot - Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
