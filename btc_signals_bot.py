import os
import time
import random
import logging
import requests
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import ta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "")

AUTO_INTERVAL_MIN = 30
MONITOR_MIN = 5
MIN_CONFIDENCE = 72
MIN_RR = 1.25

CACHE_TTL = 600
SIGNAL_COOLDOWN_SEC = 60 * 60 * 2

ALLOWED_USERS = {8490817794, 1548286220}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_languages = {}
active_btc_trade = {}
_cache = {}
_last_signals = {}

GREETINGS = [
    "مرحبا", "هاي", "هلا", "اهلا", "أهلا", "السلام", "صباح", "مساء", "كيف",
    "hello", "hi", "hey", "good", "morning", "evening"
]

TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة Pro

━━━━━━━━━━━━━━━━━━━━
متخصص في:
₿ البيتكوين BTC/USD
🥇 الذهب XAU/USD

يعتمد على:
▫️ توافق الفريمات 1H / 4H / Daily
▫️ Fibonacci + ATR
▫️ RSI + MACD + EMA + ADX + Bollinger
▫️ فلترة جودة الصفقة والمخاطرة
▫️ تحديثات تلقائية للأهداف ووقف الخسارة
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط — ليست توصية مالية""",

        "btn_btc": "₿ صفقة BTC",
        "btn_gold": "🥇 صفقة الذهب",
        "btn_analysis_btc": "📈 تحليل BTC",
        "btn_analysis_gold": "📈 تحليل الذهب",
        "btn_prices": "💰 الأسعار",
        "btn_about": "ℹ️ عن البوت",
        "btn_lang": "🌐 اللغة",

        "loading_trade": "⏳ جاري تحليل السوق بعمق...",
        "loading_analysis": "⏳ جاري بناء التحليل...",
        "loading_prices": "⏳ جاري جلب الأسعار...",
        "failed": "❌ فشل جلب البيانات، حاول بعد قليل",
        "error": "❌ خطأ: ",
        "no_signal": "⚪ لا توجد صفقة قوية حالياً\nالانتظار أفضل من الدخول الضعيف 🕐",

        "trade_header": "صفقة مقترحة على فريم الساعة - أبو مهرة Pro",
        "auto_header": "صفقة تلقائية مقترحة - أبو مهرة Pro",
        "update_header": "تحديث الصفقة المقترحة - أبو مهرة",

        "entry": "منطقة الدخول",
        "ref_price": "السعر المرجعي",
        "fib_entry": "أقرب مستوى Fib",
        "direction": "نوع الصفقة",
        "buy": "شراء BUY ⬆️",
        "sell": "بيع SELL ⬇️",

        "targets_section": "الأهداف المقترحة",
        "tp1": "TP1",
        "tp2": "TP2",
        "tp3": "TP3",
        "sl": "SL",
        "rr": "العائد / المخاطرة",

        "fib_section": "مستويات Fibonacci",
        "risk_note": "ملاحظة المخاطرة",
        "hold_time": "المدة المتوقعة",
        "support": "دعم",
        "resistance": "مقاومة",
        "confluence": "توافق الفريمات",
        "market_regime": "حالة السوق",
        "quality": "جودة الصفقة",
        "indicators_section": "المؤشرات",
        "strength_section": "قوة الصفقة",
        "risk_section": "المخاطرة",

        "frame_1h": "1H",
        "frame_4h": "4H",
        "frame_1d": "يومي",

        "full_confluence": "🔥 توافق كامل على 3 فريمات",
        "partial_confluence": "✅ توافق قوي على فريمين",
        "no_confluence": "⚪ لا يوجد توافق كافٍ",

        "risk_low": "🟢 منخفضة",
        "risk_med": "🟡 متوسطة",
        "risk_high": "🔴 عالية",

        "risk_low_msg": "إعداد قوي — مع الالتزام بإدارة المخاطر",
        "risk_med_msg": "إعداد جيد — يحتاج دخول منضبط",
        "risk_high_msg": "المخاطرة مرتفعة — يفضل الحذر",

        "footer": "⚠️ للأغراض التعليمية فقط — ليست توصية مالية",
        "updated_gmt": "آخر تحديث GMT",

        "update_tp1_hit": "✅ تم الوصول إلى الهدف الأول",
        "update_tp2_hit": "✅✅ تم الوصول إلى الهدف الثاني",
        "update_near_sl": "⚠️ تم الوصول إلى مستوى وقف الخسارة",
        "update_sl_moved": "📊 تم تحديث مستوى وقف الخسارة",
        "update_tp3_hit": "🏆 تم الوصول إلى الهدف الثالث بنجاح 🎉",

        "current_price": "السعر الحالي",

        "trend_bull": "📈 الاتجاه يميل للصعود",
        "trend_bear": "📉 الاتجاه يميل للهبوط",
        "trend_neutral": "➡️ السوق غير واضح",

        "summary_bull": "✅ الخلاصة: الميل الفني صاعد",
        "summary_bear": "✅ الخلاصة: الميل الفني هابط",
        "summary_neutral": "✅ الخلاصة: السوق يحتاج تأكيد إضافي",

        "prices_title": "💰 الأسعار الحالية",
        "change_24h": "التغيير 24h",

        "about_text": """ℹ️ عن بوت أبو مهرة Pro 🐎

يعتمد على قراءة فنية متعددة الطبقات تشمل:
▫️ توافق 1H / 4H / Daily
▫️ Fibonacci + ATR للأهداف
▫️ RSI, MACD, EMA, ADX, Bollinger, Stochastic
▫️ فلتر جودة الصفقة
▫️ فلتر حالة السوق
▫️ منع تكرار الصفقات المتشابهة
▫️ تحديث مستويات TP و SL

⚠️ للأغراض التعليمية فقط — ليست توصية مالية""",
    },

    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "welcome": """🐎 Welcome to Abu Mahra Pro Bot

━━━━━━━━━━━━━━━━━━━━
Specialized in:
₿ Bitcoin BTC/USD
🥇 Gold XAU/USD

Built on:
▫️ 1H / 4H / Daily confluence
▫️ Fibonacci + ATR
▫️ RSI + MACD + EMA + ADX + Bollinger
▫️ Trade quality and risk filtering
▫️ Automatic TP/SL level updates
━━━━━━━━━━━━━━━━━━━━
⚠️ Educational purposes only — not financial advice""",

        "btn_btc": "₿ BTC Trade",
        "btn_gold": "🥇 Gold Trade",
        "btn_analysis_btc": "📈 BTC Analysis",
        "btn_analysis_gold": "📈 Gold Analysis",
        "btn_prices": "💰 Prices",
        "btn_about": "ℹ️ About",
        "btn_lang": "🌐 Language",

        "loading_trade": "⏳ Deep market scan in progress...",
        "loading_analysis": "⏳ Building analysis...",
        "loading_prices": "⏳ Fetching prices...",
        "failed": "❌ Failed to fetch data, try again shortly",
        "error": "❌ Error: ",
        "no_signal": "⚪ No strong trade setup right now\nWaiting is better than forcing a weak entry 🕐",

        "trade_header": "Suggested 1H Trade Setup - Abu Mahra Pro",
        "auto_header": "Suggested Auto Trade Setup - Abu Mahra Pro",
        "update_header": "Suggested Trade Update - Abu Mahra",

        "entry": "Entry Zone",
        "ref_price": "Reference Price",
        "fib_entry": "Nearest Fib",
        "direction": "Trade Type",
        "buy": "BUY ⬆️",
        "sell": "SELL ⬇️",

        "targets_section": "Suggested Targets",
        "tp1": "TP1",
        "tp2": "TP2",
        "tp3": "TP3",
        "sl": "SL",
        "rr": "Reward / Risk",

        "fib_section": "Fibonacci Levels",
        "risk_note": "Risk Note",
        "hold_time": "Expected Hold",
        "support": "Support",
        "resistance": "Resistance",
        "confluence": "Timeframe Confluence",
        "market_regime": "Market Regime",
        "quality": "Trade Quality",
        "indicators_section": "Indicators",
        "strength_section": "Trade Strength",
        "risk_section": "Risk",

        "frame_1h": "1H",
        "frame_4h": "4H",
        "frame_1d": "Daily",

        "full_confluence": "🔥 Full confluence on 3 timeframes",
        "partial_confluence": "✅ Strong confluence on 2 timeframes",
        "no_confluence": "⚪ Not enough confluence",

        "risk_low": "🟢 Low",
        "risk_med": "🟡 Medium",
        "risk_high": "🔴 High",

        "risk_low_msg": "Strong setup — respect risk management",
        "risk_med_msg": "Good setup — requires disciplined entry",
        "risk_high_msg": "High risk — caution preferred",

        "footer": "⚠️ Educational purposes only — not financial advice",
        "updated_gmt": "Last update GMT",

        "update_tp1_hit": "✅ TP1 reached",
        "update_tp2_hit": "✅✅ TP2 reached",
        "update_near_sl": "⚠️ SL level reached",
        "update_sl_moved": "📊 SL level updated",
        "update_tp3_hit": "🏆 TP3 reached successfully 🎉",

        "current_price": "Current Price",

        "trend_bull": "📈 Trend leaning bullish",
        "trend_bear": "📉 Trend leaning bearish",
        "trend_neutral": "➡️ Market unclear",

        "summary_bull": "✅ Summary: Technical bias is bullish",
        "summary_bear": "✅ Summary: Technical bias is bearish",
        "summary_neutral": "✅ Summary: Market needs more confirmation",

        "prices_title": "💰 Current Prices",
        "change_24h": "24h Change",

        "about_text": """ℹ️ About Abu Mahra Pro Bot 🐎

Built on multi-layer technical reading:
▫️ 1H / 4H / Daily confluence
▫️ Fibonacci + ATR targets
▫️ RSI, MACD, EMA, ADX, Bollinger, Stochastic
▫️ Trade quality filter
▫️ Market regime filter
▫️ Duplicate trade prevention
▫️ TP and SL level updates

⚠️ Educational purposes only — not financial advice""",
    },
}


def t(uid, key):
    lang = user_languages.get(uid, "ar")
    return TEXTS[lang].get(key, key)


def gmt_now():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


def get_cached(key):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data.copy() if hasattr(data, "copy") else data
    return None


def set_cache(key, data):
    _cache[key] = (data.copy() if hasattr(data, "copy") else data, time.time())


def asset_symbol(asset):
    return "BTC/USD" if asset == "BTC" else "XAU/USD"


# ================= DATA =================

def get_data(asset="BTC", days=30, interval="hourly"):
    asset = asset.upper()
    cache_key = f"{asset}_{days}_{interval}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    symbol = asset_symbol(asset)

    if interval == "hourly":
        td_interval = "1h"
        outputsize = min(days * 24, 500)
    elif interval == "daily":
        td_interval = "1day"
        outputsize = min(days, 500)
    else:
        td_interval = "1h"
        outputsize = 300

    if TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": symbol,
                    "interval": td_interval,
                    "outputsize": outputsize,
                    "apikey": TWELVEDATA_KEY,
                    "format": "JSON",
                },
                timeout=15,
            )
            data = r.json()

            if "values" in data and len(data["values"]) > 0:
                rows = []
                for v in reversed(data["values"]):
                    rows.append({
                        "timestamp": pd.to_datetime(v["datetime"]),
                        "Open": float(v["open"]),
                        "High": float(v["high"]),
                        "Low": float(v["low"]),
                        "Close": float(v["close"]),
                        "Volume": float(v.get("volume", 0) or 0),
                    })

                df = pd.DataFrame(rows).set_index("timestamp").sort_index().dropna()
                if len(df) >= 60:
                    set_cache(cache_key, df)
                    return df

        except Exception as e:
            logger.warning("TwelveData failed: %s", e)

    if asset == "BTC":
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc",
                params={"vs_currency": "usd", "days": min(days, 30)},
                timeout=15,
            )
            data = r.json()

            df = pd.DataFrame(data, columns=["timestamp", "Open", "High", "Low", "Close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["Volume"] = 0
            df = df.set_index("timestamp").sort_index().dropna()

            if len(df) >= 60:
                set_cache(cache_key, df)
                return df

        except Exception as e:
            logger.error("CoinGecko BTC fallback failed: %s", e)

    return None


def get_live_price(asset="BTC"):
    asset = asset.upper()

    if TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/price",
                params={"symbol": asset_symbol(asset), "apikey": TWELVEDATA_KEY},
                timeout=10,
            )
            data = r.json()
            if "price" in data:
                return float(data["price"])
        except Exception:
            pass

    if asset == "BTC":
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"},
                timeout=10,
            )
            return float(r.json()["bitcoin"]["usd"])
        except Exception:
            return None

    return None


def get_prices():
    result = {"bitcoin": {}, "gold": {}}

    btc = get_live_price("BTC")
    gold = get_live_price("GOLD")

    result["bitcoin"] = {"usd": btc or 0, "usd_24h_change": 0}
    result["gold"] = {"usd": gold or 0, "usd_24h_change": 0}
    return result


# ================= INDICATORS =================

def calc_indicators(df):
    df = df.copy()

    c = df["Close"]
    h = df["High"]
    l = df["Low"]

    df["EMA9"] = ta.trend.EMAIndicator(c, window=9).ema_indicator()
    df["EMA21"] = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df["EMA50"] = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df["EMA200"] = ta.trend.EMAIndicator(c, window=200).ema_indicator()

    df["RSI"] = ta.momentum.RSIIndicator(c, window=14).rsi()

    macd = ta.trend.MACD(c)
    df["MACD"] = macd.macd()
    df["MACD_S"] = macd.macd_signal()
    df["MACD_H"] = macd.macd_diff()

    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["BB_U"] = bb.bollinger_hband()
    df["BB_L"] = bb.bollinger_lband()
    df["BB_W"] = (df["BB_U"] - df["BB_L"]) / c * 100

    df["ATR"] = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    df["ATR_PCT"] = df["ATR"] / c * 100

    adx = ta.trend.ADXIndicator(h, l, c, window=14)
    df["ADX"] = adx.adx()

    stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
    df["Stoch"] = stoch.stoch()
    df["Stoch_S"] = stoch.stoch_signal()

    pivot = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df["R1"] = 2 * pivot - l.shift(1)
    df["S1"] = 2 * pivot - h.shift(1)

    return df.dropna()


def detect_market_regime(df):
    last = df.iloc[-1]
    adx = float(last["ADX"])
    atr_pct = float(last["ATR_PCT"])
    bb_w = float(last["BB_W"])

    if atr_pct > 2.8:
        return "High Volatility"
    if adx >= 25:
        return "Trending"
    if bb_w < 2.5:
        return "Squeeze / Breakout Watch"
    return "Ranging / Mixed"


# ================= FIBONACCI =================

def calculate_fibonacci(df):
    window = min(80, len(df))
    recent = df.tail(window)

    swing_high = float(recent["High"].max())
    swing_low = float(recent["Low"].min())
    diff = swing_high - swing_low

    levels = {
        "0.0": round(swing_high, 2),
        "23.6": round(swing_high - 0.236 * diff, 2),
        "38.2": round(swing_high - 0.382 * diff, 2),
        "50.0": round(swing_high - 0.500 * diff, 2),
        "61.8": round(swing_high - 0.618 * diff, 2),
        "78.6": round(swing_high - 0.786 * diff, 2),
        "100.0": round(swing_low, 2),
    }

    extensions = {
        "BUY_127.2": round(swing_high + 0.272 * diff, 2),
        "BUY_161.8": round(swing_high + 0.618 * diff, 2),
        "BUY_200.0": round(swing_high + 1.000 * diff, 2),
        "SELL_127.2": round(swing_low - 0.272 * diff, 2),
        "SELL_161.8": round(swing_low - 0.618 * diff, 2),
        "SELL_200.0": round(swing_low - 1.000 * diff, 2),
    }

    return levels, extensions, swing_high, swing_low


def find_nearest_fib(price, levels):
    nearest_key, nearest_val = min(levels.items(), key=lambda x: abs(x[1] - price))
    dist_pct = abs(nearest_val - price) / price * 100
    return nearest_val, nearest_key, dist_pct


def get_fib_targets(price, levels, extensions, direction, atr):
    fib_vals = sorted(levels.values())

    if direction == "BUY":
        below = [v for v in fib_vals if v < price]
        above = [v for v in fib_vals if v > price]

        sl_base = below[-1] if below else price - atr
        sl = round(min(sl_base - 0.25 * atr, price - 0.9 * atr), 2)

        tp1 = round(max((above[0] if above else price + atr), price + 0.85 * atr), 2)
        tp2 = round(max(price + 1.65 * atr, tp1 + 0.5 * atr), 2)
        tp3 = round(max(extensions["BUY_127.2"], price + 2.6 * atr), 2)

    else:
        above = [v for v in fib_vals if v > price]
        below = [v for v in fib_vals if v < price]

        sl_base = above[0] if above else price + atr
        sl = round(max(sl_base + 0.25 * atr, price + 0.9 * atr), 2)

        tp1 = round(min((below[-1] if below else price - atr), price - 0.85 * atr), 2)
        tp2 = round(min(price - 1.65 * atr, tp1 - 0.5 * atr), 2)
        tp3 = round(min(extensions["SELL_127.2"], price - 2.6 * atr), 2)

    rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
    return sl, tp1, tp2, tp3, rr


# ================= ANALYSIS =================

def analyze_frame(df, uid=0):
    df = calc_indicators(df)
    if len(df) < 50:
        return None

    last = df.iloc[-1]
    price = float(last["Close"])

    sb = 0
    ss = 0
    details = []

    rsi = float(last["RSI"])
    adx = float(last["ADX"])

    if rsi < 30:
        sb += 20
        details.append(f"RSI تشبع بيعي ({rsi:.1f}) 🟢")
    elif rsi < 45:
        sb += 10
        details.append(f"RSI يميل للشراء ({rsi:.1f})")
    elif rsi > 70:
        ss += 20
        details.append(f"RSI تشبع شرائي ({rsi:.1f}) 🔴")
    elif rsi > 55:
        ss += 10
        details.append(f"RSI يميل للبيع ({rsi:.1f})")

    if last["MACD"] > last["MACD_S"] and last["MACD_H"] > 0:
        sb += 18
        details.append("MACD زخم صاعد ↗️")
    elif last["MACD"] < last["MACD_S"] and last["MACD_H"] < 0:
        ss += 18
        details.append("MACD زخم هابط ↘️")

    if last["EMA9"] > last["EMA21"] > last["EMA50"]:
        sb += 22
        details.append("EMAs مرتبة صعوداً 📈")
    elif last["EMA9"] < last["EMA21"] < last["EMA50"]:
        ss += 22
        details.append("EMAs مرتبة هبوطاً 📉")

    if price > last["EMA200"]:
        sb += 10
    else:
        ss += 10

    if adx >= 25:
        if sb > ss:
            sb += 8
        elif ss > sb:
            ss += 8
        details.append(f"ADX قوة اتجاه ({adx:.1f})")

    if price <= last["BB_L"]:
        sb += 8
        details.append("Bollinger دعم سفلي 🟢")
    elif price >= last["BB_U"]:
        ss += 8
        details.append("Bollinger مقاومة علوية 🔴")

    if last["Stoch"] < 20 and last["Stoch_S"] < 20:
        sb += 6
        details.append("Stochastic تشبع بيعي")
    elif last["Stoch"] > 80 and last["Stoch_S"] > 80:
        ss += 6
        details.append("Stochastic تشبع شرائي")

    total = sb + ss
    if total <= 0:
        return None

    direction = "BUY" if sb > ss else "SELL"
    conf = round(max(sb, ss) / total * 100)

    return {
        "direction": direction,
        "conf": conf,
        "sb": sb,
        "ss": ss,
        "price": round(price, 2),
        "rsi": round(rsi, 1),
        "atr": round(float(last["ATR"]), 2),
        "adx": round(adx, 1),
        "support": round(float(last["S1"]), 2),
        "resistance": round(float(last["R1"]), 2),
        "details": details[:5],
        "macd_bull": last["MACD"] > last["MACD_S"],
        "ema_bull": last["EMA9"] > last["EMA21"] > last["EMA50"],
        "ema_bear": last["EMA9"] < last["EMA21"] < last["EMA50"],
        "bb_zone": "low" if price <= last["BB_L"] else "high" if price >= last["BB_U"] else "mid",
    }


def full_analysis(asset="BTC", uid=0):
    df_1h = get_data(asset, days=18, interval="hourly")
    df_4h_raw = get_data(asset, days=35, interval="hourly")
    df_1d = get_data(asset, days=180, interval="daily")

    df_4h = None
    if df_4h_raw is not None and len(df_4h_raw) > 0:
        df_4h = df_4h_raw.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()

    frames = {
        "1h": df_1h,
        "4h": df_4h,
        "1d": df_1d,
    }

    results = {}
    for label, df in frames.items():
        if df is not None and len(df) >= 60:
            r = analyze_frame(df, uid)
            if r:
                results[label] = r

    if len(results) < 2:
        return None

    buy_c = sum(1 for r in results.values() if r["direction"] == "BUY")
    sell_c = sum(1 for r in results.values() if r["direction"] == "SELL")

    if buy_c == sell_c:
        return None

    final = "BUY" if buy_c > sell_c else "SELL"
    aligned = buy_c if final == "BUY" else sell_c

    if aligned < 2:
        return None

    aligned_results = [r for r in results.values() if r["direction"] == final]
    avg_conf = round(np.mean([r["conf"] for r in aligned_results]))
    base_conf = min(96, avg_conf + (7 if aligned == 3 else 0))

    main = results.get("1h") or aligned_results[0]
    price = main["price"]
    atr = main["atr"]

    df_regime = calc_indicators(df_1h)
    market_regime = detect_market_regime(df_regime)

    if market_regime == "High Volatility" and base_conf < 82:
        return None

    fib_levels, fib_ext, swing_h, swing_l = calculate_fibonacci(df_1h)
    nearest_fib, fib_key, dist_pct = find_nearest_fib(price, fib_levels)
    sl, tp1, tp2, tp3, rr = get_fib_targets(price, fib_levels, fib_ext, final, atr)

    if rr < MIN_RR:
        return None

    quality = base_conf
    if rr >= 1.8:
        quality += 4
    if main["adx"] >= 25:
        quality += 3
    if market_regime == "Ranging / Mixed":
        quality -= 4
    if market_regime == "High Volatility":
        quality -= 6
    if dist_pct > 2:
        quality -= 3

    quality = max(1, min(99, quality))

    if quality < MIN_CONFIDENCE:
        return None

    risk = 100 - quality
    if risk < 28:
        rl = t(uid, "risk_low")
        rm = t(uid, "risk_low_msg")
    elif risk < 50:
        rl = t(uid, "risk_med")
        rm = t(uid, "risk_med_msg")
    else:
        rl = t(uid, "risk_high")
        rm = t(uid, "risk_high_msg")

    icons = {"1h": t(uid, "frame_1h"), "4h": t(uid, "frame_4h"), "1d": t(uid, "frame_1d")}
    frame_lines = []
    for k, r in results.items():
        icon = "🟢" if r["direction"] == "BUY" else "🔴"
        frame_lines.append(f"{icon} {icons.get(k, k)}: {r['direction']} ({r['conf']}%) | ADX {r['adx']}")

    conf_txt = t(uid, "full_confluence") if aligned == 3 else t(uid, "partial_confluence")

    key_fibs = [
        f"Fib {pct}%  ${val:,.2f}"
        for pct, val in sorted(fib_levels.items(), key=lambda x: float(x[0]))[:6]
    ]

    entry_buffer = max(atr * 0.18, price * 0.0015)
    entry_low = round(price - entry_buffer, 2)
    entry_high = round(price + entry_buffer, 2)

    return {
        "final": final,
        "asset": asset,
        "confluence_txt": conf_txt,
        "base_conf": base_conf,
        "quality": quality,
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "rr": rr,
        "atr": atr,
        "risk_pct": risk,
        "risk_label": rl,
        "risk_msg": rm,
        "frame_lines": frame_lines,
        "ind_details": main["details"],
        "rsi": main["rsi"],
        "adx": main["adx"],
        "support": main["support"],
        "resistance": main["resistance"],
        "macd_bull": main["macd_bull"],
        "ema_bull": main["ema_bull"],
        "ema_bear": main["ema_bear"],
        "bb_zone": main["bb_zone"],
        "fib_levels": fib_levels,
        "fib_ext": fib_ext,
        "key_fibs": key_fibs,
        "nearest_fib": nearest_fib,
        "fib_key": fib_key,
        "market_regime": market_regime,
        "leverage_ar": "إدارة المخاطر أهم من حجم الدخول — تجنب الرافعة العالية",
        "leverage_en": "Risk management matters more than position size — avoid high leverage",
        "hold_ar": "2 — 8 ساعات",
        "hold_en": "2 — 8 Hours",
    }


# ================= MESSAGES =================

def build_trade_msg(res, uid=0, auto=False):
    lang = user_languages.get(uid, "ar")
    ai = "₿" if res["asset"] == "BTC" else "🥇"
    an = "BTC/USD" if res["asset"] == "BTC" else "XAU/USD"
    is_sell = res["final"] == "SELL"

    dir_emoji = "🔴" if is_sell else "🟢"
    dir_txt = t(uid, "sell") if is_sell else t(uid, "buy")
    header = t(uid, "auto_header") if auto else t(uid, "trade_header")

    risk_note = res["leverage_ar"] if lang == "ar" else res["leverage_en"]
    hold = res["hold_ar"] if lang == "ar" else res["hold_en"]

    conf = res["quality"]
    bar = "█" * (conf // 10) + "░" * (10 - conf // 10)

    lines = [
        "╔══════════════════════════╗",
        f"  {ai} {an}  {dir_emoji}  {dir_txt}",
        f"  ⚡ {header}",
        "╚══════════════════════════╝",
        "",
        f"📍 {t(uid, 'entry')}        ${res['entry_low']:,.2f} - ${res['entry_high']:,.2f}",
        f"💵 {t(uid, 'ref_price')}     ${res['price']:,.2f}",
        f"📐 {t(uid, 'fib_entry')}   Fib {res['fib_key']}% (${res['nearest_fib']:,.2f})",
        "",
        f"━━━━  🎯 {t(uid, 'targets_section')}  ━━━━",
        f"  TP1  ›  ${res['tp1']:,.2f}",
        f"  TP2  ›  ${res['tp2']:,.2f}",
        f"  TP3  ›  ${res['tp3']:,.2f}",
        f"  🛑 {t(uid, 'sl')}   ›  ${res['sl']:,.2f}",
        f"  ⚖️ {t(uid, 'rr')}:  1:{res['rr']}",
        "",
        f"━━━━  🧠 {t(uid, 'quality')}  ━━━━",
        f"  {bar}  {res['quality']}%",
        f"  Technical Confidence: {res['base_conf']}%",
        f"  {t(uid, 'market_regime')}: {res['market_regime']}",
        "",
        f"━━━━  🔗 {t(uid, 'confluence')}  ━━━━",
    ]

    for fl in res["frame_lines"]:
        lines.append("  " + fl)

    lines.append("  " + res["confluence_txt"])

    lines += [
        "",
        f"━━━━  📐 {t(uid, 'fib_section')}  ━━━━",
    ]

    for f in res["key_fibs"]:
        lines.append("  " + f)

    lines += [
        "",
        f"━━━━  📊 {t(uid, 'indicators_section')}  ━━━━",
        f"  RSI: {res['rsi']}",
        f"  ADX: {res['adx']}",
    ]

    for d in res["ind_details"]:
        lines.append("  " + d)

    lines += [
        "",
        f"━━━━  📡 {t(uid, 'support')} / {t(uid, 'resistance')}  ━━━━",
        f"  🟢 {t(uid, 'support')}      ${res['support']:,.2f}",
        f"  🔴 {t(uid, 'resistance')}   ${res['resistance']:,.2f}",
        "",
        f"━━━━  ⚠️ {t(uid, 'risk_section')}  ━━━━",
        f"  {res['risk_label']}  •  {res['risk_pct']}%",
        f"  {res['risk_msg']}",
        f"  {risk_note}",
        f"  ⏳ {t(uid, 'hold_time')}: {hold}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {t(uid, 'updated_gmt')}: {gmt_now()}",
        t(uid, "footer"),
    ]

    return "\n".join(lines)


def build_update_msg(trade, current_price, update_type, uid=0):
    dir_txt = t(uid, "buy") if trade["direction"] == "BUY" else t(uid, "sell")

    return "\n".join([
        "╔══════════════════════════╗",
        f"  🔄 ₿ BTC/USD • {t(uid, 'update_header')}",
        "╚══════════════════════════╝",
        "",
        f"  {t(uid, 'direction')}:      {dir_txt}",
        f"  {t(uid, 'entry')}:          ${trade['entry_low']:,.2f} - ${trade['entry_high']:,.2f}",
        f"  {t(uid, 'current_price')}:  ${current_price:,.2f}",
        "",
        f"  {update_type}",
        "",
        f"━━━━  🎯 {t(uid, 'targets_section')}  ━━━━",
        f"  TP1  ›  ${trade['tp1']:,.2f}",
        f"  TP2  ›  ${trade['tp2']:,.2f}",
        f"  TP3  ›  ${trade['tp3']:,.2f}",
        f"  🛑 SL  ›  ${trade['sl']:,.2f}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {t(uid, 'updated_gmt')}: {gmt_now()}",
        t(uid, "footer"),
    ])


def build_analysis_msg(res, uid=0):
    ai = "₿" if res["asset"] == "BTC" else "🥇"
    an = "BTC/USD" if res["asset"] == "BTC" else "XAU/USD"

    if res["final"] == "BUY":
        trend = t(uid, "trend_bull")
        summary = t(uid, "summary_bull")
    elif res["final"] == "SELL":
        trend = t(uid, "trend_bear")
        summary = t(uid, "summary_bear")
    else:
        trend = t(uid, "trend_neutral")
        summary = t(uid, "summary_neutral")

    lines = [
        "╔══════════════════════════╗",
        f"  {ai} {an} | تحليل السوق",
        "╚══════════════════════════╝",
        "",
        f"  {trend}",
        f"  💵 {t(uid, 'ref_price')}: ${res['price']:,.2f}",
        f"  🧠 {t(uid, 'quality')}: {res['quality']}%",
        f"  {t(uid, 'market_regime')}: {res['market_regime']}",
        "",
        f"━━━━  🔗 {t(uid, 'confluence')}  ━━━━",
    ]

    for fl in res["frame_lines"]:
        lines.append("  " + fl)

    lines += [
        "",
        f"━━━━  📊 {t(uid, 'indicators_section')}  ━━━━",
        f"  RSI: {res['rsi']}",
        f"  ADX: {res['adx']}",
    ]

    for d in res["ind_details"]:
        lines.append("  " + d)

    lines += [
        "",
        "  " + summary,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🕐 {t(uid, 'updated_gmt')}: {gmt_now()}",
        t(uid, "footer"),
    ]

    return "\n".join(lines)


# ================= KEYBOARDS =================

def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(uid, "btn_btc"), callback_data="trade_BTC"),
            InlineKeyboardButton(t(uid, "btn_gold"), callback_data="trade_GOLD"),
        ],
        [
            InlineKeyboardButton(t(uid, "btn_analysis_btc"), callback_data="analysis_BTC"),
            InlineKeyboardButton(t(uid, "btn_analysis_gold"), callback_data="analysis_GOLD"),
        ],
        [
            InlineKeyboardButton(t(uid, "btn_prices"), callback_data="prices"),
            InlineKeyboardButton(t(uid, "btn_about"), callback_data="about"),
        ],
        [InlineKeyboardButton(t(uid, "btn_lang"), callback_data="change_lang")],
    ])


def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data="lang_ar"),
        InlineKeyboardButton("English", callback_data="lang_en"),
    ]])


# ================= DEDUP =================

def signal_fingerprint(res):
    step = 50 if res["asset"] == "BTC" else 5
    rounded_entry = round(res["price"] / step) * step
    return f"{res['asset']}:{res['final']}:{rounded_entry}"


def can_send_signal(res):
    fp = signal_fingerprint(res)
    last = _last_signals.get(fp)

    if last and time.time() - last < SIGNAL_COOLDOWN_SEC:
        return False

    _last_signals[fp] = time.time()
    return True


# ================= HANDLERS =================

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in ALLOWED_USERS:
        await update.message.reply_text("⛔ هذا البوت خاص")
        return

    if uid not in user_languages:
        await update.message.reply_text(
            "🐎 Abu Mahra Pro\n\nاختر لغتك / Choose your language:",
            reply_markup=lang_keyboard(),
        )
    else:
        await update.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    text = update.message.text or ""
    kb = main_keyboard(uid) if uid in user_languages else lang_keyboard()

    if any(g in text.lower() for g in GREETINGS):
        reply = "هلا وغلا! 🐎 استخدم الأزرار 👇" if user_languages.get(uid, "ar") == "ar" else "Hello! 🐎 Use the buttons below 👇"
    else:
        reply = "اختر من القائمة 👇" if user_languages.get(uid, "ar") == "ar" else "Choose from the menu 👇"

    await update.message.reply_text(reply, reply_markup=kb)


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data

    await query.answer()

    if uid not in ALLOWED_USERS:
        return

    if data == "lang_ar":
        user_languages[uid] = "ar"
        await query.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))

    elif data == "lang_en":
        user_languages[uid] = "en"
        await query.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))

    elif data == "change_lang":
        await query.message.reply_text(t(uid, "choose_lang"), reply_markup=lang_keyboard())

    elif data.startswith("trade_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid, "loading_trade"))

        try:
            res = full_analysis(asset, uid)

            if not res:
                await query.message.reply_text(t(uid, "no_signal"))
                return

            await query.message.reply_text(build_trade_msg(res, uid))

            if asset == "BTC":
                active_btc_trade["data"] = {
                    "asset": "BTC",
                    "direction": res["final"],
                    "entry": res["price"],
                    "entry_low": res["entry_low"],
                    "entry_high": res["entry_high"],
                    "sl": res["sl"],
                    "tp1": res["tp1"],
                    "tp2": res["tp2"],
                    "tp3": res["tp3"],
                    "atr": res["atr"],
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "chat_id": query.message.chat_id,
                    "uid": uid,
                }

        except Exception as e:
            logger.exception("Manual trade failed")
            await query.message.reply_text(t(uid, "error") + str(e))

    elif data.startswith("analysis_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid, "loading_analysis"))

        try:
            res = full_analysis(asset, uid)

            if not res:
                await query.message.reply_text(t(uid, "no_signal"))
                return

            await query.message.reply_text(build_analysis_msg(res, uid))

        except Exception as e:
            logger.exception("Analysis failed")
            await query.message.reply_text(t(uid, "error") + str(e))

    elif data == "prices":
        try:
            d = get_prices()
            btc = d.get("bitcoin", {})
            gold = d.get("gold", {})

            bp = btc.get("usd", 0)
            gp = gold.get("usd", 0)

            lines = [
                "╔══════════════════════════╗",
                f"  {t(uid, 'prices_title')}",
                "╚══════════════════════════╝",
                "",
                f"  ₿ BTC/USD:   ${bp:,.2f}" if bp else "  ₿ BTC/USD: غير متاح",
                "",
                f"  🥇 XAU/USD:  ${gp:,.2f}" if gp else "  🥇 XAU/USD: غير متاح",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                f"🕐 {t(uid, 'updated_gmt')}: {gmt_now()}",
            ]

            await query.message.reply_text("\n".join(lines))

        except Exception as e:
            await query.message.reply_text(t(uid, "error") + str(e))

    elif data == "about":
        await query.message.reply_text(t(uid, "about_text"))


# ================= AUTO JOBS =================

async def auto_signals(context):
    try:
        for asset in ["BTC", "GOLD"]:
            res = full_analysis(asset, 0)

            if not res:
                continue

            if not can_send_signal(res):
                logger.info("Duplicate signal skipped: %s", signal_fingerprint(res))
                continue

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=build_trade_msg(res, 0, auto=True),
            )

            if asset == "BTC":
                active_btc_trade["data"] = {
                    "asset": "BTC",
                    "direction": res["final"],
                    "entry": res["price"],
                    "entry_low": res["entry_low"],
                    "entry_high": res["entry_high"],
                    "sl": res["sl"],
                    "tp1": res["tp1"],
                    "tp2": res["tp2"],
                    "tp3": res["tp3"],
                    "atr": res["atr"],
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "chat_id": CHANNEL_ID,
                    "uid": 0,
                }

    except Exception as e:
        logger.error("❌ Auto: %s", e)


async def monitor_btc(context):
    if "data" not in active_btc_trade:
        return

    trade = active_btc_trade["data"]

    try:
        current = get_live_price("BTC")
        if not current:
            return

        direction = trade["direction"]
        chat_id = trade["chat_id"]
        uid = trade.get("uid", 0)
        update_msg = None
        should_clear = False

        if direction == "BUY":
            if current <= trade["sl"]:
                update_msg = t(uid, "update_near_sl")
                should_clear = True
            elif current >= trade["tp3"]:
                update_msg = t(uid, "update_tp3_hit")
                should_clear = True
            elif not trade["tp1_hit"] and current >= trade["tp1"]:
                trade["tp1_hit"] = True
                trade["sl"] = trade["entry"]
                update_msg = t(uid, "update_tp1_hit")
            elif trade["tp1_hit"] and not trade["tp2_hit"] and current >= trade["tp2"]:
                trade["tp2_hit"] = True
                trade["sl"] = trade["tp1"]
                update_msg = t(uid, "update_tp2_hit")

        else:
            if current >= trade["sl"]:
                update_msg = t(uid, "update_near_sl")
                should_clear = True
            elif current <= trade["tp3"]:
                update_msg = t(uid, "update_tp3_hit")
                should_clear = True
            elif not trade["tp1_hit"] and current <= trade["tp1"]:
                trade["tp1_hit"] = True
                trade["sl"] = trade["entry"]
                update_msg = t(uid, "update_tp1_hit")
            elif trade["tp1_hit"] and not trade["tp2_hit"] and current <= trade["tp2"]:
                trade["tp2_hit"] = True
                trade["sl"] = trade["tp1"]
                update_msg = t(uid, "update_tp2_hit")

        if update_msg:
            await context.bot.send_message(
                chat_id=chat_id,
                text=build_update_msg(trade, current, update_msg, uid),
            )

        if should_clear:
            active_btc_trade.clear()

    except Exception as e:
        logger.error("❌ Monitor: %s", e)


# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(
        auto_signals,
        interval=AUTO_INTERVAL_MIN * 60,
        first=30,
    )

    app.job_queue.run_repeating(
        monitor_btc,
        interval=MONITOR_MIN * 60,
        first=60,
    )

    logger.info("🐎 Abu Mahra Pro Bot - Ready!")
    app.run_polling()


if __name__ == "__main__":
    main()
