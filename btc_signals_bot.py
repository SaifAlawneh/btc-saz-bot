import os
import logging
import asyncio
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import ta
import random
import json

# ==================== إعدادات ====================
BOT_TOKEN      = os.environ.get("BOT_TOKEN",  "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "")
NEWS_API_KEY   = os.environ.get("NEWS_API_KEY", "cdf2a61f2cbe4540a41456bc4bd3a40e")
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY", "")

MIN_CONFIDENCE    = 68
SPAM_COOLDOWN     = 1800
CACHE_TTL         = 900
PENDING_MAX_AGE   = 48      # hours: stale pending auto-cancels after this
TRADES_FILE       = "active_trades.json"
STATS_FILE        = "trade_stats.json"
LANGUAGES_FILE    = "user_languages.json"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ✅ FIX 1: asyncio lock لحماية active_trades من race conditions
_trades_lock = asyncio.Lock()

ALLOWED_USERS = {8490817794, 1548286220}

def load_languages():
    try:
        with open(LANGUAGES_FILE) as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except:
        return {}

def save_languages():
    with open(LANGUAGES_FILE, "w") as f:
        json.dump({str(k): v for k, v in user_languages.items()}, f)

def load_trades():
    try:
        with open(TRADES_FILE) as f:
            data = json.load(f)
            return data.get("trades", []), data.get("counter", 0)
    except:
        return [], 0

def save_trades():
    with open(TRADES_FILE, "w") as f:
        json.dump({"trades": active_trades, "counter": trade_counter}, f)

_loaded_languages = load_languages()
user_languages.update(_loaded_languages)

def _validate_loaded_trade(t: dict) -> bool:
    """Ensure trade has valid levels and required fields before restoring after restart."""
    if t.get("asset") != "BTC" or t.get("entry", 0) <= 10_000: return False
    for k in ["entry", "sl", "tp1", "tp2", "tp3", "direction", "chat_id"]:
        if k not in t: return False
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
REPLIES_AR = ["هلا وغلا! 🐎 أنا بوت أبو مهرة\nاستخدم الأزرار 👇",
              "أهلاً! 🤖 تبي صفقة أو تحليل؟ اختر 👇",
              "هلا! 😊 اضغط أي زر للبدء 👇"]
REPLIES_EN = ["Hello! 🐎 I'm Abu Mahra Bot!\nUse the buttons below 👇",
              "Hi! 🤖 Want a trade or analysis? Choose 👇"]
CONFUSED_AR = ["ما فهمت 😅 استخدم الأزرار 👇", "🤔 اختر من القائمة 👇"]
CONFUSED_EN = ["Didn't get that 😅 Use the buttons 👇", "🤔 Choose from the menu 👇"]

TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "welcome": "🐎 أهلاً وسهلاً في بوت أبو مهرة!\n\n━━━━━━━━━━━━━━━━━━━━\nمتخصص في:\n₿ البيتكوين  BTC/USD\n\n✨ مميزاتي:\n▫️ صفقات مبنية على فريم الساعة\n▫️ Fibonacci + ATR للأهداف\n▫️ مستويات دعم ومقاومة دقيقة\n▫️ إشارات تلقائية فورية\n▫️ مراقبة BTC وتحديث SL/TP\n━━━━━━━━━━━━━━━━━━━━\n⚠️ للأغراض التعليمية فقط",
        "btn_btc": "₿ صفقة BTC",
        "btn_analysis_btc": "📈 تحليل BTC",
        "btn_prices": "💰 الأسعار", "btn_about": "ℹ️ عن البوت",
        "btn_lang": "🌐 اللغة", "btn_trades": "📋 الصفقات المفتوحة",
        "btn_stats": "📊 الإحصائيات",
        "no_open_trades": "📭 لا توجد صفقات مفتوحة حالياً",
        "loading_trade": "⏳ جاري تحليل السوق...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices": "⏳ جاري جلب الأسعار...",
        "failed": "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error": "❌ خطأ: ",
        "no_signal": "⚪ لا توجد فرصة واضحة الآن\nانتظر إشارة أقوى 🕐",
        "trade_header": "صفقة ساعة (1H Scalp) - أبو مهرة",
        "auto_header": "إشارة تلقائية - أبو مهرة",
        "update_header": "تحديث صفقة BTC - أبو مهرة",
        "analysis_header": "تحليل السوق - أبو مهرة",
        "entry": "الدخول", "fib_entry": "مستوى Fib",
        "direction": "نوع الصفقة",
        "buy": "شراء  BUY ⬆️", "sell": "بيع  SELL ⬇️",
        "targets_section": "الأهداف",
        "tp1": "TP1", "tp2": "TP2", "tp3": "TP3", "sl": "SL",
        "rr": "العائد / المخاطرة",
        "fib_section": "مستويات Fibonacci",
        "support": "دعم", "resistance": "مقاومة",
        "confluence": "توافق الفريمات",
        "frame_1h": "ساعة", "frame_4h": "4 ساعات", "frame_1d": "يومي",
        "full_confluence": "🔥 توافق كامل على 3 فريمات!",
        "partial_confluence": "✅ توافق على فريمين",
        "no_confluence": "⚪ لا توافق",
        "indicators_section": "المؤشرات",
        "risk_low": "🟢 منخفضة", "risk_med": "🟡 متوسطة", "risk_high": "🔴 عالية",
        "risk_low_msg": "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg": "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",
        "footer": "⚠️ للأغراض التعليمية فقط",
        "updated_gmt": "آخر تحديث (GMT)",
        "update_tp1_hit": "✅ الهدف الأول تم! تم نقل SL للدخول",
        "update_tp2_hit": "✅✅ الهدف الثاني تم! تم نقل SL للـ TP2",
        "update_sl_moved": "📊 تم تحريك وقف الخسارة للأمان",
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
        "summary_neutral": "✅ الخلاصة: السوق في منطقة تردد",
        "prices_title": "💰 الأسعار الحالية", "change_24h": "التغيير 24h",
        "about_text": "ℹ️ عن بوت أبو مهرة 🐎\n\n⏱️ فريم الساعة (1H)\n📐 Fibonacci + ATR للأهداف\n📡 إشارات تلقائية فورية\n🔄 مراقبة BTC كل دقيقة\n🔬 RSI, MACD, EMA, BB, Stoch, ATR, Ichimoku\n⚙️ توافق 3 فريمات\n📊 مصادر: Twelve Data + Binance\n⚠️ للأغراض التعليمية فقط",
        "ind_rsi_oversold": "RSI تشبع بيعي", "ind_rsi_buy": "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي", "ind_rsi_sell": "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️", "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up": "EMAs صاعدة 📈", "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low": "بولنجر: دعم سفلي 🟢", "ind_bb_high": "بولنجر: مقاومة عليا 🔴",
        "ind_stoch_low": "Stochastic تشبع بيعي", "ind_stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "welcome": "🐎 Welcome to Abu Mahra Bot!\n\n━━━━━━━━━━━━━━━━━━━━\nSpecializing in:\n₿ Bitcoin  BTC/USD\n\n✨ Features:\n▫️ 1H timeframe based signals\n▫️ Fibonacci + ATR targets\n▫️ Precise support & resistance\n▫️ Instant auto signals\n▫️ BTC live SL/TP monitoring\n━━━━━━━━━━━━━━━━━━━━\n⚠️ For educational purposes only",
        "btn_btc": "₿ BTC Trade",
        "btn_analysis_btc": "📈 BTC Analysis",
        "btn_prices": "💰 Prices", "btn_about": "ℹ️ About",
        "btn_lang": "🌐 Language", "btn_trades": "📋 Open Trades",
        "btn_stats": "📊 Statistics",
        "no_open_trades": "📭 No open trades at the moment",
        "loading_trade": "⏳ Analyzing market...",
        "loading_analysis": "⏳ Analyzing...",
        "loading_prices": "⏳ Fetching prices...",
        "failed": "❌ Failed to fetch data, try again in a minute",
        "error": "❌ Error: ",
        "no_signal": "⚪ No clear opportunity right now\nWaiting for stronger signal 🕐",
        "trade_header": "1H Scalp Trade - Abu Mahra",
        "auto_header": "Auto Signal - Abu Mahra",
        "update_header": "BTC Trade Update - Abu Mahra",
        "analysis_header": "Market Analysis - Abu Mahra",
        "entry": "Entry", "fib_entry": "Fib Level",
        "direction": "Trade Type",
        "buy": "BUY ⬆️", "sell": "SELL ⬇️",
        "targets_section": "Targets",
        "tp1": "TP1", "tp2": "TP2", "tp3": "TP3", "sl": "SL",
        "rr": "Reward / Risk",
        "fib_section": "Fibonacci Levels",
        "support": "Support", "resistance": "Resistance",
        "confluence": "Timeframe Confluence",
        "frame_1h": "1H", "frame_4h": "4H", "frame_1d": "Daily",
        "full_confluence": "🔥 Full confluence on 3 timeframes!",
        "partial_confluence": "✅ Confluence on 2 timeframes",
        "no_confluence": "⚪ No confluence",
        "indicators_section": "Indicators",
        "risk_low": "🟢 Low", "risk_med": "🟡 Medium", "risk_high": "🔴 High",
        "risk_low_msg": "Good opportunity — Low risk",
        "risk_med_msg": "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",
        "footer": "⚠️ For educational purposes only",
        "updated_gmt": "Last update (GMT)",
        "update_tp1_hit": "✅ TP1 reached! SL moved to entry",
        "update_tp2_hit": "✅✅ TP2 reached! SL moved to TP2",
        "update_sl_moved": "📊 Stop Loss moved to safety",
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
        "summary_neutral": "✅ Summary: Market in consolidation",
        "prices_title": "💰 Current Prices", "change_24h": "24h Change",
        "about_text": "ℹ️ About Abu Mahra Bot 🐎\n\n⏱️ 1H timeframe as base\n📐 Fibonacci + ATR targets\n📡 Instant auto signals\n🔄 BTC live monitoring every minute\n🔬 RSI, MACD, EMA, BB, Stoch, ATR, Ichimoku\n⚙️ 3 timeframe confluence\n📊 Sources: Twelve Data + Binance\n⚠️ For educational purposes only",
        "ind_rsi_oversold": "RSI Oversold", "ind_rsi_buy": "RSI Buy Zone",
        "ind_rsi_overbought": "RSI Overbought", "ind_rsi_sell": "RSI Sell Zone",
        "ind_macd_pos": "MACD Positive ↗️", "ind_macd_neg": "MACD Negative ↘️",
        "ind_ema_up": "EMAs Bullish 📈", "ind_ema_down": "EMAs Bearish 📉",
        "ind_bb_low": "Bollinger: Lower Support 🟢", "ind_bb_high": "Bollinger: Upper Resistance 🔴",
        "ind_stoch_low": "Stochastic Oversold", "ind_stoch_high": "Stochastic Overbought",
    }
}

def t(uid, key):
    lang = user_languages.get(uid, "ar")
    return TEXTS[lang].get(key, key)

def gmt_now():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M")

def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


# ==================== البيانات ====================
def get_binance_data(days=30, interval="hourly"):
    try:
        if interval == "hourly":
            binance_interval = "1h"
            limit = min(days * 24, 1000)
        elif interval == "4h":
            binance_interval = "4h"
            limit = min(days * 6, 1000)
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
    if TWELVEDATA_KEY:
        try:
            r1 = requests.get("https://api.twelvedata.com/price",
                params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY}, timeout=10)
            btc_price = float(r1.json().get("price", 0))
            r2 = requests.get("https://api.twelvedata.com/time_series",
                params={"symbol": "BTC/USD", "interval": "1day", "outputsize": 2,
                        "apikey": TWELVEDATA_KEY}, timeout=10)
            btc_data = r2.json().get("values", [])
            btc_change = 0
            if len(btc_data) >= 2:
                prev = float(btc_data[1]["close"])
                btc_change = round((btc_price - prev) / prev * 100, 2) if prev > 0 else 0
            return {"bitcoin": {"usd": btc_price, "usd_24h_change": btc_change}}
        except Exception as e:
            logger.warning("Twelve Data prices: " + str(e))
    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"}, timeout=10)
        r2 = requests.get("https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": "BTCUSDT"}, timeout=10)
        if r1.status_code == 200 and r2.status_code == 200:
            price  = float(r1.json()["price"])
            change = float(r2.json()["priceChangePercent"])
            return {"bitcoin": {"usd": price, "usd_24h_change": change}}
    except: pass
    try:
        import time; time.sleep(1)
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=10)
        if r.status_code == 200:
            return r.json()
    except: pass
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
    except:
        df["Vol_High"] = False
    return df


def safe(val, default):
    try:
        v = float(val)
        return default if pd.isna(v) else v
    except:
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

    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf  = round(max(sb, ss) / total * 100) if total > 0 else 50
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
        "direction": direction, "conf": conf, "rsi": round(rsi, 1),
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
    except:
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
    except:
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
    except:
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
    except:
        return [], []


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
def full_analysis(asset="BTC", uid=0):
    try:
        df_1h = get_data(asset, days=30,  interval="hourly")
        df_4h = get_data(asset, days=60,  interval="4h")
        df_1d = get_data(asset, days=365, interval="daily")
        df_1w = get_data(asset, days=365, interval="daily")
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

    buy_c = sum(1 for r in results.values() if r["direction"] == "BUY"  and r["conf"] >= 60)
    sel_c = sum(1 for r in results.values() if r["direction"] == "SELL" and r["conf"] >= 60)

    if session == "ASIAN" and buy_c < 2 and sel_c < 2:
        return None

    majority = None
    final = "NEUTRAL"
    conf_txt = t(uid, "no_confluence")
    frames_conf = 0
    if   buy_c == 3: final="BUY";     conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif sel_c == 3: final="SELL";    conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif buy_c == 2: final="NEUTRAL"; conf_txt=t(uid,"partial_confluence"); frames_conf=65; majority="BUY"
    elif sel_c == 2: final="NEUTRAL"; conf_txt=t(uid,"partial_confluence"); frames_conf=65; majority="SELL"

    # Two-frame: return NEUTRAL with majority so button_handler shows override button
    if final == "NEUTRAL" and majority:
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h)
        nf2, fk2, _ = find_nearest_fib(main2["price"], fib_l2, "NEUTRAL") if fib_l2 else (main2["price"],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x:float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            fl2.append(("🟢" if r["direction"]=="BUY" else "🔴")+" "+icons2.get(k,"")+": "+r["direction"]+" ("+str(r["conf"])+"%)")
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

    else:
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h)
        nf2, fk2, _ = find_nearest_fib(main2["price"], fib_l2, "NEUTRAL") if fib_l2 else (main2["price"],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x:float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            fl2.append(("🟢" if r["direction"]=="BUY" else "🔴")+" "+icons2.get(k,"")+": "+r["direction"]+" ("+str(r["conf"])+"%)")
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

    fib_vals_sorted = sorted(fib_levels.values())
    if final == "BUY":
        candidates = [v for v in fib_vals_sorted if v <= price * 1.002 and abs(v - price) / price * 100 <= 0.5]
        entry_price = round(candidates[-1], 2) if candidates else round(price, 2)
    else:
        candidates = [v for v in fib_vals_sorted if v >= price * 0.998 and abs(v - price) / price * 100 <= 0.5]
        entry_price = round(candidates[0], 2) if candidates else round(price, 2)

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
        frame_lines.append(("🟢" if r["direction"]=="BUY" else "🔴")+" "+icons.get(k,"")+": "+r["direction"]+" ("+str(r["conf"])+"%)")

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

    bull_obs, bear_obs = find_order_blocks(df_1h)
    buy_liq, sell_liq  = find_liquidity_zones(df_1h)

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
        risk_warnings.append("⚡ السوق متقلب — حجم صغير")
    elif regime == "RANGING":
        risk_warnings.append("↔️ سوق جانبي — أهداف محدودة")
    if monthly_bias == "BULL" and final == "SELL":
        risk_warnings.append("📈 الشهري صاعد — SELL عكس الترند")
    elif monthly_bias == "BEAR" and final == "BUY":
        risk_warnings.append("📉 الشهري هابط — BUY عكس الترند")
    if weekly_trend == "BULL" and final == "SELL":
        risk_warnings.append("📈 الويكلي صاعد — SELL عكس الترند")
    elif weekly_trend == "BEAR" and final == "BUY":
        risk_warnings.append("📉 الويكلي هابط — BUY عكس الترند")
    if divergence == "BEARISH" and final == "BUY":
        risk_warnings.append("⚠️ RSI Divergence معاكس للاتجاه")
    elif divergence == "BULLISH" and final == "SELL":
        risk_warnings.append("⚠️ RSI Divergence معاكس للاتجاه")
    is_counter_trend = (final=="BUY" and weekly_trend=="BEAR") or \
                       (final=="SELL" and weekly_trend=="BULL")
    if is_counter_trend:
        risk_warnings.append("⚠️ صفقة عكس الترند الأسبوعي — خذ TP1 وTP2 فقط")
        if final == "BUY":
            tp3 = round(tp2 + abs(tp2-tp1)*0.5, 2)
        else:
            tp3 = round(tp2 - abs(tp1-tp2)*0.5, 2)

    warn_count = len(risk_warnings)
    if warn_count == 0:   overall_risk = "🟢 منخفضة"
    elif warn_count <= 2: overall_risk = "🟡 متوسطة"
    else:                 overall_risk = "🔴 عالية"

    return {
        "final": final, "asset": asset,
        "risk_warnings": risk_warnings, "overall_risk": overall_risk,
        "weekly_trend": weekly_trend, "regime": regime, "regime_strength": regime_strength,
        "monthly_bias": monthly_bias, "divergence": divergence,
        "session": session, "session_score": session_score,
        "bull_obs": bull_obs, "bear_obs": bear_obs,
        "buy_liq": buy_liq, "sell_liq": sell_liq,
        "confluence_txt": conf_txt, "base_conf": base_conf,
        "price": price, "entry_price": entry_price, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": atr,
        "risk_pct": risk, "risk_label": rl, "risk_msg": rm,
        "frame_lines": frame_lines, "rsi": main["rsi"],
        "support": main["support"], "resistance": main["resistance"],
        "macd_bull": main["macd_bull"], "ema_bull": main["ema_bull"],
        "ema_bear": main["ema_bear"], "bb_zone": main["bb_zone"],
        "fib_levels": fib_levels, "fib_ext": fib_ext, "key_fibs": key_fibs[:5],
        "nearest_fib": nearest_fib, "fib_key": fib_key,
        "swing_h": swing_h, "swing_l": swing_l,
        "leverage_ar": "10x — 15x\n⚠️ لا تتجاوز 15x للمبتدئين",
        "leverage_en": "10x — 15x\n⚠️ Max 15x for beginners",
        "tf_ar": "1 ساعة", "tf_en": "1 Hour",
        "hold_ar": "2 — 8 ساعات", "hold_en": "2 — 8 Hours",
    }


# ==================== بناء الرسائل ====================
def build_trade_msg(res, uid=0, auto=False):
    lang    = user_languages.get(uid, "ar")
    ai      = "₿" if res["asset"] == "BTC" else "🥇"
    an      = "BTC/USD"
    is_sell = res["final"] == "SELL"
    dir_emoji = "🔴" if is_sell else "🟢"
    dir_txt   = t(uid,"sell") if is_sell else t(uid,"buy")
    header    = t(uid,"auto_header") if auto else t(uid,"trade_header")
    trade_num = res.get("id","")
    num_str   = "  #"+str(trade_num) if trade_num else ""

    # ✅ FIX 4: entry_price فقط — لا fallback لـ nearest_fib
    entry_display = res.get("entry_price", res["price"])

    lines = [
        "╔══════════════════════════╗",
        "  "+ai+" "+an+"  "+dir_emoji+"  "+dir_txt+num_str,
        "  ⚡ "+header,
        "╚══════════════════════════╝",
        "",
        "💵 "+t(uid,"current_price")+"   $"+"{:,.2f}".format(res["price"]),
        "📍 "+t(uid,"entry")+"   $"+"{:,.2f}".format(entry_display),
        "📐 "+t(uid,"fib_entry")+"   Fib "+res["fib_key"]+"% ($"+"{:,.2f}".format(entry_display)+")",
        "",
        "━━━━  🎯 "+t(uid,"targets_section")+"  ━━━━",
        "  TP1  ›  $"+"{:,.2f}".format(res["tp1"]),
        "  TP2  ›  $"+"{:,.2f}".format(res["tp2"]),
        "  TP3  ›  $"+"{:,.2f}".format(res["tp3"]),
        "  🛑 "+t(uid,"sl")+"   ›  $"+"{:,.2f}".format(res["sl"]),
        "  ⚖️  "+t(uid,"rr")+":  1:"+str(res["rr"]),
        "",
        "━━━━  🔗 "+t(uid,"confluence")+"  ━━━━",
    ]

    wt = res.get("weekly_trend","NEUTRAL")
    is_counter = (res["final"]=="BUY" and wt=="BEAR") or (res["final"]=="SELL" and wt=="BULL")
    if is_counter:
        lines.append("  ⚠️ صفقة عكس الترند — أهداف قصيرة، SL ضيق")
    lines.append("  "+("📈" if wt=="BULL" else "📉" if wt=="BEAR" else "➡️")+" ويكلي: "+("صاعد" if wt=="BULL" else "هابط" if wt=="BEAR" else "محايد"))

    rg = res.get("regime","UNKNOWN")
    rg_map = {"TRENDING_UP":"📈 ترند صاعد","TRENDING_DOWN":"📉 ترند هابط","RANGING":"↔️ سوق جانبي","VOLATILE":"⚡ تقلب عالي","UNKNOWN":"❓"}
    lines.append("  "+rg_map.get(rg, rg))

    mb = res.get("monthly_bias","NEUTRAL")
    lines.append("  "+("📈 شهري: صاعد" if mb=="BULL" else "📉 شهري: هابط" if mb=="BEAR" else "➡️ شهري: محايد"))

    div = res.get("divergence","NONE")
    if div == "BEARISH": lines.append("  📉 RSI Divergence هابط ⚠️")
    elif div == "BULLISH": lines.append("  📈 RSI Divergence صاعد ✅")

    obs = res.get("bear_obs" if is_sell else "bull_obs", [])
    if obs:
        ob = obs[-1]
        lines.append("  "+("🔴 منطقة بيع قوية" if is_sell else "🟢 منطقة شراء قوية"))
        lines.append("     $"+"{:,.0f}".format(ob["low"])+" — $"+"{:,.0f}".format(ob["high"]))

    liq = res.get("sell_liq" if is_sell else "buy_liq", [])
    if liq:
        lines.append("  🎯 $"+"{:,.0f}".format(liq[0])+" — منطقة سيولة")
        lines.append("     ⚠️ قد ينعكس السوق عندها")

    for fl in res["frame_lines"]:
        lines.append("  "+fl)
    lines.append("  "+res["confluence_txt"])

    overall_risk = res.get("overall_risk", "🟡 متوسطة")
    risk_warnings = res.get("risk_warnings", [])
    lines += ["", "━━━━  ⚠️ تقييم المخاطر  ━━━━",
              "  مستوى الخطورة: " + overall_risk]
    for w in risk_warnings:
        lines.append("  " + w)

    lines += [
        "",
        "━━━━  📡 مناطق مهمة  ━━━━",
        "  🟢 دعم:       $"+"{:,.2f}".format(res["support"]),
        "  🔴 مقاومة:   $"+"{:,.2f}".format(res["resistance"]),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
        t(uid,"footer"),
    ]
    return "\n".join(lines)


def build_update_msg(trade, current_price, update_type, uid=0):
    dir_txt = t(uid,"buy") if trade["direction"] == "BUY" else t(uid,"sell")
    lines = [
        "╔══════════════════════════╗",
        "  🔄 ₿ BTC/USD  •  "+t(uid,"update_header"),
        "╚══════════════════════════╝",
        "",
        "  "+t(uid,"direction")+":      "+dir_txt,
        "  "+t(uid,"entry")+":          $"+"{:,.2f}".format(trade["entry"]),
        "  "+t(uid,"current_price")+":  $"+"{:,.2f}".format(current_price),
        "",
        "  "+update_type,
        "",
        "━━━━  🎯 "+t(uid,"targets_section")+"  ━━━━",
        "  TP1  ›  $"+"{:,.2f}".format(trade["tp1"]),
        "  TP2  ›  $"+"{:,.2f}".format(trade["tp2"]),
        "  TP3  ›  $"+"{:,.2f}".format(trade["tp3"]),
        "  🛑 SL  ›  $"+"{:,.2f}".format(trade["sl"]),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
        t(uid,"footer"),
    ]
    return "\n".join(lines)


def build_analysis_msg(res, uid=0):
    ai = "₿" if res["asset"] == "BTC" else "🥇"
    an = "BTC/USD"
    if res["final"] == "BUY" and res["base_conf"] > 60:
        trend = t(uid,"trend_bull"); summary = t(uid,"summary_bull")
    elif res["final"] == "SELL" and res["base_conf"] > 60:
        trend = t(uid,"trend_bear"); summary = t(uid,"summary_bear")
    else:
        trend = t(uid,"trend_neutral"); summary = t(uid,"summary_neutral")
    rsi      = res["rsi"]
    rsi_txt  = t(uid,"rsi_oversold") if rsi < 30 else t(uid,"rsi_overbought") if rsi > 70 else t(uid,"rsi_neutral")
    macd_txt = t(uid,"macd_bull") if res["macd_bull"] else t(uid,"macd_bear")
    ema_txt  = t(uid,"ema_bull") if res["ema_bull"] else t(uid,"ema_bear") if res["ema_bear"] else t(uid,"ema_mixed")
    bb_txt   = t(uid,"bb_low") if res["bb_zone"]=="low" else t(uid,"bb_high") if res["bb_zone"]=="high" else t(uid,"bb_mid")
    lines = [
        "╔══════════════════════════╗",
        "  "+ai+" "+an+"  |  "+t(uid,"analysis_header"),
        "╚══════════════════════════╝",
        "",
        "  "+trend,
        "  💵 "+t(uid,"entry")+":         $"+"{:,.2f}".format(res["price"]),
        "  🟢 "+t(uid,"support")+":      $"+"{:,.2f}".format(res["support"]),
        "  🔴 "+t(uid,"resistance")+":   $"+"{:,.2f}".format(res["resistance"]),
        "",
        "━━━━  📐 "+t(uid,"fib_section")+"  ━━━━",
    ]
    for f in res.get("key_fibs", []):
        lines.append("  "+f)
    lines += ["", "━━━━  🔗 "+t(uid,"confluence")+"  ━━━━"]
    for fl in res.get("frame_lines", []):
        lines.append("  "+fl)
    lines += [
        "",
        "━━━━  📊 "+t(uid,"indicators_section")+"  ━━━━",
        "  RSI ("+str(rsi)+"):  "+rsi_txt,
        "  "+macd_txt, "  "+ema_txt, "  "+bb_txt,
        "",
        "  "+summary,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
        t(uid,"footer"),
    ]
    return "\n".join(lines)


# ==================== لوحات المفاتيح ====================
def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_btc"),          callback_data="trade_BTC")],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"), callback_data="analysis_BTC")],
        [InlineKeyboardButton(t(uid,"btn_prices"),  callback_data="prices"),
         InlineKeyboardButton(t(uid,"btn_trades"),  callback_data="open_trades")],
        [InlineKeyboardButton(t(uid,"btn_stats"),   callback_data="stats"),
         InlineKeyboardButton(t(uid,"btn_about"),   callback_data="about")],
        [InlineKeyboardButton(t(uid,"btn_lang"),    callback_data="change_lang")],
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data="lang_ar"),
        InlineKeyboardButton("English", callback_data="lang_en"),
    ]])

def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ أغلق القديمة وافتح جديدة", callback_data="confirm_replace_yes")],
        [InlineKeyboardButton("➕ خلي القديمة وافتح جديدة أيضاً", callback_data="confirm_add_new")],
        [InlineKeyboardButton("❌ خلي القديمة فقط", callback_data="confirm_replace_no")],
    ])


# ==================== هاندلرز ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        await update.message.reply_text("⛔ هذا البوت خاص"); return
    if uid not in user_languages:
        await update.message.reply_text("🐎 Abu Mahra Bot\n\nاختر لغتك / Choose your language:", reply_markup=lang_keyboard())
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
            current_price_check = get_btc_price()
            if current_price_check:
                early_similar = next((
                    tr for tr in active_trades
                    if tr["asset"] == asset and
                    abs(tr["entry"] - current_price_check) < 0.5 * tr.get("atr", current_price_check * 0.015)
                ), None)
                if early_similar:
                    await query.message.reply_text(
                        "⚠️ نفس الفرصة موجودة بالفعل\n"
                        "دخول قائم: $"+"{:,.2f}".format(early_similar["entry"])+"\n"
                        "السعر الحالي قريب — لا داعي لصفقة جديدة")
                    return

            keys_to_clear = [k for k in _cache if k.startswith(asset)]
            for k in keys_to_clear:
                _cache.pop(k, None)
            res = full_analysis(asset, uid)
            if not res:
                await query.message.reply_text("⚪ البيانات غير متوفرة الآن\nحاول بعد دقيقتين 🕐"); return
            if res["final"] == "NEUTRAL":
                fls = res.get("frame_lines", [])
                # Get majority from full_analysis (set for 2-frame case)
                # Fall back to counting frame_lines for 0/1 frame case
                majority = res.get("majority")
                if not majority:
                    buy_f  = sum(1 for f in fls if "BUY"  in f)
                    sell_f = sum(1 for f in fls if "SELL" in f)
                    majority = "BUY" if buy_f > sell_f else "SELL" if sell_f > buy_f else None

                parts = ["⚪ الفريمات غير متوافقة الآن", ""]
                if fls:
                    parts.append("📊 حالة الفريمات:")
                    for fl in fls:
                        parts.append(f"  {fl}")
                parts += [""]

                if majority:
                    dir_ar = "شراء BUY ⬆️" if majority == "BUY" else "بيع SELL ⬇️"
                    dir_e  = "🟢" if majority == "BUY" else "🔴"
                    is_two_frame = res.get("base_conf", 0) >= 65  # two-frame case
                    warn = "⚠️ فريمان من ثلاثة يدعمان الاتجاه — فريم واحد عكسهم" if is_two_frame else "⚠️ الأغلبية مع الاتجاه لكن لا توافق كامل"
                    parts.append(warn)
                    parts.append("تبي تدخل رغم الخلاف؟")
                    kb_override = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"{dir_e} أدخل {dir_ar} — الأغلبية",
                            callback_data=f"override_trade_{asset}_{majority}"
                        ),
                        InlineKeyboardButton("❌ إلغاء", callback_data="override_cancel"),
                    ]])
                    # Store res for override use
                    pending_trade_replace[uid] = {"override_res": res, "override_dir": majority}
                    await query.message.reply_text("\n".join(parts), reply_markup=kb_override)
                else:
                    parts.append("💡 انتظر إشارة أقوى 🕐")
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
                    "⚠️ نفس الفرصة موجودة بالفعل\n"
                    "دخول سابق: $"+"{:,.2f}".format(similar_recent["entry"])+"\n"
                    "لا داعي لصفقة جديدة")
                return

            trade_counter += 1
            res["id"] = trade_counter
            await query.message.reply_text(build_trade_msg(res, uid))

            dist_to_entry = abs(entry_p - market_p) / market_p * 100
            is_pending = dist_to_entry > 0.1
            frame_snapshot = {
                "buy": sum(1 for f in res.get("frame_lines", []) if "BUY" in f),
                "sell": sum(1 for f in res.get("frame_lines", []) if "SELL" in f),
            }
            new_trade = {
                "id": trade_counter, "asset": res["asset"],
                "direction": res["final"], "entry": entry_p,
                "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"], "tp3": res["tp3"],
                "atr": res["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res["sl"], "entry_fib": entry_p,
                "status": "pending" if is_pending else "active",
                "chat_id": query.message.chat_id, "open_time": gmt_now(),
                "frame_snapshot": frame_snapshot,
            }
            already_open = next((tr for tr in active_trades
                if tr["asset"] == new_trade["asset"] and tr["direction"] == new_trade["direction"]), None)
            opposite_open = next((tr for tr in active_trades
                if tr["asset"] == new_trade["asset"] and tr["direction"] != new_trade["direction"]), None)

            if already_open:
                dir_ar  = "شراء BUY" if new_trade["direction"] == "BUY" else "بيع SELL"
                ai_sym  = "₿ BTC" if new_trade["asset"] == "BTC" else "🥇 GOLD"
                pending_trade_replace[uid] = {"new": new_trade, "old": already_open, "res": res}
                await query.message.reply_text(
                    "⚠️ في صفقة مفتوحة بالفعل\n"+ai_sym+" — "+dir_ar+"\n\nتبي تغلق القديمة وتفتح صفقة جديدة؟",
                    reply_markup=confirm_keyboard())
            elif opposite_open:
                old_dir  = "شراء BUY ⬆️" if opposite_open["direction"] == "BUY" else "بيع SELL ⬇️"
                new_dir  = "بيع SELL ⬇️" if new_trade["direction"] == "SELL" else "شراء BUY ⬆️"
                ai_sym   = "₿ BTC" if new_trade["asset"] == "BTC" else "🥇 GOLD"
                pending_trade_replace[uid] = {"new": new_trade, "old": opposite_open, "res": res}
                await query.message.reply_text(
                    "⚠️ في صفقة "+old_dir+" قائمة\n"+ai_sym+"\n\n"
                    "الآن في إشارة "+new_dir+" — اتجاه معاكس",
                    reply_markup=confirm_keyboard())
            else:
                # ✅ FIX 1: lock عند التعديل على active_trades
                async with _trades_lock:
                    active_trades.append(new_trade)
                    if res["asset"] == "BTC":
                        active_btc_trade["data"] = new_trade
                    save_trades()
        except Exception as e:
            logger.error("Trade handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "confirm_replace_yes":
        pending = pending_trade_replace.pop(uid, None)
        if pending:
            old_tr = pending["old"]
            res_old = pending["res"]
            new_tr  = pending["new"]
            async with _trades_lock:
                if old_tr in active_trades:
                    active_trades.remove(old_tr)
                active_trades.append(new_tr)
                if new_tr["asset"] == "BTC":
                    active_btc_trade["data"] = new_tr
                save_trades()
            await query.message.reply_text(build_trade_msg(res_old, uid))
        else:
            await query.message.reply_text("⚠️ انتهت صلاحية الطلب، اطلب صفقة جديدة")

    elif data == "confirm_add_new":
        pending = pending_trade_replace.pop(uid, None)
        if pending:
            new_tr  = pending["new"]
            res_stored = pending["res"]
            async with _trades_lock:
                active_trades.append(new_tr)
                if new_tr["asset"] == "BTC":
                    active_btc_trade["data"] = new_tr
                save_trades()
            await query.message.reply_text(build_trade_msg(res_stored, uid))
        else:
            await query.message.reply_text("⚠️ انتهت صلاحية الطلب، اطلب صفقة جديدة")

    elif data == "confirm_replace_no":
        pending_trade_replace.pop(uid, None)
        await query.message.reply_text("👍 تم الإبقاء على الصفقة القديمة")

    elif data.startswith("analysis_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            keys_to_clear = [k for k in _cache if k.startswith(asset)]
            for k in keys_to_clear:
                _cache.pop(k, None)
            res = full_analysis(asset, uid)
            if not res:
                await query.message.reply_text("⚪ الفلاتر منعت التحليل أو البيانات غير متوفرة\n\nحاول بعد دقيقتين 🕐"); return
            await query.message.reply_text(build_analysis_msg(res, uid))
        except Exception as e:
            logger.error("Analysis handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "prices":
        try:
            d = get_prices()
            if not d:
                await query.message.reply_text(t(uid,"failed")); return
            btc = d.get("bitcoin", {})
            bp  = btc.get("usd", 0)
            bc  = btc.get("usd_24h_change", 0)
            lines = [
                "╔══════════════════════════╗",
                "  "+t(uid,"prices_title"),
                "╚══════════════════════════╝",
                "",
                "  ₿ BTC/USD:   $"+"{:,.0f}".format(bp),
                "  "+("📈" if bc > 0 else "📉")+" "+t(uid,"change_24h")+":  "+"{:+.2f}".format(bc)+"%",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                "🕐 "+t(uid,"updated_gmt")+":  "+gmt_now(),
            ]
            await query.message.reply_text("\n".join(lines))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == "open_trades":
        if not active_trades:
            await query.message.reply_text(t(uid,"no_open_trades"))
        else:
            rows = ["╔"+"═"*26+"╗", "  📋 الصفقات المفتوحة", "╚"+"═"*26+"╝", ""]
            current_price = get_btc_price()
            for tr in active_trades:
                de      = "🔴 بيع SELL" if tr["direction"]=="SELL" else "🟢 شراء BUY"
                ai2     = "₿" if tr["asset"]=="BTC" else "🥇"
                tp1_hit = "✅" if tr.get("tp1_hit") else "⏳"
                tp2_hit = "✅" if tr.get("tp2_hit") else "⏳"
                rows += [ai2+" #"+str(tr.get("id","?"))+"  "+de,
                         "  💵 دخول:  $"+"{:,.2f}".format(tr["entry"])]
                if current_price and tr["asset"] == "BTC":
                    rows.append("  📍 الحالي: $"+"{:,.2f}".format(current_price))
                rows += [tp1_hit+" TP1:  $"+"{:,.2f}".format(tr["tp1"]),
                         tp2_hit+" TP2:  $"+"{:,.2f}".format(tr["tp2"]),
                         "⏳ TP3:  $"+"{:,.2f}".format(tr["tp3"]),
                         "🛑 SL:   $"+"{:,.2f}".format(tr["sl"]),
                         "🕐 "+tr.get("open_time",""), ""]
            rows += ["━"*24, "🕐 "+gmt_now()]
            await query.message.reply_text("\n".join(rows))

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
            "╔"+"═"*26+"╗", "  📊 إحصائيات أبو مهرة", "╚"+"═"*26+"╝", "",
            "━━━━  📈 الصفقات المغلقة  ━━━━",
            "  إجمالي:      "+str(total_closed),
            "  🏆 رابحة:    "+str(wins),
            "  🟡 تعادل:    "+str(stats.get("breakeven", 0)),
            "  🛑 خاسرة:    "+str(losses), "",
            "  🎯 نسبة النجاح",
            "  "+bar_w+"  "+str(win_rate)+"%",
            "  ⚖️ متوسط RR:  1:"+str(avg_rr), "",
        ]
        if active_trades:
            lines.append("━━━━  🔓 الصفقات القائمة  ━━━━")
            for tr in active_trades:
                ai2  = "₿" if tr["asset"]=="BTC" else "🥇"
                dire = "🔴 SELL" if tr["direction"]=="SELL" else "🟢 BUY"
                if tr.get("status") == "pending":
                    status = "⏳ انتظار الدخول عند $"+"{:,.2f}".format(tr["entry"])
                elif tr.get("tp2_hit"):
                    status = "✅✅ TP2 تم"
                elif tr.get("tp1_hit"):
                    status = "✅ TP1 تم"
                else:
                    status = "🟢 نشطة — لم يصل أي هدف بعد"
                lines += [
                    ai2+" #"+str(tr.get("id","?"))+"  "+dire,
                    "  💵 دخول:  $"+"{:,.2f}".format(tr["entry"]),
                    "  "+status,
                    "  TP1: $"+"{:,.2f}".format(tr["tp1"])+"  TP2: $"+"{:,.2f}".format(tr["tp2"]),
                    "  TP3: $"+"{:,.2f}".format(tr["tp3"])+"  SL: $"+"{:,.2f}".format(tr["sl"]),
                    "",
                ]
        else:
            lines += ["━━━━  🔓 لا توجد صفقات قائمة  ━━━━", ""]
        lines += ["━"*24, "🕐 "+gmt_now()]
        await query.message.reply_text("\n".join(lines))

    elif data.startswith("keep_pending_"):
        trade_id = int(data.split("_")[2])
        pending_trade_replace.pop(trade_id, None)
        await query.message.reply_text("✅ الصفقة #"+str(trade_id)+" لا تزال قائمة")

    elif data.startswith("cancel_pending_"):
        trade_id = int(data.split("_")[2])
        pending_trade_replace.pop(trade_id, None)
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            async with _trades_lock:
                active_trades.remove(trade)
                save_trades()
        await query.message.reply_text("❌ الصفقة #"+str(trade_id)+" ألغيت")

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
                "buy": sum(1 for f in res_sig.get("frame_lines", []) if "BUY" in f),
                "sell": sum(1 for f in res_sig.get("frame_lines", []) if "SELL" in f),
            }
            new_trade = {
                "id": sig_id, "asset": "BTC",
                "direction": res_sig["final"], "entry": entry_p,
                "sl": res_sig["sl"], "tp1": res_sig["tp1"],
                "tp2": res_sig["tp2"], "tp3": res_sig["tp3"],
                "atr": res_sig["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res_sig["sl"], "entry_fib": entry_p,
                "status": "pending" if is_pending else "active",
                "chat_id": chat_id_s, "open_time": gmt_now(),
                "frame_snapshot": sig_frame_snapshot,
                "entry_update_sent": False,
            }
            async with _trades_lock:
                active_trades.append(new_trade)
                if res_sig["asset"] == "BTC":
                    active_btc_trade["data"] = new_trade
                save_trades()
            status_txt = "⏳ انتظار الدخول عند $"+"{:,.2f}".format(entry_p) if is_pending else "🟢 نشطة"
            confirm_msg = "✅ #"+str(sig_id)+" تم تفعيل الصفقة\n"+status_txt
            for cid in chat_ids_s:
                try:
                    await context.bot.send_message(chat_id=cid, text=confirm_msg)
                except: pass
        else:
            await query.message.reply_text("⚠️ انتهت صلاحية الإشارة")

    elif data.startswith("ignore_signal_"):
        sig_id = int(data.split("_")[2])
        pending_signals.pop(sig_id, None)

    elif data.startswith("update_entry_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade and "pending_update" in trade:
            upd = trade["pending_update"]
            old_entry = trade["entry"]
            async with _trades_lock:
                trade["entry"]  = upd["entry"]
                trade["sl"]     = upd["sl"]
                trade["tp1"]    = upd["tp1"]
                trade["tp2"]    = upd["tp2"]
                trade["tp3"]    = upd["tp3"]
                trade["orig_sl"]= upd["sl"]
                trade.pop("pending_update", None)
                trade["entry_update_sent"] = False
                save_trades()
            await query.message.reply_text(
                "✅ #"+str(trade_id)+" تم تحديث مستوى الدخول\n"
                "القديم: $"+"{:,.2f}".format(old_entry)+" → الجديد: $"+"{:,.2f}".format(upd["entry"]))
        else:
            await query.message.reply_text("⚠️ انتهت صلاحية التحديث")

    elif data.startswith("ignore_entry_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            trade.pop("pending_update", None)
            trade["entry_update_sent"] = False

    elif data.startswith("keep_active_"):
        pass  # صمت — المستخدم قرر يبقيها

    elif data.startswith("close_active_"):
        trade_id = int(data.split("_")[2])
        trade = next((tr for tr in active_trades if tr.get("id") == trade_id), None)
        if trade:
            async with _trades_lock:
                active_trades.remove(trade)
                save_trades()
            await query.message.reply_text("✅ #"+str(trade_id)+" تم إغلاق الصفقة من القائمة")

    elif data == "override_cancel":
        pending_trade_replace.pop(uid, None)
        await query.message.reply_text("👍 تم الإلغاء — انتظر إشارة أقوى")
        return

    elif data.startswith("override_trade_"):
        # Format: override_trade_{asset}_{direction}
        parts_d = data.split("_")
        asset_ov = parts_d[2]
        forced_dir = parts_d[3]  # BUY or SELL
        stored = pending_trade_replace.pop(uid, {})
        res_ov = stored.get("override_res")

        if not res_ov:
            await query.message.reply_text("⚠️ انتهت صلاحية الطلب، اطلب صفقة جديدة")
            return

        await query.message.reply_text("⏳ جاري تحضير الصفقة...")
        try:
            clear_asset_cache(asset_ov)
            res_fresh = full_analysis(asset_ov, uid)
            res_use = res_fresh if res_fresh else res_ov
            entry_p  = res_use.get("entry_price", res_use["price"])
            avg_atr  = res_use["atr"]

            similar = next((tr for tr in active_trades
                            if tr["asset"] == asset_ov and tr["direction"] == forced_dir
                            and abs(tr["entry"] - entry_p) < 0.5 * avg_atr), None)
            if similar:
                await query.message.reply_text(
                    f"⚠️ صفقة مشابهة موجودة بالفعل\nدخول: ${similar['entry']:,.2f}")
                return

            trade_counter += 1
            res_use["id"] = trade_counter
            res_use["forced"] = True  # mark as override trade

            # Build trade message with forced warning
            trade_msg = build_trade_msg(res_use, uid)
            fl_now = res_use.get("frame_lines", [])
            conflict_frames = [f for f in fl_now if
                               ("BUY" in f and forced_dir == "SELL") or
                               ("SELL" in f and forced_dir == "BUY")]
            warning_lines = [
                "",
                "━━━━  ⚠️ تنبيه — صفقة بتجاوز الفلاتر  ━━━━",
                f"  فريم الساعة يعاكس الاتجاه",
                "  استخدم حجم أصغر من المعتاد",
                "  المخاطرة أعلى من الصفقة العادية",
            ]
            trade_msg = trade_msg + "\n" + "\n".join(warning_lines)
            await query.message.reply_text(trade_msg)

            is_p = abs(entry_p - res_use["price"]) / res_use["price"] * 100 > 0.1
            snap = {
                "buy":  sum(1 for f in fl_now if "BUY"  in f),
                "sell": sum(1 for f in fl_now if "SELL" in f),
            }
            nt = {
                "id": trade_counter, "asset": asset_ov,
                "direction": forced_dir, "entry": entry_p,
                "sl": res_use["sl"], "tp1": res_use["tp1"],
                "tp2": res_use["tp2"], "tp3": res_use["tp3"],
                "atr": res_use["atr"], "tp1_hit": False, "tp2_hit": False,
                "orig_sl": res_use["sl"],
                "status": "pending" if is_p else "active",
                "chat_id": query.message.chat_id, "open_time": gmt_now(),
                "frame_snapshot": snap, "entry_update_sent": False,
                "entry_alert_sent": False, "last_news_event": "",
                "last_frame_alert": "", "last_active_alert": "",
                "forced": True,  # flag for health reports
            }
            async with _trades_lock:
                active_trades.append(nt)
                if asset_ov == "BTC": active_btc_trade["data"] = nt
                save_trades()
        except Exception as e:
            logger.error(f"Override trade: {e}")
            await query.message.reply_text(t(uid, "error") + str(e))
        return

    elif data == "about":
        await query.message.reply_text(t(uid,"about_text"))


# ══════════════════════════════════════════════════════
#  PENDING TRADE HEALTH REPORT
# ══════════════════════════════════════════════════════
def _build_health_report(trade: dict, res: dict, current: float):
    """
    Returns (msg_text, n_cancel_reasons).
    Called every 15-min cycle for both pending and active trades.
    Gives the user a clear, actionable assessment.
    """
    tid   = trade.get("id", "?")
    entry = trade["entry"]
    dire  = trade["direction"]
    dist  = abs(current - entry) / entry * 100
    dist_dir = "فوق" if current > entry else "تحت"

    frame_lines = res.get("frame_lines", [])
    buy_f  = sum(1 for f in frame_lines if "BUY"  in f)
    sell_f = sum(1 for f in frame_lines if "SELL" in f)
    match  = buy_f if dire == "BUY" else sell_f
    total  = buy_f + sell_f
    align  = round(match / total * 100) if total else 0

    wt  = res.get("weekly_trend", "NEUTRAL")
    mb  = res.get("monthly_bias", "NEUTRAL")
    rg  = res.get("regime", "UNKNOWN")
    div = res.get("divergence", "NONE")

    cancel_r = []
    hold_r   = []

    # ── Frame alignment ──
    if match == 0:
        cancel_r.append("❌ جميع الفريمات انعكست — لا دعم للاتجاه")
    elif match == total:
        hold_r.append(f"✅ {match}/{total} فريمات تدعم الاتجاه بالكامل ({align}%)")
    else:
        hold_r.append(f"🟡 {match}/{total} فريمات لا تزال مع الاتجاه ({align}%)")

    # ── Monthly bias ──
    if (dire == "BUY" and mb == "BEAR") or (dire == "SELL" and mb == "BULL"):
        cancel_r.append("📉 الاتجاه الشهري معاكس للصفقة")
    elif (dire == "BUY" and mb == "BULL") or (dire == "SELL" and mb == "BEAR"):
        hold_r.append("📈 الاتجاه الشهري يدعم الصفقة")

    # ── Weekly trend ──
    if (dire == "BUY" and wt == "BEAR") or (dire == "SELL" and wt == "BULL"):
        cancel_r.append("📉 الاتجاه الأسبوعي معاكس — صفقة عكس الترند")
    elif (dire == "BUY" and wt == "BULL") or (dire == "SELL" and wt == "BEAR"):
        hold_r.append("📈 الاتجاه الأسبوعي يدعم الصفقة")

    # ── Market regime ──
    _rg_ar = {
        "TRENDING_UP":   "📈 ترند صاعد",
        "TRENDING_DOWN": "📉 ترند هابط",
        "RANGING":       "↔️ سوق جانبي",
        "VOLATILE":      "⚡ تقلب عالي",
        "UNKNOWN":       "❓",
    }
    if rg == "VOLATILE":
        cancel_r.append("⚡ السوق في تقلب عالٍ — الدخول محفوف بمخاطر")
    elif rg in ("TRENDING_UP", "TRENDING_DOWN"):
        match_trend = (dire == "BUY" and rg == "TRENDING_UP") or \
                      (dire == "SELL" and rg == "TRENDING_DOWN")
        if match_trend:
            hold_r.append(f"📊 الـ Regime يدعم الاتجاه ({_rg_ar.get(rg, '')})")
        else:
            cancel_r.append(f"📊 الـ Regime عكس الاتجاه ({_rg_ar.get(rg, '')})")
    elif rg == "RANGING":
        cancel_r.append("↔️ سوق جانبي — الأهداف قد لا تُكتمل")

    # ── RSI Divergence ──
    if (div == "BEARISH" and dire == "BUY") or (div == "BULLISH" and dire == "SELL"):
        cancel_r.append("⚠️ RSI Divergence يعاكس الصفقة")
    elif (div == "BULLISH" and dire == "BUY") or (div == "BEARISH" and dire == "SELL"):
        hold_r.append("📈 RSI Divergence يدعم الاتجاه")

    # ── Verdict ──
    nc = len(cancel_r)
    nh = len(hold_r)
    if nc >= 2:
        verdict = "🔴 توصية: إلغاء — تدهورت الظروف بشكل واضح"
    elif nc == 1 and nh == 0:
        verdict = "🟡 توصية: مراجعة — ظرف واحد ضد الصفقة بدون دعم"
    elif nh >= 2 and nc == 0:
        verdict = "🟢 توصية: الإبقاء — الظروف مواتية"
    else:
        verdict = "🟡 توصية: مراقبة — وضع مختلط"

    forced_note = "  ⚠️ صُفقة بتجاوز الفلاتر — فريم الساعة كان عكس الاتجاه عند الفتح\n" if trade.get("forced") else ""
    st = "⏳ معلقة" if trade.get("status") == "pending" else "🟢 نشطة"
    lines = [
        "╔══════════════════════════╗",
        f"  📋 تقرير صحة الصفقة #{tid}  ({st})",
        "╚══════════════════════════╝",
        "",
        f"  {'🟢 BUY ⬆️' if dire == 'BUY' else '🔴 SELL ⬇️'}",
        forced_note if forced_note else "",
        f"  الدخول:       ${entry:,.2f}",
        f"  السعر الحالي: ${current:,.2f}",
        f"  المسافة:      {dist:.2f}% {dist_dir} الدخول",
        "",
        "━━━━  🔗 توافق الفريمات  ━━━━",
    ]
    for fl in frame_lines:
        lines.append(f"  {fl}")
    lines += ["", "━━━━  📊 تقييم الظروف  ━━━━"]
    for h in hold_r:
        lines.append(f"  {h}")
    for c in cancel_r:
        lines.append(f"  {c}")
    lines += [
        "",
        f"  {verdict}",
        "",
        f"  SL:  ${trade['sl']:,.2f}   TP1: ${trade['tp1']:,.2f}",
        f"  TP2: ${trade['tp2']:,.2f}  TP3: ${trade['tp3']:,.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {gmt_now()}",
        "⚠️ للأغراض التعليمية فقط",
    ]
    return "\n".join(lines), nc


# ══════════════════════════════════════════════════════
#  JOB: check_pending_trades  (every 15 min)
# ══════════════════════════════════════════════════════
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

    cur = get_btc_price()
    res = None
    try:
        res = full_analysis("BTC", 0)
    except Exception as e:
        logger.error(f"check_pending_trades analysis: {e}")

    if not res or not cur:
        return

    frame_lines = res.get("frame_lines", [])
    buy_f  = sum(1 for f in frame_lines if "BUY"  in f)
    sell_f = sum(1 for f in frame_lines if "SELL" in f)
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
                        async with _trades_lock:
                            if trade in active_trades:
                                active_trades.remove(trade)
                            save_trades()
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"⏰ #{tid} الصفقة المعلقة ألغيت تلقائياً\n"
                                 f"مضى عليها أكثر من {PENDING_MAX_AGE} ساعة دون تفعيل\n"
                                 f"أعد الطلب إذا كانت الفرصة لا تزال قائمة")
                        continue
                except Exception:
                    pass

            # ── 2. Full reversal: all frames flipped ──
            if total_f > 0 and opposite == total_f:
                alert_key = f"flip_{buy_f}_{sell_f}"
                if trade.get("last_frame_alert") != alert_key:
                    trade["last_frame_alert"] = alert_key
                    opp_dir = "SELL ⬇️" if dire == "BUY" else "BUY ⬆️"
                    msg, nc = _build_health_report(trade, res, cur)
                    if status == "pending":
                        async with _trades_lock:
                            if trade in active_trades:
                                active_trades.remove(trade)
                            save_trades()
                        await context.bot.send_message(chat_id=chat_id,
                            text=msg + f"\n\n❌ تم إلغاء الصفقة تلقائياً\n"
                                       f"جميع الفريمات تحولت إلى {opp_dir}")
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ أبقِ الصفقة",     callback_data=f"keep_active_{tid}"),
                            InlineKeyboardButton("❌ أغلق من القائمة", callback_data=f"close_active_{tid}"),
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
                    msg, nc = _build_health_report(trade, res, cur)

                    if status == "pending":
                        if nc >= 2:
                            # Auto-cancel: 2+ strong reasons against
                            async with _trades_lock:
                                if trade in active_trades:
                                    active_trades.remove(trade)
                                save_trades()
                            await context.bot.send_message(chat_id=chat_id,
                                text=msg + "\n\n❌ الصفقة ألغيت تلقائياً — الظروف تدهورت")
                        else:
                            kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton("✅ أبقِ الصفقة", callback_data=f"keep_pending_{tid}"),
                                InlineKeyboardButton("❌ ألغِ الصفقة", callback_data=f"cancel_pending_{tid}"),
                            ]])
                            await context.bot.send_message(chat_id=chat_id,
                                text=msg, reply_markup=kb)
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ أبقِ الصفقة",     callback_data=f"keep_active_{tid}"),
                            InlineKeyboardButton("❌ أغلق من القائمة", callback_data=f"close_active_{tid}"),
                        ]])
                        await context.bot.send_message(chat_id=chat_id,
                            text=msg, reply_markup=kb)

        except Exception as e:
            logger.error(f"check_pending_trades trade #{tid}: {e}")


# ==================== مراقبة BTC ====================
async def _check_auto_signal(context):
    """Auto-signal: fires when RSI extreme + at Fib level + 3-frame confluence."""
    n = now_ts()
    if (n - last_signal_time.get("BTC", 0)) < SPAM_COOLDOWN:
        return
    try:
        df_q = get_data("BTC", days=3, interval="hourly")
        if df_q is None or len(df_q) < 20:
            return
        dq     = calc_indicators(df_q.tail(50).copy())
        lq     = dq.iloc[-1]
        price_q= float(lq["Close"])
        rsi_q  = safe(lq["RSI"], 50)
        fib_q, *_ = calculate_fibonacci(df_q)

        if not (rsi_q < 35 or rsi_q > 65): return
        if not any(abs(price_q - v) / price_q * 100 < 0.5 for v in fib_q.values()): return

        no_buy  = not any(tr["asset"]=="BTC" and tr["direction"]=="BUY"  for tr in active_trades)
        no_sell = not any(tr["asset"]=="BTC" and tr["direction"]=="SELL" for tr in active_trades)

        res = full_analysis("BTC", 0)
        if not res or res["final"] == "NEUTRAL" or res["base_conf"] < MIN_CONFIDENCE:
            return

        fl     = res.get("frame_lines", [])
        buy_f  = sum(1 for f in fl if "BUY"  in f)
        sell_f = sum(1 for f in fl if "SELL" in f)
        three  = buy_f == 3 or sell_f == 3
        dir_ok = (res["final"]=="BUY" and no_buy) or (res["final"]=="SELL" and no_sell)
        ep     = res["entry_price"]
        sig_atr= res.get("atr", ep * 0.015)
        dup    = any(tr["asset"]=="BTC" and tr["direction"]==res["final"]
                     and abs(tr["entry"] - ep) < 0.5 * sig_atr
                     for tr in active_trades)

        if not (three and dir_ok and not dup):
            return

        global trade_counter
        last_signal_time["BTC"] = n
        trade_counter += 1
        res["id"] = trade_counter

        dir_e   = "🔴" if res["final"]=="SELL" else "🟢"
        dir_t   = "بيع SELL ⬇️" if res["final"]=="SELL" else "شراء BUY ⬆️"
        fl_txt  = "\n".join(f"  {f}" for f in fl)
        ev_warn = ""
        ev = get_upcoming_event(2)
        if ev:
            ev_warn = f"\n⚠️ {ev['event']} خلال {_mins_txt(ev['mins_left'])}"

        sig_msg = (
            f"🔔 إشارة تلقائية — ₿ BTC/USD\n"
            f"{dir_e} {dir_t}\n\n"
            f"💵 السعر: ${res['price']:,.2f}\n"
            f"📍 الدخول: ${ep:,.2f}\n"
            f"🛑 SL: ${res['sl']:,.2f}\n"
            f"TP1: ${res['tp1']:,.2f}  TP2: ${res['tp2']:,.2f}  TP3: ${res['tp3']:,.2f}\n"
            f"⚖️ RR: 1:{res['rr']}\n\n"
            f"{fl_txt}{ev_warn}\n\n"
            f"ثقة الإشارة: {res['base_conf']}%  •  مخاطرة: {res.get('overall_risk','')}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ فعّل الصفقة", callback_data=f"activate_signal_{trade_counter}"),
            InlineKeyboardButton("❌ تجاهل",       callback_data=f"ignore_signal_{trade_counter}"),
        ]])
        pending_signals[trade_counter] = {
            "res": res, "entry_p": ep, "timestamp": n,
            "price": res["price"], "chat_ids": [],
        }
        for uid in ALLOWED_USERS:
            try:
                await context.bot.send_message(chat_id=uid, text=sig_msg, reply_markup=kb)
                pending_signals[trade_counter]["chat_ids"].append(uid)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Auto-signal: {e}")


async def _expire_pending_signals(context):
    """Expire signals that are stale, price-moved, or direction-changed."""
    if not pending_signals:
        return
    try:
        n   = now_ts()
        cur = get_btc_price()
        fresh = None
        try: fresh = full_analysis("BTC", 0)
        except Exception: pass

        to_exp = []
        for sid, sig in list(pending_signals.items()):
            expired = False; reason = ""
            if cur and abs(cur - sig["price"]) / sig["price"] * 100 > PRICE_EXPIRY_PCT:
                expired = True; reason = "السعر تحرك بعيداً عن نقطة الدخول"
            elif fresh and fresh["final"] != sig["res"]["final"]:
                expired = True; reason = "الفريمات تغيرت — الفرصة انتهت"
            elif n - sig["timestamp"] > SIGNAL_EXPIRY:
                expired = True
            if expired:
                to_exp.append(sid)
                msg = f"⏰ #{sid} انتهت صلاحية الإشارة"
                if reason: msg += f"\n{reason}"
                for cid in sig.get("chat_ids", list(ALLOWED_USERS)):
                    try: await context.bot.send_message(chat_id=cid, text=msg)
                    except Exception: pass
        for sid in to_exp:
            pending_signals.pop(sid, None)
    except Exception as e:
        logger.error(f"Expire signals: {e}")


async def _economic_alert_no_trades(context):
    """Alert about upcoming high-impact event when no trades are open."""
    if active_trades:
        return
    try:
        ev30 = get_upcoming_event(0.5)
        if not ev30: return
        ek = _event_key(ev30)
        if _news_notified.get(ek): return
        _news_notified[ek] = True
        nm = (f"📰 تنبيه اقتصادي مهم\n"
              f"{ev30['event']} — خلال {_mins_txt(ev30['mins_left'])}\n"
              f"تأثير متوقع: 🔴 عالي\n"
              f"تجنب فتح صفقات جديدة حتى مرور الخبر")
        for uid in ALLOWED_USERS:
            try: await context.bot.send_message(chat_id=uid, text=nm)
            except Exception: pass
    except Exception as e:
        logger.warning(f"Econ alert: {e}")


async def _monitor_active_trades(context):
    """Monitor SL/TP on all active trades, send updates, remove closed ones."""
    if not active_trades:
        return
    cur = get_btc_price()
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
                arrived = (direction=="BUY"  and cur <= entry*1.001) or                           (direction=="SELL" and cur >= entry*0.999)
                if arrived:
                    try:
                        fresh = full_analysis(trade["asset"], 0)
                        if fresh is None:
                            trade["status"] = "active"
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🟢 #{trade_id} السعر وصل للدخول — الصفقة نشطة ✅")
                        elif fresh["final"] != direction:
                            to_remove.append(trade)
                            nd = "BUY ⬆️" if fresh["final"]=="BUY" else "SELL ⬇️"
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"⚠️ #{trade_id} الصفقة ألغيت عند الدخول\nالاتجاه تغير إلى {nd}")
                        else:
                            trade.update({"status":"active","sl":fresh["sl"],
                                          "tp1":fresh["tp1"],"tp2":fresh["tp2"],
                                          "tp3":fresh["tp3"],"atr":fresh["atr"],
                                          "orig_sl":fresh["sl"]})
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🟢 #{trade_id} الصفقة نشطة — أرقام محدّثة ✅\n"
                                     f"SL: ${fresh['sl']:,.2f}\n"
                                     f"TP1: ${fresh['tp1']:,.2f}  TP2: ${fresh['tp2']:,.2f}  TP3: ${fresh['tp3']:,.2f}")
                            async with _trades_lock:
                                save_trades()
                    except Exception as e:
                        logger.error(f"Pending arrival: {e}")
                        trade["status"] = "active"
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"🟢 #{trade_id} الصفقة نشطة ✅")
                else:
                    # SL hit before entry
                    sl_pre = (direction=="BUY" and cur <= sl) or (direction=="SELL" and cur >= sl)
                    if sl_pre:
                        to_remove.append(trade)
                        await context.bot.send_message(chat_id=chat_id,
                            text=f"⚠️ #{trade_id} وقف الخسارة تجاوز قبل الدخول\n"
                                 f"SL: ${sl:,.2f}  •  السعر: ${cur:,.2f}\nألغيت تلقائياً")
                    else:
                        dist_pct = abs(cur - entry) / entry * 100
                        if dist_pct <= 0.5 and not trade.get("entry_alert_sent"):
                            trade["entry_alert_sent"] = True
                            await context.bot.send_message(chat_id=chat_id,
                                text=f"🎯 #{trade_id} السعر اقترب من الدخول\n"
                                     f"${entry:,.2f}  •  السعر: ${cur:,.2f}  •  {dist_pct:.2f}%")
                        # News alert
                        try:
                            ev = get_upcoming_event(2)
                            if ev:
                                ek = ev.get("event","")
                                if ek != trade.get("last_news_event",""):
                                    trade["last_news_event"] = ek
                                    await context.bot.send_message(chat_id=chat_id,
                                        text=f"⚠️ #{trade_id} خبر مهم قادم\n"
                                             f"{ek} خلال {_mins_txt(ev['mins_left'])}\n"
                                             f"تأثير: 🔴 عالي — كن حذراً")
                        except Exception: pass
                        # Entry-passed update
                        ep_passed = (direction=="SELL" and cur < entry*0.99) or                                     (direction=="BUY"  and cur > entry*1.01)
                        if ep_passed and not trade.get("entry_update_sent"):
                            try:
                                fe = full_analysis(trade["asset"], 0)
                                if fe and fe["final"] == direction:
                                    ne = fe.get("entry_price", fe["price"])
                                    if abs(ne - entry) / entry * 100 > 0.1:
                                        trade["entry_update_sent"] = True
                                        trade["pending_update"] = {
                                            "entry":ne,"sl":fe["sl"],"tp1":fe["tp1"],
                                            "tp2":fe["tp2"],"tp3":fe["tp3"],
                                        }
                                        kb_upd = InlineKeyboardMarkup([[
                                            InlineKeyboardButton("✅ حدّث الصفقة", callback_data=f"update_entry_{trade_id}"),
                                            InlineKeyboardButton("❌ تجاهل",        callback_data=f"ignore_entry_{trade_id}"),
                                        ]])
                                        await context.bot.send_message(chat_id=chat_id,
                                            text=f"📊 #{trade_id} تحديث مستوى الدخول\n"
                                                 f"القديم: ${entry:,.2f}  →  الجديد: ${ne:,.2f}\n"
                                                 f"SL: ${fe['sl']:,.2f}  TP1: ${fe['tp1']:,.2f}  TP2: ${fe['tp2']:,.2f}",
                                            reply_markup=kb_upd)
                            except Exception as e:
                                logger.warning(f"Entry update: {e}")
                        # Counter-move cancel
                        ctr = (direction=="SELL" and cur > entry*1.02) or                               (direction=="BUY"  and cur < entry*0.98)
                        if ctr:
                            try:
                                fc = full_analysis(trade["asset"], 0)
                                if fc and fc["final"] != direction:
                                    to_remove.append(trade)
                                    nd = "BUY ⬆️" if fc["final"]=="BUY" else "SELL ⬇️"
                                    moved = abs(cur-entry)/entry*100
                                    await context.bot.send_message(chat_id=chat_id,
                                        text=f"⚠️ #{trade_id} الصفقة ألغيت — عكس الاتجاه\n"
                                             f"السعر تحرك {moved:.1f}% ضد الدخول\nالفريمات: {nd}")
                            except Exception as e:
                                logger.warning(f"Counter-move: {e}")
                continue  # done with pending

            # ── Active: TP / SL logic ──
            if direction == "BUY":
                if cur >= tp3:
                    update_msg = f"🏆 #{trade_id} الهدف الثالث تحقق! مغلقة بنجاح 🎉"
                    record_trade_result(trade_id, "win", trade.get("rr",0), direction, _session); closed=True
                elif not trade["tp1_hit"] and cur >= tp1:
                    trade["tp1_hit"]=True; trade["sl"]=entry
                    update_msg = f"✅ #{trade_id} TP1 تحقق — SL انتقل للدخول ${entry:,.2f}"
                elif trade["tp1_hit"] and not trade["tp2_hit"] and cur >= tp2:
                    trade["tp2_hit"]=True
                    nsl = round(tp2-0.25*abs(tp1-tp2), 2); trade["sl"]=nsl
                    update_msg = f"✅✅ #{trade_id} TP2 تحقق — SL انتقل إلى ${nsl:,.2f}"
                elif cur <= trade["sl"]:
                    if trade.get("tp2_hit"):
                        rp = round(abs(tp2-entry)/abs(entry-trade.get("orig_sl",sl)),2) if abs(entry-trade.get("orig_sl",sl))>0 else 1.0
                        update_msg = f"✅ #{trade_id} SL عند TP2 — ربح جزئي 🎉"
                        record_trade_result(trade_id, "win", rp, direction, _session)
                    elif trade.get("tp1_hit"):
                        update_msg = f"🟡 #{trade_id} SL عند الدخول — تعادل"
                        record_trade_result(trade_id, "breakeven", 0, direction, _session)
                    else:
                        update_msg = f"🛑 #{trade_id} وقف الخسارة — مغلقة"
                        record_trade_result(trade_id, "loss", 0, direction, _session)
                    closed=True
                elif trade["tp1_hit"] and cur > tp1+0.5*atr:
                    nsl = round(cur-0.8*atr, 2)
                    if nsl > trade["sl"] and nsl-trade["sl"] >= atr:
                        trade["sl"]=nsl
                        update_msg = f"📊 #{trade_id} Trailing SL → ${nsl:,.2f}"
            else:  # SELL
                if cur <= tp3:
                    update_msg = f"🏆 #{trade_id} الهدف الثالث تحقق! مغلقة بنجاح 🎉"
                    record_trade_result(trade_id, "win", trade.get("rr",0), direction, _session); closed=True
                elif not trade["tp1_hit"] and cur <= tp1:
                    trade["tp1_hit"]=True; trade["sl"]=entry
                    update_msg = f"✅ #{trade_id} TP1 تحقق — SL انتقل للدخول ${entry:,.2f}"
                elif trade["tp1_hit"] and not trade["tp2_hit"] and cur <= tp2:
                    trade["tp2_hit"]=True
                    nsl = round(tp2+0.25*abs(tp1-tp2), 2); trade["sl"]=nsl
                    update_msg = f"✅✅ #{trade_id} TP2 تحقق — SL انتقل إلى ${nsl:,.2f}"
                elif cur >= trade["sl"]:
                    if trade.get("tp2_hit"):
                        rp = round(abs(tp2-entry)/abs(entry-trade.get("orig_sl",sl)),2) if abs(entry-trade.get("orig_sl",sl))>0 else 1.0
                        update_msg = f"✅ #{trade_id} SL عند TP2 — ربح جزئي 🎉"
                        record_trade_result(trade_id, "win", rp, direction, _session)
                    elif trade.get("tp1_hit"):
                        update_msg = f"🟡 #{trade_id} SL عند الدخول — تعادل"
                        record_trade_result(trade_id, "breakeven", 0, direction, _session)
                    else:
                        update_msg = f"🛑 #{trade_id} وقف الخسارة — مغلقة"
                        record_trade_result(trade_id, "loss", 0, direction, _session)
                    closed=True
                elif trade["tp1_hit"] and cur < tp1-0.5*atr:
                    nsl = round(cur+0.8*atr, 2)
                    if nsl < trade["sl"] and trade["sl"]-nsl >= atr:
                        trade["sl"]=nsl
                        update_msg = f"📊 #{trade_id} Trailing SL → ${nsl:,.2f}"

            if update_msg:
                await context.bot.send_message(chat_id=chat_id,
                    text=build_update_msg(trade, cur, update_msg, 0))
            if closed:
                to_remove.append(trade)

        except Exception as e:
            logger.error(f"Monitor trade #{trade.get('id','?')}: {e}")

    if to_remove:
        async with _trades_lock:
            for tr in to_remove:
                if tr in active_trades: active_trades.remove(tr)
            save_trades()


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


async def send_smart_alerts(context):
    try:
        df = get_data("BTC", days=7, interval="hourly")
        if df is None or len(df) < 30: return
        df    = calc_indicators(df)
        last  = df.iloc[-1]
        price = float(last["Close"])
        rsi   = safe(last["RSI"], 50)
        fib_levels, _, _, _ = calculate_fibonacci(df)
        alerts = []

        if rsi < 28:   alerts.append("🔴 RSI تشبع بيعي قوي ("+str(round(rsi,1))+") — فرصة شراء محتملة!")
        elif rsi > 72: alerts.append("🔴 RSI تشبع شرائي قوي ("+str(round(rsi,1))+") — احتمال انعكاس!")

        for pct, level in fib_levels.items():
            if abs(price - level) / price * 100 < 0.3:
                alerts.append("📐 السعر عند Fib "+pct+"% ($"+"{:,.2f}".format(level)+") — مستوى مهم!")
                break

        bb_u = safe(last["BB_U"], price * 1.02)
        bb_l = safe(last["BB_L"], price * 0.98)
        if (bb_u - bb_l) / bb_u * 100 < 2:
            alerts.append("💥 Bollinger Squeeze — حركة قوية قادمة!")

        # ✅ FIX 2: ev30_key معرّف هنا صح — لا يعتمد على scope خارجي
        if not active_trades:
            try:
                ev30 = get_upcoming_event(hours=0.5)
                if ev30:
                    ev30_key = ev30.get("event", "") + ev30.get("time", "")[:10]
                    if not _news_notified.get(ev30_key):
                        _news_notified[ev30_key] = True
                        mins = ev30["mins_left"]
                        news_msg = (
                            "📰 تنبيه اقتصادي\n"
                            +ev30["event"]+" — خلال "+str(mins)+" دقيقة\n"
                            "تأثير متوقع: 🔴 عالي\n"
                            "تجنب فتح صفقات جديدة"
                        )
                        for user_id in ALLOWED_USERS:
                            try:
                                await context.bot.send_message(chat_id=user_id, text=news_msg)
                            except: pass
            except: pass

        if alerts:
            msg = ["╔══════════════════════════╗","  ⚡ تنبيه ذكي — ₿ BTC/USD","╚══════════════════════════╝",
                   "","  💵 السعر: $"+"{:,.2f}".format(price),""]
            for a in alerts: msg.append("  "+a)
            msg += ["","━━━━━━━━━━━━━━━━━━━━━━━━","🕐 "+gmt_now(),"⚠️ للأغراض التعليمية فقط"]
            full_msg = "\n".join(msg)
            await context.bot.send_message(chat_id=CHANNEL_ID, text=full_msg)
            for user_id in ALLOWED_USERS:
                try:
                    await context.bot.send_message(chat_id=user_id, text=full_msg)
                except: pass
    except Exception as e:
        logger.error("Smart alerts: " + str(e))


# ==================== أخبار ====================
async def send_news(context):
    try:
        r = requests.get("https://newsapi.org/v2/everything",
            params={"q":"bitcoin OR Federal Reserve OR inflation OR CPI",
                    "language":"en","sortBy":"publishedAt","pageSize":5,"apiKey":NEWS_API_KEY},
            timeout=10)
        data = r.json()
        if data.get("status") != "ok": return
        articles = data.get("articles", [])
        if not articles: return
        lines = ["╔══════════════════════════╗","  📰 أخبار السوق - أبو مهرة","╚══════════════════════════╝",""]
        for i, a in enumerate(articles[:5], 1):
            lines.append(str(i)+". "+a.get("title","")[:80])
            lines.append("   📌 "+a.get("source",{}).get("name","")+"  |  "+a.get("publishedAt","")[:10])
            lines.append("")
        lines += ["━"*24,"🕐 "+gmt_now(),"⚠️ للأغراض التعليمية فقط"]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
    except Exception as e:
        logger.error("News: " + str(e))


# ══════════════════════════════════════════════════════
#  STATS — Advanced tracking
# ══════════════════════════════════════════════════════
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
        }

def save_stats(stats: dict):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, ensure_ascii=False)

def record_trade_result(trade_id, result: str, rr: float = 0.0,
                        direction: str = "", session: str = ""):
    stats = load_stats()
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
        "time": gmt_now(),
    })
    stats["trades"] = stats["trades"][-100:]
    save_stats(stats)
    logger.info(f"Trade #{trade_id} closed: {result} | RR={rr} | {direction} | {session}")


# ══════════════════════════════════════════════════════
#  DAILY SUMMARY — Advanced stats
# ══════════════════════════════════════════════════════
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
            "╔══════════════════════════╗",
            "  📊 الملخص اليومي — أبو مهرة",
            "╚══════════════════════════╝", "",
            "━━━━  📈 الأداء الإجمالي  ━━━━",
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
            lines += ["━━━━  📊 حسب الاتجاه  ━━━━"]
            if bt > 0:
                lines.append(f"  🟢 BUY:   {bw}/{bt}  ({round(bw/bt*100)}%)")
            if st2 > 0:
                lines.append(f"  🔴 SELL:  {sw}/{st2}  ({round(sw/st2*100)}%)")
            lines.append("")
        ss = s.get("session_stats", {})
        if ss:
            lines += ["━━━━  🕐 حسب الجلسة  ━━━━"]
            for sname, sv in ss.items():
                stot = sv.get("total", 0); swin = sv.get("wins", 0)
                swr2 = round(swin / stot * 100) if stot else 0
                lines.append(f"  {sname:10s}: {swin}/{stot}  ({swr2}%)")
            lines.append("")
        if active_trades:
            lines += [f"━━━━  🔓 صفقات مفتوحة: {len(active_trades)}  ━━━━"]
            cur = get_btc_price()
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
        lines += ["━━━━━━━━━━━━━━━━━━━━━━━━", f"🕐 {gmt_now()}", "⚠️ للأغراض التعليمية فقط"]
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
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(monitor_btc,          interval=60,      first=30)
    app.job_queue.run_repeating(check_pending_trades, interval=15*60,  first=60)
    app.job_queue.run_repeating(send_smart_alerts,    interval=45*60,  first=120)
    app.job_queue.run_repeating(send_news,            interval=4*60*60, first=300)
    app.job_queue.run_daily(send_daily_summary, time=__import__("datetime").time(6, 0, 0))
    logger.info("🐎 Abu Mahra Bot - Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
