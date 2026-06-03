import os
import logging
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import ta

BOT_TOKEN      = os.environ.get("BOT_TOKEN",  "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "")
AUTO_INTERVAL_MIN = 30
MONITOR_MIN       = 5
MIN_CONFIDENCE    = 68

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
user_languages   = {}
active_btc_trade = {}
# ==================== Cache بسيط ====================
_cache = {}
CACHE_TTL = 600  # 10 دقائق

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
REPLIES_AR = [
    "هلا وغلا! 🐎 أنا بوت أبو مهرة\nاستخدم الأزرار 👇",
    "أهلاً! 🤖 تبي صفقة أو تحليل؟ اختر 👇",
    "وعليكم السلام! 🐎 شو أقدر أساعدك؟",
    "هلا! 😊 اضغط أي زر للبدء 👇",
]
REPLIES_EN = [
    "Hello! 🐎 I'm Abu Mahra Bot!\nUse the buttons below 👇",
    "Hi! 🤖 Want a trade or analysis? Choose 👇",
    "Hey! 😊 Press any button to start 👇",
]
CONFUSED_AR = ["ما فهمت 😅 استخدم الأزرار 👇", "🤔 اختر من القائمة 👇"]
CONFUSED_EN = ["Didn't get that 😅 Use the buttons 👇", "🤔 Choose from the menu 👇"]

import random

TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة! 🐎

━━━━━━━━━━━━━━━━━━━━
متخصص في:
₿ البيتكوين  BTC/USD
🥇 الذهب  XAU/USD

✨ مميزاتي:
▫️ صفقات مبنية على فريم الساعة
▫️ Fibonacci + ATR للأهداف
▫️ مستويات دعم ومقاومة دقيقة
▫️ إشارات تلقائية كل 30 دقيقة
▫️ مراقبة BTC وتحديث SL/TP
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط""",

        "btn_btc":          "₿ صفقة BTC",
        "btn_gold":         "🥇 صفقة ذهب",
        "btn_analysis_btc": "📈 تحليل BTC",
        "btn_analysis_gold":"📈 تحليل ذهب",
        "btn_prices":       "💰 الأسعار",
        "btn_about":        "ℹ️ عن البوت",
        "btn_lang":         "🌐 اللغة",

        "loading_trade":    "⏳ جاري تحليل السوق...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices":   "⏳ جاري جلب الأسعار...",
        "failed":    "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error":     "❌ خطأ: ",
        "no_signal": "⚪ لا توجد فرصة واضحة الآن\nانتظر إشارة أقوى 🕐",

        "trade_header":    "⚡ صفقة ساعة (1H Scalp) - أبو مهرة",
        "auto_header":     "🔔 إشارة تلقائية - أبو مهرة",
        "update_header":   "🔄 تحديث صفقة BTC - أبو مهرة",
        "analysis_header": "📊 تحليل السوق - أبو مهرة",

        "entry":     "💰 سعر الدخول",
        "fib_entry": "📍 مستوى Fib للدخول",
        "direction": "📌 نوع الصفقة",
        "buy":       "شراء  BUY ⬆️",
        "sell":      "بيع  SELL ⬇️",
        "targets_section": "🎯 الأهداف",
        "tp1": "الهدف الأول   TP1",
        "tp2": "الهدف الثاني  TP2",
        "tp3": "الهدف الثالث  TP3",
        "sl":  "وقف الخسارة  SL",
        "rr":  "⚖️ العائد / المخاطرة",
        "fib_section":   "📐 مستويات Fibonacci",
        "leverage":  "🔧 الرافعة المقترحة",
        "timeframe": "⏱️ الفريم",
        "hold_time": "⏳ المدة",
        "support":    "🟢 دعم",
        "resistance": "🔴 مقاومة",
        "confluence": "🔗 توافق الفريمات",
        "frame_1h":  "🕐 ساعة",
        "frame_4h":  "🕓 4 ساعات",
        "frame_1d":  "📅 يومي",
        "full_confluence":    "🔥 توافق كامل على 3 فريمات!",
        "partial_confluence": "✅ توافق على فريمين",
        "no_confluence":      "⚪ لا توافق",
        "indicators_section": "📈 المؤشرات",
        "strength_section":   "💡 قوة الإشارة",
        "risk_section":       "⚠️ المخاطرة",
        "risk_low":      "🟢 منخفضة",
        "risk_med":      "🟡 متوسطة",
        "risk_high":     "🔴 عالية",
        "risk_low_msg":  "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg":  "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",
        "footer":      "⚠️ للأغراض التعليمية فقط\n📚 تداول بمسؤولية دائماً",
        "updated_gmt": "🕐 آخر تحديث (GMT)",
        "update_tp1_hit":  "✅ الهدف الأول تم! تم نقل SL للدخول",
        "update_tp2_hit":  "✅✅ الهدف الثاني تم! تم نقل SL للـ TP1",
        "update_near_sl":  "⚠️ تحذير: السعر اقترب من وقف الخسارة",
        "update_sl_moved": "📊 تم تحريك وقف الخسارة للأمان",
        "update_tp3_hit":  "🏆 الهدف الثالث تم! صفقة BTC مغلقة بنجاح 🎉",
        "current_price":   "💵 السعر الحالي",
        "trend_bull":    "📈 الاتجاه: صاعد",
        "trend_bear":    "📉 الاتجاه: هابط",
        "trend_neutral": "➡️ الاتجاه: محايد",
        "rsi_oversold":   "تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought": "تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral":    "منطقة محايدة",
        "macd_bull": "🔹 MACD: زخم صاعد ↗️",
        "macd_bear": "🔹 MACD: زخم هابط ↘️",
        "ema_bull":  "🔹 EMAs: مرتبة صعوداً 📈",
        "ema_bear":  "🔹 EMAs: مرتبة هبوطاً 📉",
        "ema_mixed": "🔹 EMAs: إشارات مختلطة ↔️",
        "bb_low":  "🔹 بولنجر: عند الدعم السفلي",
        "bb_high": "🔹 بولنجر: عند المقاومة العلوية",
        "bb_mid":  "🔹 بولنجر: منتصف النطاق",
        "summary_bull":    "✅ الخلاصة: السوق يميل للصعود",
        "summary_bear":    "✅ الخلاصة: السوق يميل للهبوط",
        "summary_neutral": "✅ الخلاصة: السوق في منطقة تردد",
        "prices_title": "💰 الأسعار الحالية",
        "change_24h":   "التغيير 24h",
        "about_text": """ℹ️ عن بوت أبو مهرة 🐎

⏱️ فريم الساعة (1H) كأساس للصفقات
📐 Fibonacci + ATR للأهداف
📡 إشارات تلقائية كل 30 دقيقة
🔄 مراقبة BTC وتحديث SL/TP كل 5 دقائق
🔬 المؤشرات: RSI, MACD, EMA, BB, Stoch, ATR, Fibonacci
⚙️ توافق 3 فريمات — إشارة عند توافق فريمين+
⚠️ للأغراض التعليمية فقط""",
        "ind_rsi_oversold":   "RSI تشبع بيعي",
        "ind_rsi_buy":        "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي",
        "ind_rsi_sell":       "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️",
        "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up":   "EMAs صاعدة 📈",
        "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low":  "بولنجر: دعم سفلي 🟢",
        "ind_bb_high": "بولنجر: مقاومة عليا 🔴",
        "ind_stoch_low":  "Stochastic تشبع بيعي",
        "ind_stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "welcome": """🐎 Welcome to Abu Mahra Bot! 🐎

━━━━━━━━━━━━━━━━━━━━
Specializing in:
₿ Bitcoin  BTC/USD
🥇 Gold  XAU/USD

✨ Features:
▫️ 1H timeframe based signals
▫️ Fibonacci + ATR targets
▫️ Precise support & resistance
▫️ Auto signals every 30 minutes
▫️ BTC live SL/TP monitoring
━━━━━━━━━━━━━━━━━━━━
⚠️ For educational purposes only""",

        "btn_btc":          "₿ BTC Trade",
        "btn_gold":         "🥇 Gold Trade",
        "btn_analysis_btc": "📈 BTC Analysis",
        "btn_analysis_gold":"📈 Gold Analysis",
        "btn_prices":       "💰 Prices",
        "btn_about":        "ℹ️ About",
        "btn_lang":         "🌐 Language",

        "loading_trade":    "⏳ Analyzing market...",
        "loading_analysis": "⏳ Analyzing...",
        "loading_prices":   "⏳ Fetching prices...",
        "failed":    "❌ Failed to fetch data, try again in a minute",
        "error":     "❌ Error: ",
        "no_signal": "⚪ No clear opportunity right now\nWaiting for stronger signal 🕐",

        "trade_header":    "⚡ 1H Scalp Trade - Abu Mahra",
        "auto_header":     "🔔 Auto Signal - Abu Mahra",
        "update_header":   "🔄 BTC Trade Update - Abu Mahra",
        "analysis_header": "📊 Market Analysis - Abu Mahra",

        "entry":     "💰 Entry Price",
        "fib_entry": "📍 Fib Entry Level",
        "direction": "📌 Trade Type",
        "buy":       "BUY ⬆️",
        "sell":      "SELL ⬇️",
        "targets_section": "🎯 Targets",
        "tp1": "First Target   TP1",
        "tp2": "Second Target  TP2",
        "tp3": "Third Target   TP3",
        "sl":  "Stop Loss      SL",
        "rr":  "⚖️ Reward / Risk",
        "fib_section":   "📐 Fibonacci Levels",
        "leverage":  "🔧 Suggested Leverage",
        "timeframe": "⏱️ Timeframe",
        "hold_time": "⏳ Hold Time",
        "support":    "🟢 Support",
        "resistance": "🔴 Resistance",
        "confluence": "🔗 Timeframe Confluence",
        "frame_1h":  "🕐 1H",
        "frame_4h":  "🕓 4H",
        "frame_1d":  "📅 Daily",
        "full_confluence":    "🔥 Full confluence on 3 timeframes!",
        "partial_confluence": "✅ Confluence on 2 timeframes",
        "no_confluence":      "⚪ No confluence",
        "indicators_section": "📈 Indicators",
        "strength_section":   "💡 Signal Strength",
        "risk_section":       "⚠️ Risk Level",
        "risk_low":      "🟢 Low",
        "risk_med":      "🟡 Medium",
        "risk_high":     "🔴 High",
        "risk_low_msg":  "Good opportunity — Low risk",
        "risk_med_msg":  "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",
        "footer":      "⚠️ For educational purposes only\n📚 Always trade responsibly",
        "updated_gmt": "🕐 Last update (GMT)",
        "update_tp1_hit":  "✅ TP1 reached! SL moved to entry",
        "update_tp2_hit":  "✅✅ TP2 reached! SL moved to TP1",
        "update_near_sl":  "⚠️ Warning: Price approaching Stop Loss",
        "update_sl_moved": "📊 Stop Loss moved to safety",
        "update_tp3_hit":  "🏆 TP3 reached! BTC trade closed successfully 🎉",
        "current_price":   "💵 Current Price",
        "trend_bull":    "📈 Trend: Bullish",
        "trend_bear":    "📉 Trend: Bearish",
        "trend_neutral": "➡️ Trend: Neutral",
        "rsi_oversold":   "Oversold — Possible buying pressure",
        "rsi_overbought": "Overbought — Possible selling pressure",
        "rsi_neutral":    "Neutral zone",
        "macd_bull": "🔹 MACD: Positive momentum ↗️",
        "macd_bear": "🔹 MACD: Negative momentum ↘️",
        "ema_bull":  "🔹 EMAs: Bullish stack 📈",
        "ema_bear":  "🔹 EMAs: Bearish stack 📉",
        "ema_mixed": "🔹 EMAs: Mixed signals ↔️",
        "bb_low":  "🔹 Bollinger: At lower support",
        "bb_high": "🔹 Bollinger: At upper resistance",
        "bb_mid":  "🔹 Bollinger: Middle zone",
        "summary_bull":    "✅ Summary: Market leaning bullish",
        "summary_bear":    "✅ Summary: Market leaning bearish",
        "summary_neutral": "✅ Summary: Market in consolidation",
        "prices_title": "💰 Current Prices",
        "change_24h":   "24h Change",
        "about_text": """ℹ️ About Abu Mahra Bot 🐎

⏱️ 1H timeframe as base
📐 Fibonacci + ATR targets
📡 Auto signals every 30 minutes
🔄 BTC live SL/TP monitoring every 5 minutes
🔬 Indicators: RSI, MACD, EMA, BB, Stoch, ATR, Fibonacci
⚙️ 3 timeframe confluence — signals on 2+ agreement
⚠️ For educational purposes only""",
        "ind_rsi_oversold":   "RSI Oversold",
        "ind_rsi_buy":        "RSI Buy Zone",
        "ind_rsi_overbought": "RSI Overbought",
        "ind_rsi_sell":       "RSI Sell Zone",
        "ind_macd_pos": "MACD Positive ↗️",
        "ind_macd_neg": "MACD Negative ↘️",
        "ind_ema_up":   "EMAs Bullish 📈",
        "ind_ema_down": "EMAs Bearish 📉",
        "ind_bb_low":  "Bollinger: Lower Support 🟢",
        "ind_bb_high": "Bollinger: Upper Resistance 🔴",
        "ind_stoch_low":  "Stochastic Oversold",
        "ind_stoch_high": "Stochastic Overbought",
    }
}

def t(uid, key):
    lang = user_languages.get(uid, "ar")
    return TEXTS[lang].get(key, key)

def gmt_now():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M")


# ==================== البيانات ====================
def get_data(asset="BTC", days=30, interval="hourly"):
    """
    يجيب البيانات من Twelve Data (دقيق) أو CoinGecko (fallback)
    """
    cache_key = str(asset).upper() + "_" + str(days) + "_" + interval
    cached = get_cached(cache_key)
    if cached is not None:
        logger.info("Cache hit: " + cache_key)
        return cached

    # حدد الرمز والفريم لـ Twelve Data
    symbol = "BTC/USD" if asset == "BTC" else "XAU/USD"

    # تحويل الفريم
    if interval == "hourly":
        td_interval = "1h"
        outputsize = min(days * 24, 500)
    elif interval == "daily":
        td_interval = "1day"
        outputsize = min(days, 500)
    else:
        td_interval = "1h"
        outputsize = 200

    # جرب Twelve Data أولاً
    if TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": symbol,
                    "interval": td_interval,
                    "outputsize": outputsize,
                    "apikey": TWELVEDATA_KEY,
                    "format": "JSON"
                },
                timeout=15
            )
            data = r.json()
            if "values" in data and len(data["values"]) > 0:
                rows = []
                for v in reversed(data["values"]):
                    rows.append({
                        "timestamp": pd.to_datetime(v["datetime"]),
                        "Open":   float(v["open"]),
                        "High":   float(v["high"]),
                        "Low":    float(v["low"]),
                        "Close":  float(v["close"]),
                        "Volume": float(v.get("volume", 0)),
                    })
                df = pd.DataFrame(rows)
                df = df.set_index("timestamp")
                result = df.dropna()
                set_cache(cache_key, result)
                logger.info("Twelve Data OK: " + symbol + " " + td_interval)
                return result
            else:
                logger.warning("Twelve Data no values: " + str(data.get("message","")))
        except Exception as e:
            logger.warning("Twelve Data failed: " + str(e))

    # Fallback: CoinGecko
    try:
        coin = "bitcoin" if asset == "BTC" else "tether-gold"
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/" + coin + "/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": interval},
            timeout=15)
        data = r.json()
        df = pd.DataFrame(data["prices"], columns=["timestamp", "Close"])
        df["Volume"] = [v[1] for v in data["total_volumes"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("timestamp")
        df["High"] = df["Close"].rolling(3).max()
        df["Low"]  = df["Close"].rolling(3).min()
        df["Open"] = df["Close"].shift(1)
        result = df.dropna()
        set_cache(cache_key, result)
        logger.info("CoinGecko fallback OK: " + asset)
        return result
    except Exception as e:
        logger.error(asset + " Error: " + str(e))
        return None

def get_btc_price():
    """يجيب سعر BTC الحالي من Twelve Data أو CoinGecko"""
    if TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/price",
                params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY},
                timeout=10)
            data = r.json()
            if "price" in data:
                return float(data["price"])
        except:
            pass
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=10)
        return float(r.json()["bitcoin"]["usd"])
    except:
        return None

def get_prices():
    """يجيب أسعار BTC والذهب مع التغيير 24h"""
    result = {"bitcoin": {}, "tether-gold": {}}

    if TWELVEDATA_KEY:
        try:
            # BTC price
            r1 = requests.get(
                "https://api.twelvedata.com/price",
                params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY},
                timeout=10)
            btc_price = float(r1.json().get("price", 0))

            # Gold price
            r2 = requests.get(
                "https://api.twelvedata.com/price",
                params={"symbol": "XAU/USD", "apikey": TWELVEDATA_KEY},
                timeout=10)
            gold_price = float(r2.json().get("price", 0))

            # BTC 24h change
            r3 = requests.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": "BTC/USD", "interval": "1day", "outputsize": 2, "apikey": TWELVEDATA_KEY},
                timeout=10)
            btc_data = r3.json().get("values", [])
            btc_change = 0
            if len(btc_data) >= 2:
                prev = float(btc_data[1]["close"])
                btc_change = round((btc_price - prev) / prev * 100, 2) if prev > 0 else 0

            # Gold 24h change
            r4 = requests.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": "XAU/USD", "interval": "1day", "outputsize": 2, "apikey": TWELVEDATA_KEY},
                timeout=10)
            gold_data = r4.json().get("values", [])
            gold_change = 0
            if len(gold_data) >= 2:
                prev_g = float(gold_data[1]["close"])
                gold_change = round((gold_price - prev_g) / prev_g * 100, 2) if prev_g > 0 else 0

            result["bitcoin"]      = {"usd": btc_price,  "usd_24h_change": btc_change}
            result["tether-gold"]  = {"usd": gold_price, "usd_24h_change": gold_change}
            return result
        except Exception as e:
            logger.warning("Twelve Data prices failed: " + str(e))

    # Fallback CoinGecko
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether-gold&vs_currencies=usd&include_24hr_change=true",
            timeout=10)
        return r.json()
    except:
        return None


# ==================== Fibonacci ====================
def calculate_fibonacci(df):
    """
    يحسب مستويات Fibonacci من آخر موجة سعرية (swing high/low)
    يستخدم آخر 50 شمعة للبحث عن القمة والقاع
    """
    window = min(50, len(df))
    recent = df.tail(window)
    swing_high = float(recent['High'].max())
    swing_low  = float(recent['Low'].min())
    diff = swing_high - swing_low

    # مستويات الارتداد (Retracement)
    levels = {
        "0.0":   round(swing_high, 2),
        "23.6":  round(swing_high - 0.236 * diff, 2),
        "38.2":  round(swing_high - 0.382 * diff, 2),
        "50.0":  round(swing_high - 0.500 * diff, 2),
        "61.8":  round(swing_high - 0.618 * diff, 2),
        "78.6":  round(swing_high - 0.786 * diff, 2),
        "100.0": round(swing_low, 2),
    }

    # مستويات الامتداد (Extension) للأهداف
    extensions = {
        "127.2": round(swing_low - 0.272 * diff, 2),
        "161.8": round(swing_low - 0.618 * diff, 2),
        "200.0": round(swing_low - 1.000 * diff, 2),
    }

    return levels, extensions, swing_high, swing_low


def find_nearest_fib(price, levels, direction):
    """يجد أقرب مستوى Fibonacci للسعر الحالي"""
    fib_values = list(levels.values())
    nearest = min(fib_values, key=lambda x: abs(x - price))
    fib_key  = [k for k, v in levels.items() if v == nearest][0]
    dist_pct = abs(nearest - price) / price * 100
    return nearest, fib_key, dist_pct


def get_fib_targets(price, levels, extensions, direction, atr):
    """
    يحسب الأهداف بناءً على:
    1. مستويات Fibonacci (الأولوية)
    2. ATR كحد أدنى للمسافة (للتأكد من منطقية الهدف)
    """
    fib_vals = sorted(levels.values())

    if direction == "BUY":
        # SL: تحت أقرب دعم Fib + ATR buffer
        sl_fib = max([v for v in fib_vals if v < price], default=price - atr)
        sl = round(min(sl_fib - 0.2*atr, price - 0.8*atr), 2)

        # TP1: أقرب مقاومة Fib فوق السعر (بحد أدنى 0.5 ATR)
        tp1_candidates = [v for v in fib_vals if v > price + 0.5*atr]
        tp1 = round(tp1_candidates[0] if tp1_candidates else price + 0.8*atr, 2)

        # TP2: المستوى التالي أو 1.5 ATR
        tp2_candidates = [v for v in fib_vals if v > tp1 + 0.3*atr]
        tp2_fib = tp2_candidates[0] if tp2_candidates else price + 1.8*atr
        tp2 = round(max(tp2_fib, price + 1.5*atr), 2)

        # TP3: Extension 127.2% أو 3 ATR
        ext_vals = sorted(extensions.values(), reverse=True)
        tp3_candidates = [v for v in ext_vals if v > tp2 + 0.5*atr]
        tp3 = round(tp3_candidates[0] if tp3_candidates else price + 3.0*atr, 2)

    else:  # SELL
        sl_fib = min([v for v in fib_vals if v > price], default=price + atr)
        sl = round(max(sl_fib + 0.2*atr, price + 0.8*atr), 2)

        tp1_candidates = [v for v in reversed(fib_vals) if v < price - 0.5*atr]
        tp1 = round(tp1_candidates[0] if tp1_candidates else price - 0.8*atr, 2)

        tp2_candidates = [v for v in reversed(fib_vals) if v < tp1 - 0.3*atr]
        tp2_fib = tp2_candidates[0] if tp2_candidates else price - 1.8*atr
        tp2 = round(min(tp2_fib, price - 1.5*atr), 2)

        ext_vals_sell = sorted(extensions.values())
        tp3_candidates = [v for v in ext_vals_sell if v < tp2 - 0.5*atr]
        tp3 = round(tp3_candidates[0] if tp3_candidates else price - 3.0*atr, 2)

    rr = round(abs(tp2-price) / abs(sl-price), 2) if abs(sl-price) > 0 else 0
    return sl, tp1, tp2, tp3, rr


# ==================== التحليل ====================
def calc_indicators(df):
    c = df['Close']; h = df['High']; l = df['Low']
    df['EMA9']  = ta.trend.EMAIndicator(c, window=9).ema_indicator()
    df['EMA21'] = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df['EMA50'] = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df['EMA200']= ta.trend.EMAIndicator(c, window=200).ema_indicator()
    df['RSI']   = ta.momentum.RSIIndicator(c, window=14).rsi()
    macd = ta.trend.MACD(c)
    df['MACD']  = macd.macd()
    df['MACD_S']= macd.macd_signal()
    df['MACD_H']= macd.macd_diff()
    bb = ta.volatility.BollingerBands(c)
    df['BB_U'] = bb.bollinger_hband()
    df['BB_L'] = bb.bollinger_lband()
    df['ATR']  = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    stoch = ta.momentum.StochasticOscillator(h, l, c)
    df['Stoch'] = stoch.stoch()
    df['Stoch_S']= stoch.stoch_signal()
    # Pivot Points
    df['Pivot'] = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df['R1'] = 2 * df['Pivot'] - l.shift(1)
    df['S1'] = 2 * df['Pivot'] - h.shift(1)
    df['R2'] = df['Pivot'] + (h.shift(1) - l.shift(1))
    df['S2'] = df['Pivot'] - (h.shift(1) - l.shift(1))
    # Ichimoku Cloud
    high_9  = h.rolling(window=9).max()
    low_9   = l.rolling(window=9).min()
    high_26 = h.rolling(window=26).max()
    low_26  = l.rolling(window=26).min()
    high_52 = h.rolling(window=52).max()
    low_52  = l.rolling(window=52).min()
    df['Tenkan']  = (high_9  + low_9)  / 2   # Conversion Line
    df['Kijun']   = (high_26 + low_26) / 2   # Base Line
    df['SpanA']   = ((df['Tenkan'] + df['Kijun']) / 2).shift(26)   # Leading Span A
    df['SpanB']   = ((high_52 + low_52) / 2).shift(26)              # Leading Span B
    df['Chikou']  = c.shift(-26)                                     # Lagging Span
    return df

def analyze_frame(df, uid=0):
    df = calc_indicators(df)
    last  = df.iloc[-1]
    price = last['Close']
    sb = ss = 0
    details = []
    rsi = last['RSI']

    # RSI
    if rsi < 30:   sb += 25; details.append(t(uid,'ind_rsi_oversold') + " (" + str(round(rsi,1)) + ") 🟢")
    elif rsi < 45: sb += 12; details.append(t(uid,'ind_rsi_buy') + " (" + str(round(rsi,1)) + ")")
    elif rsi > 70: ss += 25; details.append(t(uid,'ind_rsi_overbought') + " (" + str(round(rsi,1)) + ") 🔴")
    elif rsi > 55: ss += 12; details.append(t(uid,'ind_rsi_sell') + " (" + str(round(rsi,1)) + ")")

    # MACD
    if last['MACD'] > last['MACD_S'] and last['MACD_H'] > 0:
        sb += 20; details.append(t(uid,'ind_macd_pos'))
    elif last['MACD'] < last['MACD_S'] and last['MACD_H'] < 0:
        ss += 20; details.append(t(uid,'ind_macd_neg'))

    # EMA Stack
    if last['EMA9'] > last['EMA21'] > last['EMA50']:
        sb += 20; details.append(t(uid,'ind_ema_up'))
    elif last['EMA9'] < last['EMA21'] < last['EMA50']:
        ss += 20; details.append(t(uid,'ind_ema_down'))

    # EMA200 - اتجاه عام
    if price > last['EMA200']:
        sb += 10
    else:
        ss += 10

    # Bollinger
    if price <= last['BB_L']:   sb += 15; details.append(t(uid,'ind_bb_low'))
    elif price >= last['BB_U']: ss += 15; details.append(t(uid,'ind_bb_high'))

    # Stochastic
    if last['Stoch'] < 20 and last['Stoch_S'] < 20:
        sb += 10; details.append(t(uid,'ind_stoch_low'))
    elif last['Stoch'] > 80 and last['Stoch_S'] > 80:
        ss += 10; details.append(t(uid,'ind_stoch_high'))

    # Ichimoku signals
    try:
        tenkan = last['Tenkan']; kijun = last['Kijun']
        span_a = last['SpanA'];  span_b = last['SpanB']
        cloud_top = max(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
        cloud_bot = min(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
        ichi_bull = False; ichi_bear = False

        if cloud_top and cloud_bot:
            if price > cloud_top and tenkan > kijun:
                sb += 15; ichi_bull = True
                details.append("☁️ Ichimoku: فوق السحابة + TK صاعد")
            elif price < cloud_bot and tenkan < kijun:
                ss += 15; ichi_bear = True
                details.append("☁️ Ichimoku: تحت السحابة + TK هابط")
            elif cloud_top > cloud_bot:
                sb += 5   # سحابة خضراء
            else:
                ss += 5   # سحابة حمراء
    except:
        ichi_bull = False; ichi_bear = False

    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf  = round(max(sb, ss) / total * 100) if total > 0 else 50

    return {
        "direction": direction, "conf": conf, "sb": sb, "ss": ss,
        "rsi": round(rsi, 1), "price": round(price, 2),
        "atr": round(last['ATR'], 2),
        "details": details[:4],
        "support":    round(last['S1'], 2),
        "resistance": round(last['R1'], 2),
        "macd_bull": last['MACD'] > last['MACD_S'],
        "ema_bull": last['EMA9'] > last['EMA21'] > last['EMA50'],
        "ema_bear": last['EMA9'] < last['EMA21'] < last['EMA50'],
        "bb_zone":  "low" if price <= last['BB_L'] else "high" if price >= last['BB_U'] else "mid",
        "ichi_bull": ichi_bull, "ichi_bear": ichi_bear,
    }


def full_analysis(asset="BTC", uid=0):
    """
    تحليل 3 فريمات: 1H (أساس) + 4H + 1D
    مع Fibonacci + ATR للأهداف
    """
    # جلب البيانات - فريم الساعة كأساس
    df_1h = get_data(asset, days=14,  interval="hourly")
    df_4h = get_data(asset, days=30,  interval="hourly")   # نأخذ hourly ونعيد تجميعه
    df_1d = get_data(asset, days=90,  interval="daily")

    # تحويل الساعي لـ 4H
    if df_4h is not None and len(df_4h) > 0:
        try:
            df_4h = df_4h.resample('4h').agg({
                'Open':'first','High':'max','Low':'min',
                'Close':'last','Volume':'sum'
            }).dropna()
        except:
            df_4h = None

    frames = {"1h": df_1h, "4h": df_4h, "1d": df_1d}
    results = {}
    for label, df in frames.items():
        if df is not None and len(df) >= 20:
            results[label] = analyze_frame(df, uid)

    if len(results) < 2:
        return None

    buy_c = sum(1 for r in results.values() if r['direction'] == "BUY")
    sel_c = sum(1 for r in results.values() if r['direction'] == "SELL")

    if buy_c == 3:   final="BUY";  conf_txt=t(uid,"full_confluence");    base_conf=92
    elif buy_c == 2: final="BUY";  conf_txt=t(uid,"partial_confluence"); base_conf=74
    elif sel_c == 3: final="SELL"; conf_txt=t(uid,"full_confluence");    base_conf=92
    elif sel_c == 2: final="SELL"; conf_txt=t(uid,"partial_confluence"); base_conf=74
    else:
        # حتى لو NEUTRAL نرجع تحليل كامل للعرض
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h) if (df_1h is not None and len(df_1h)>=20) else ({},{},0,0)
        nf2, fk2, dp2 = find_nearest_fib(main2['price'], fib_l2, "NEUTRAL") if fib_l2 else (main2['price'],"50.0",0)
        kf2 = ["📐 Fib "+k+"%:  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x: float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            icon = "🟢" if r['direction']=="BUY" else "🔴"
            fl2.append(icon+" "+icons2.get(k,"")+": "+r['direction']+" ("+str(r['conf'])+"%)")
        return {
            "final":"NEUTRAL","asset":asset,
            "confluence_txt":t(uid,"no_confluence"),"base_conf":0,
            "price":main2['price'],"tp1":0,"tp2":0,"tp3":0,"sl":0,"rr":0,"atr":main2['atr'],
            "risk_pct":50,"risk_label":t(uid,"risk_med"),"risk_msg":t(uid,"risk_med_msg"),
            "frame_lines":fl2,"ind_details":main2['details'],
            "rsi":main2['rsi'],"support":main2['support'],"resistance":main2['resistance'],
            "macd_bull":main2['macd_bull'],"ema_bull":main2['ema_bull'],
            "ema_bear":main2['ema_bear'],"bb_zone":main2['bb_zone'],
            "fib_levels":fib_l2,"fib_ext":fib_e2,"key_fibs":kf2,
            "nearest_fib":nf2,"fib_key":fk2,
            "swing_h":sh2,"swing_l":sl2,
            "leverage_ar":"","leverage_en":"","tf_ar":"","tf_en":"","hold_ar":"","hold_en":"",
        }

    # استخدم فريم الساعة كأساس للسعر والـ ATR
    main  = results.get("1h") or list(results.values())[0]
    price = main['price']
    atr   = main['atr']

    # ====== حساب Fibonacci ======
    if df_1h is not None and len(df_1h) >= 20:
        fib_levels, fib_ext, swing_h, swing_l = calculate_fibonacci(df_1h)
    else:
        fib_levels, fib_ext, swing_h, swing_l = {}, {}, price*1.02, price*0.98

    # إيجاد أقرب مستوى Fib للسعر الحالي
    nearest_fib, fib_key, dist_pct = find_nearest_fib(price, fib_levels, final)

    # ====== الأهداف: Fibonacci + ATR ======
    sl, tp1, tp2, tp3, rr = get_fib_targets(price, fib_levels, fib_ext, final, atr)

    # درجة المخاطرة
    risk = 100 - base_conf
    if main['rsi'] < 25 or main['rsi'] > 75: risk += 10
    if dist_pct > 2: risk += 5  # لو بعيد عن Fib مهم
    risk = min(risk, 99)
    if risk < 30:   rl=t(uid,"risk_low");  rm=t(uid,"risk_low_msg")
    elif risk < 55: rl=t(uid,"risk_med");  rm=t(uid,"risk_med_msg")
    else:           rl=t(uid,"risk_high"); rm=t(uid,"risk_high_msg")

    lang = user_languages.get(uid, "ar")
    frame_lines = []
    icons = {"1h": t(uid,"frame_1h"), "4h": t(uid,"frame_4h"), "1d": t(uid,"frame_1d")}
    for k, r in results.items():
        icon = "🟢" if r['direction'] == "BUY" else "🔴"
        frame_lines.append(icon + " " + icons.get(k,'') + ": " + r['direction'] + " (" + str(r['conf']) + "%)")

    # أهم مستويات Fib للعرض
    key_fibs = []
    for pct, val in sorted(fib_levels.items(), key=lambda x: float(x[0])):
        key_fibs.append("📐 Fib " + pct + "%:  $" + "{:,.2f}".format(val))

    return {
        "final": final, "asset": asset,
        "confluence_txt": conf_txt, "base_conf": base_conf,
        "price": price, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": atr,
        "risk_pct": risk, "risk_label": rl, "risk_msg": rm,
        "frame_lines": frame_lines, "ind_details": main['details'],
        "rsi": main['rsi'],
        "support": main['support'], "resistance": main['resistance'],
        "macd_bull": main['macd_bull'], "ema_bull": main['ema_bull'],
        "ema_bear": main['ema_bear'], "bb_zone": main['bb_zone'],
        "fib_levels": fib_levels, "fib_ext": fib_ext,
        "key_fibs": key_fibs[:5],
        "nearest_fib": nearest_fib, "fib_key": fib_key,
        "swing_h": swing_h, "swing_l": swing_l,
        "leverage_ar": "10x — 15x\n⚠️ لا تتجاوز 15x للمبتدئين",
        "leverage_en": "10x — 15x\n⚠️ Max 15x for beginners",
        "tf_ar": "1 ساعة", "tf_en": "1 Hour",
        "hold_ar": "2 — 8 ساعات", "hold_en": "2 — 8 Hours",
    }


# ==================== بناء الرسائل ====================
def build_trade_msg(res, uid=0, auto=False):
    emoji   = "🟢" if res['final'] == "BUY" else "🔴"
    dir_txt = t(uid,"buy") if res['final'] == "BUY" else t(uid,"sell")
    ai      = "₿" if res['asset'] == "BTC" else "🥇"
    an      = "BTC/USD" if res['asset'] == "BTC" else "XAU/USD"
    conf    = res['base_conf']
    bar     = "█" * (conf//10) + "░" * (10-conf//10)
    header  = t(uid,"auto_header") if auto else t(uid,"trade_header")
    lang    = user_languages.get(uid, "ar")
    leverage = res['leverage_ar'] if lang == "ar" else res['leverage_en']
    tf       = res['tf_ar']       if lang == "ar" else res['tf_en']
    hold     = res['hold_ar']     if lang == "ar" else res['hold_en']

    # Ichimoku status
    ichi_status = ""
    if res.get('frame_lines'):
        pass  # will show in confluence

    lines = [
        "┌─────────────────────────┐",
        "│  " + emoji*2 + "  " + ai + " " + an + "  " + emoji*2 + "  │",
        "└─────────────────────────┘",
        "📋 " + header,
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        t(uid,'direction') + ":  " + dir_txt,
        t(uid,'entry') + ":  $" + "{:,.2f}".format(res['price']),
        t(uid,'fib_entry') + ":  Fib " + res['fib_key'] + "% ($" + "{:,.2f}".format(res['nearest_fib']) + ")",
        "",
        "━━━━  " + t(uid,'targets_section') + "  ━━━━",
        "✅  " + t(uid,'tp1') + "  »  $" + "{:,.2f}".format(res['tp1']),
        "✅  " + t(uid,'tp2') + "  »  $" + "{:,.2f}".format(res['tp2']),
        "✅  " + t(uid,'tp3') + "  »  $" + "{:,.2f}".format(res['tp3']),
        "🛑  " + t(uid,'sl')  + "  »   $" + "{:,.2f}".format(res['sl']),
        t(uid,'rr') + ":  1:" + str(res['rr']),
        "",
        "━━━━  " + t(uid,'fib_section') + "  ━━━━",
    ]
    lines += res['key_fibs']
    lines += [
        "",
        "━━━━  " + t(uid,'leverage') + "  ━━━━",
        leverage,
        t(uid,'timeframe') + ":  " + tf,
        t(uid,'hold_time') + ":  " + hold,
        "",
        "━━━━  " + t(uid,'support') + " / " + t(uid,'resistance') + "  ━━━━",
        "🟢 $" + "{:,.2f}".format(res['support']) + "  |  🔴 $" + "{:,.2f}".format(res['resistance']),
        "",
        "━━━━  " + t(uid,'confluence') + "  ━━━━",
    ]
    lines += res['frame_lines']
    lines.append(res['confluence_txt'])
    lines += [
        "",
        "━━━━  " + t(uid,'indicators_section') + "  ━━━━",
        "🔹 RSI: " + str(res['rsi']),
    ]
    for d in res['ind_details']:
        lines.append("▫️ " + d)
    lines += [
        "",
        "━━━━  " + t(uid,'strength_section') + "  ━━━━",
        bar + "  " + str(conf) + "%",
        "",
        "━━━━  " + t(uid,'risk_section') + "  ━━━━",
        res['risk_label'] + "  •  " + str(res['risk_pct']) + "%",
        res['risk_msg'],
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        t(uid,'updated_gmt') + ":  " + gmt_now(),
        t(uid,'footer'),
    ]
    return "\n".join(lines)


def build_update_msg(trade, current_price, update_type, uid=0):
    dir_txt = t(uid,"buy") if trade['direction'] == "BUY" else t(uid,"sell")
    lines = [
        "🔄  ₿ BTC/USD  •  " + t(uid,'update_header'),
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        t(uid,'direction') + ":  " + dir_txt,
        t(uid,'entry') + ":  $" + "{:,.2f}".format(trade['entry']),
        t(uid,'current_price') + ":  $" + "{:,.2f}".format(current_price),
        "",
        update_type,
        "",
        "✅ TP1 »  $" + "{:,.2f}".format(trade['tp1']),
        "✅ TP2 »  $" + "{:,.2f}".format(trade['tp2']),
        "✅ TP3 »  $" + "{:,.2f}".format(trade['tp3']),
        "🛑 SL  »  $" + "{:,.2f}".format(trade['sl']),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        t(uid,'updated_gmt') + ":  " + gmt_now(),
        t(uid,'footer'),
    ]
    return "\n".join(lines)


def build_analysis_msg(res, uid=0):
    ai = "₿" if res['asset'] == "BTC" else "🥇"
    an = "BTC/USD" if res['asset'] == "BTC" else "XAU/USD"
    if res['final'] == "BUY" and res['base_conf'] > 60:
        trend = t(uid,"trend_bull"); summary = t(uid,"summary_bull")
    elif res['final'] == "SELL" and res['base_conf'] > 60:
        trend = t(uid,"trend_bear"); summary = t(uid,"summary_bear")
    else:
        trend = t(uid,"trend_neutral"); summary = t(uid,"summary_neutral")

    rsi     = res['rsi']
    rsi_txt = t(uid,"rsi_oversold") if rsi < 30 else t(uid,"rsi_overbought") if rsi > 70 else t(uid,"rsi_neutral")
    macd_txt= t(uid,"macd_bull") if res['macd_bull'] else t(uid,"macd_bear")
    ema_txt = t(uid,"ema_bull") if res['ema_bull'] else t(uid,"ema_bear") if res['ema_bear'] else t(uid,"ema_mixed")
    bb_txt  = t(uid,"bb_low") if res['bb_zone']=="low" else t(uid,"bb_high") if res['bb_zone']=="high" else t(uid,"bb_mid")

    lines = [
        "📊  " + ai + " " + an,
        t(uid,'analysis_header'),
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        trend,
        "💵 " + t(uid,'entry') + ":  $" + "{:,.2f}".format(res['price']),
        t(uid,'support') + ":  $" + "{:,.2f}".format(res['support']),
        t(uid,'resistance') + ":  $" + "{:,.2f}".format(res['resistance']),
        "",
        "━━━━  " + t(uid,'fib_section') + "  ━━━━",
    ]
    lines += res['key_fibs']
    lines += [
        "",
        "━━━━  " + t(uid,'confluence') + "  ━━━━",
    ]
    lines += res['frame_lines']
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔹 RSI (" + str(rsi) + "):  " + rsi_txt,
        macd_txt, ema_txt, bb_txt,
        "",
        summary,
        "",
        t(uid,'updated_gmt') + ":  " + gmt_now(),
        t(uid,'footer'),
    ]
    return "\n".join(lines)


# ==================== لوحات المفاتيح ====================
def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_btc"),  callback_data='trade_BTC'),
         InlineKeyboardButton(t(uid,"btn_gold"), callback_data='trade_GOLD')],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"),  callback_data='analysis_BTC'),
         InlineKeyboardButton(t(uid,"btn_analysis_gold"), callback_data='analysis_GOLD')],
        [InlineKeyboardButton(t(uid,"btn_prices"), callback_data='prices'),
         InlineKeyboardButton(t(uid,"btn_about"),  callback_data='about')],
        [InlineKeyboardButton(t(uid,"btn_lang"), callback_data='change_lang')]
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data='lang_ar'),
        InlineKeyboardButton("English",  callback_data='lang_en')
    ]])


# ==================== هاندلرز ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_languages:
        await update.message.reply_text(
            "🐎 Abu Mahra Bot\n\nاختر لغتك / Choose your language:",
            reply_markup=lang_keyboard()
        )
    else:
        await update.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text or ""
    kb   = main_keyboard(uid) if uid in user_languages else lang_keyboard()
    lang = user_languages.get(uid, "ar")
    if any(g in text.lower() for g in GREETINGS):
        reply = random.choice(REPLIES_AR if lang == "ar" else REPLIES_EN)
    else:
        reply = random.choice(CONFUSED_AR if lang == "ar" else CONFUSED_EN)
    await update.message.reply_text(reply, reply_markup=kb)


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    await query.answer()

    if data == 'lang_ar':
        user_languages[uid] = "ar"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == 'lang_en':
        user_languages[uid] = "en"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == 'change_lang':
        await query.message.reply_text(t(uid,"choose_lang"), reply_markup=lang_keyboard())

    elif data.startswith('trade_'):
        asset = data.split('_')[1]
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            res = full_analysis(asset, uid)
            if not res or res['final'] == "NEUTRAL":
                await query.message.reply_text(t(uid,"no_signal")); return
            await query.message.reply_text(build_trade_msg(res, uid))
            if asset == "BTC":
                active_btc_trade['data'] = {
                    "asset": "BTC", "direction": res['final'],
                    "entry": res['price'], "sl": res['sl'],
                    "tp1": res['tp1'], "tp2": res['tp2'], "tp3": res['tp3'],
                    "atr": res['atr'], "tp1_hit": False, "tp2_hit": False,
                    "chat_id": query.message.chat_id,
                }
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data.startswith('analysis_'):
        asset = data.split('_')[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            res = full_analysis(asset, uid)
            if not res or 'key_fibs' not in res:
                await query.message.reply_text(t(uid,"failed")); return
            await query.message.reply_text(build_analysis_msg(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == 'prices':
        try:
            d    = get_prices()
            btc  = d.get('bitcoin', {})
            gold = d.get('tether-gold', {})
            bp = btc.get('usd',0);  bc = btc.get('usd_24h_change',0)
            gp = gold.get('usd',0); gc = gold.get('usd_24h_change',0)
            lines = [
                t(uid,'prices_title'),
                "━━━━━━━━━━━━━━━━━━━━",
                "₿ BTC/USD:  $" + "{:,.0f}".format(bp),
                ("📈" if bc > 0 else "📉") + " " + t(uid,'change_24h') + ":  " + "{:+.2f}".format(bc) + "%",
                "",
                "🥇 XAU/USD:  $" + "{:,.2f}".format(gp),
                ("📈" if gc > 0 else "📉") + " " + t(uid,'change_24h') + ":  " + "{:+.2f}".format(gc) + "%",
                "",
                t(uid,'updated_gmt') + ":  " + gmt_now(),
            ]
            await query.message.reply_text("\n".join(lines))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == 'about':
        await query.message.reply_text(t(uid,"about_text"))


# ==================== إشارات تلقائية ====================
async def auto_signals(context):
    try:
        for asset in ["BTC", "GOLD"]:
            res = full_analysis(asset, 0)
            if res and res['final'] != "NEUTRAL" and res['base_conf'] >= MIN_CONFIDENCE:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=build_trade_msg(res, 0, auto=True)
                )
                if asset == "BTC":
                    active_btc_trade['data'] = {
                        "asset": "BTC", "direction": res['final'],
                        "entry": res['price'], "sl": res['sl'],
                        "tp1": res['tp1'], "tp2": res['tp2'], "tp3": res['tp3'],
                        "atr": res['atr'], "tp1_hit": False, "tp2_hit": False,
                        "chat_id": CHANNEL_ID,
                    }
                logger.info("✅ " + asset + " Auto - " + str(res['base_conf']) + "%")
    except Exception as e:
        logger.error("❌ Auto: " + str(e))


# ==================== مراقبة BTC فقط ====================
async def monitor_btc(context):
    if 'data' not in active_btc_trade:
        return
    trade = active_btc_trade['data']
    try:
        current = get_btc_price()
        if not current: return

        entry=trade['entry']; sl=trade['sl']
        tp1=trade['tp1']; tp2=trade['tp2']; tp3=trade['tp3']
        atr=trade['atr']; direction=trade['direction']
        chat_id=trade['chat_id']; uid=0
        update_msg = None

        if direction == "BUY":
            if not trade['tp1_hit'] and current >= tp1:
                trade['tp1_hit'] = True; trade['sl'] = entry
                update_msg = t(uid,"update_tp1_hit")
            elif not trade['tp2_hit'] and current >= tp2:
                trade['tp2_hit'] = True; trade['sl'] = tp1
                update_msg = t(uid,"update_tp2_hit")
            elif current <= sl * 1.002:
                update_msg = t(uid,"update_near_sl")
            elif trade['tp1_hit'] and current > tp1 + 0.5*atr:
                new_sl = round(current - 0.8*atr, 2)
                if new_sl > trade['sl']:
                    trade['sl'] = new_sl
                    update_msg = t(uid,"update_sl_moved")
            if current >= tp3:
                update_msg = t(uid,"update_tp3_hit")
                active_btc_trade.clear()
        else:
            if not trade['tp1_hit'] and current <= tp1:
                trade['tp1_hit'] = True; trade['sl'] = entry
                update_msg = t(uid,"update_tp1_hit")
            elif not trade['tp2_hit'] and current <= tp2:
                trade['tp2_hit'] = True; trade['sl'] = tp1
                update_msg = t(uid,"update_tp2_hit")
            elif current >= sl * 0.998:
                update_msg = t(uid,"update_near_sl")
            elif trade['tp1_hit'] and current < tp1 - 0.5*atr:
                new_sl = round(current + 0.8*atr, 2)
                if new_sl < trade['sl']:
                    trade['sl'] = new_sl
                    update_msg = t(uid,"update_sl_moved")
            if current <= tp3:
                update_msg = t(uid,"update_tp3_hit")
                active_btc_trade.clear()

        if update_msg:
            await context.bot.send_message(
                chat_id=chat_id,
                text=build_update_msg(trade, current, update_msg, uid)
            )
            logger.info("🔄 BTC Update: " + str(update_msg))

    except Exception as e:
        logger.error("❌ Monitor: " + str(e))



# ==================== تنبيهات ذكية ====================
async def send_smart_alerts(context):
    """يبعث تنبيهات ذكية عند مستويات مهمة"""
    try:
        for asset in ["BTC", "GOLD"]:
            df = get_data(asset, days=7, interval="hourly")
            if df is None or len(df) < 30:
                continue

            df = calc_indicators(df)
            last  = df.iloc[-1]
            price = last['Close']
            rsi   = last['RSI']
            atr   = last['ATR']

            # حساب Fibonacci
            fib_levels, _, _, _ = calculate_fibonacci(df)
            ai = "₿ BTC/USD" if asset == "BTC" else "🥇 XAU/USD"
            alerts = []

            # تنبيه RSI
            if rsi < 28:
                alerts.append("🔴 RSI في تشبع بيعي قوي (" + str(round(rsi,1)) + ") — فرصة شراء محتملة!")
            elif rsi > 72:
                alerts.append("🔴 RSI في تشبع شرائي قوي (" + str(round(rsi,1)) + ") — احتمال انعكاس!")

            # تنبيه Fib
            for pct, level in fib_levels.items():
                dist = abs(price - level) / price * 100
                if dist < 0.3:  # قريب من مستوى Fib بنسبة 0.3%
                    direction_txt = "فوق" if price > level else "تحت"
                    alerts.append("📐 السعر عند مستوى Fib " + pct + "% ($" + "{:,.2f}".format(level) + ") — مستوى مهم!")
                    break

            # تنبيه Ichimoku
            try:
                tenkan = last['Tenkan']; kijun = last['Kijun']
                if abs(tenkan - kijun) / price * 100 < 0.2:
                    alerts.append("☁️ Ichimoku: Tenkan و Kijun على وشك التقاطع — انتبه!")
            except:
                pass

            # تنبيه Bollinger Squeeze
            bb_width = (last['BB_U'] - last['BB_L']) / last['BB_U'] * 100
            if bb_width < 2:
                alerts.append("💥 Bollinger Squeeze — حركة قوية قادمة قريباً!")

            if alerts:
                msg_lines = [
                    "⚡ تنبيه ذكي — " + ai,
                    "━━━━━━━━━━━━━━━━━━━━━━━━",
                    "💵 السعر الحالي: $" + "{:,.2f}".format(price),
                    "",
                ]
                for a in alerts:
                    msg_lines.append("▫️ " + a)
                msg_lines += [
                    "",
                    "🕐 " + gmt_now(),
                    "⚠️ للأغراض التعليمية فقط",
                ]
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=chr(10).join(msg_lines)
                )
                logger.info("⚡ Smart Alert sent: " + asset)

    except Exception as e:
        logger.error("❌ Smart Alerts: " + str(e))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_signals, interval=AUTO_INTERVAL_MIN*60, first=30)
    app.job_queue.run_repeating(monitor_btc,    interval=MONITOR_MIN*60,       first=60)
    app.job_queue.run_repeating(send_smart_alerts, interval=45*60,                first=120)  # كل 45 دقيقة
    logger.info("🐎 Abu Mahra Bot - Fibonacci Edition!")
    app.run_polling()

if __name__ == "__main__":
    main()
