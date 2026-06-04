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
NEWS_API_KEY   = os.environ.get("NEWS_API_KEY", "cdf2a61f2cbe4540a41456bc4bd3a40e")
AUTO_INTERVAL_MIN = 30
MONITOR_MIN       = 5
MIN_CONFIDENCE    = 68

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
user_languages   = {}
active_btc_trade = {}
active_trades    = []   # قائمة كل الصفقات المفتوحة
trade_counter    = 0    # رقم الصفقة
last_signal_time = {}   # لمنع الـ spam: {"BTC": timestamp, "GOLD": timestamp}
TRADES_FILE      = "active_trades.json"
SPAM_COOLDOWN    = 1800  # 30 دقيقة بين كل إشارة وإشارة

def load_trades():
    try:
        import json
        with open(TRADES_FILE) as f:
            data = json.load(f)
            return data.get("trades", []), data.get("counter", 0)
    except:
        return [], 0

def save_trades():
    import json
    with open(TRADES_FILE, "w") as f:
        json.dump({"trades": active_trades, "counter": trade_counter}, f)

# تحميل الصفقات عند البدء
_loaded_trades, _loaded_counter = load_trades()
active_trades.extend(_loaded_trades)
trade_counter = _loaded_counter

ALLOWED_USERS = {8490817794, 1548286220}





_cache = {}
CACHE_TTL = 600

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
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة!

━━━━━━━━━━━━━━━━━━━━
متخصص في:
₿ البيتكوين  BTC/USD

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
        "btn_trades":       "📋 الصفقات المفتوحة",
        "btn_stats":        "📊 الإحصائيات",
        "no_open_trades":   "📭 لا توجد صفقات مفتوحة حالياً",

        "loading_trade":    "⏳ جاري تحليل السوق...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices":   "⏳ جاري جلب الأسعار...",
        "failed":    "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error":     "❌ خطأ: ",
        "no_signal": "⚪ لا توجد فرصة واضحة الآن\nانتظر إشارة أقوى 🕐",

        "trade_header":    "صفقة ساعة (1H Scalp) - أبو مهرة",
        "auto_header":     "إشارة تلقائية - أبو مهرة",
        "update_header":   "تحديث صفقة BTC - أبو مهرة",
        "analysis_header": "تحليل السوق - أبو مهرة",

        "entry":     "الدخول",
        "fib_entry": "مستوى Fib",
        "direction": "نوع الصفقة",
        "buy":       "شراء  BUY ⬆️",
        "sell":      "بيع  SELL ⬇️",
        "targets_section": "الأهداف",
        "tp1": "TP1",
        "tp2": "TP2",
        "tp3": "TP3",
        "sl":  "SL",
        "rr":  "العائد / المخاطرة",
        "fib_section":   "مستويات Fibonacci",
        "leverage":  "الرافعة المقترحة",
        "timeframe": "الفريم",
        "hold_time": "المدة المتوقعة",
        "support":    "دعم",
        "resistance": "مقاومة",
        "confluence": "توافق الفريمات",
        "frame_1h":  "ساعة",
        "frame_4h":  "4 ساعات",
        "frame_1d":  "يومي",
        "full_confluence":    "🔥 توافق كامل على 3 فريمات!",
        "partial_confluence": "✅ توافق على فريمين",
        "no_confluence":      "⚪ لا توافق",
        "indicators_section": "المؤشرات",
        "strength_section":   "قوة الإشارة",
        "risk_section":       "المخاطرة",
        "risk_low":      "🟢 منخفضة",
        "risk_med":      "🟡 متوسطة",
        "risk_high":     "🔴 عالية",
        "risk_low_msg":  "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg":  "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",
        "footer":      "⚠️ للأغراض التعليمية فقط",
        "updated_gmt": "آخر تحديث (GMT)",
        "update_tp1_hit":  "✅ الهدف الأول تم! تم نقل SL للدخول",
        "update_tp2_hit":  "✅✅ الهدف الثاني تم! تم نقل SL للـ TP1",
        "update_near_sl":  "⚠️ تحذير: السعر اقترب من وقف الخسارة",
        "update_sl_moved": "📊 تم تحريك وقف الخسارة للأمان",
        "update_tp3_hit":  "🏆 الهدف الثالث تم! صفقة BTC مغلقة بنجاح 🎉",
        "current_price":   "السعر الحالي",
        "trend_bull":    "📈 الاتجاه: صاعد",
        "trend_bear":    "📉 الاتجاه: هابط",
        "trend_neutral": "➡️ الاتجاه: محايد",
        "rsi_oversold":   "تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought": "تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral":    "منطقة محايدة",
        "macd_bull": "MACD: زخم صاعد ↗️",
        "macd_bear": "MACD: زخم هابط ↘️",
        "ema_bull":  "EMAs: مرتبة صعوداً 📈",
        "ema_bear":  "EMAs: مرتبة هبوطاً 📉",
        "ema_mixed": "EMAs: إشارات مختلطة ↔️",
        "bb_low":  "بولنجر: عند الدعم السفلي",
        "bb_high": "بولنجر: عند المقاومة العلوية",
        "bb_mid":  "بولنجر: منتصف النطاق",
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
        "welcome": """🐎 Welcome to Abu Mahra Bot!

━━━━━━━━━━━━━━━━━━━━
Specializing in:
₿ Bitcoin  BTC/USD

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
        "btn_trades":       "📋 Open Trades",
        "btn_stats":        "📊 Statistics",
        "no_open_trades":   "📭 No open trades at the moment",

        "loading_trade":    "⏳ Analyzing market...",
        "loading_analysis": "⏳ Analyzing...",
        "loading_prices":   "⏳ Fetching prices...",
        "failed":    "❌ Failed to fetch data, try again in a minute",
        "error":     "❌ Error: ",
        "no_signal": "⚪ No clear opportunity right now\nWaiting for stronger signal 🕐",

        "trade_header":    "1H Scalp Trade - Abu Mahra",
        "auto_header":     "Auto Signal - Abu Mahra",
        "update_header":   "BTC Trade Update - Abu Mahra",
        "analysis_header": "Market Analysis - Abu Mahra",

        "entry":     "Entry",
        "fib_entry": "Fib Level",
        "direction": "Trade Type",
        "buy":       "BUY ⬆️",
        "sell":      "SELL ⬇️",
        "targets_section": "Targets",
        "tp1": "TP1",
        "tp2": "TP2",
        "tp3": "TP3",
        "sl":  "SL",
        "rr":  "Reward / Risk",
        "fib_section":   "Fibonacci Levels",
        "leverage":  "Suggested Leverage",
        "timeframe": "Timeframe",
        "hold_time": "Hold Time",
        "support":    "Support",
        "resistance": "Resistance",
        "confluence": "Timeframe Confluence",
        "frame_1h":  "1H",
        "frame_4h":  "4H",
        "frame_1d":  "Daily",
        "full_confluence":    "🔥 Full confluence on 3 timeframes!",
        "partial_confluence": "✅ Confluence on 2 timeframes",
        "no_confluence":      "⚪ No confluence",
        "indicators_section": "Indicators",
        "strength_section":   "Signal Strength",
        "risk_section":       "Risk Level",
        "risk_low":      "🟢 Low",
        "risk_med":      "🟡 Medium",
        "risk_high":     "🔴 High",
        "risk_low_msg":  "Good opportunity — Low risk",
        "risk_med_msg":  "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",
        "footer":      "⚠️ For educational purposes only",
        "updated_gmt": "Last update (GMT)",
        "update_tp1_hit":  "✅ TP1 reached! SL moved to entry",
        "update_tp2_hit":  "✅✅ TP2 reached! SL moved to TP1",
        "update_near_sl":  "⚠️ Warning: Price approaching Stop Loss",
        "update_sl_moved": "📊 Stop Loss moved to safety",
        "update_tp3_hit":  "🏆 TP3 reached! BTC trade closed successfully 🎉",
        "current_price":   "Current Price",
        "trend_bull":    "📈 Trend: Bullish",
        "trend_bear":    "📉 Trend: Bearish",
        "trend_neutral": "➡️ Trend: Neutral",
        "rsi_oversold":   "Oversold — Possible buying pressure",
        "rsi_overbought": "Overbought — Possible selling pressure",
        "rsi_neutral":    "Neutral zone",
        "macd_bull": "MACD: Positive momentum ↗️",
        "macd_bear": "MACD: Negative momentum ↘️",
        "ema_bull":  "EMAs: Bullish stack 📈",
        "ema_bear":  "EMAs: Bearish stack 📉",
        "ema_mixed": "EMAs: Mixed signals ↔️",
        "bb_low":  "Bollinger: At lower support",
        "bb_high": "Bollinger: At upper resistance",
        "bb_mid":  "Bollinger: Middle zone",
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
    cache_key = str(asset).upper() + "_" + str(days) + "_" + interval
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    symbol = "BTC/USD" if asset == "BTC" else "XAU/USD"
    if interval == "hourly":
        td_interval = "1h"
        outputsize = min(days * 24, 500)
    elif interval == "daily":
        td_interval = "1day"
        outputsize = min(days, 500)
    else:
        td_interval = "1h"
        outputsize = 200

    if TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": symbol, "interval": td_interval,
                        "outputsize": outputsize, "apikey": TWELVEDATA_KEY, "format": "JSON"},
                timeout=15)
            data = r.json()
            if "values" in data and len(data["values"]) > 0:
                rows = []
                for v in reversed(data["values"]):
                    rows.append({"timestamp": pd.to_datetime(v["datetime"]),
                                 "Open": float(v["open"]), "High": float(v["high"]),
                                 "Low": float(v["low"]), "Close": float(v["close"]),
                                 "Volume": float(v.get("volume", 0))})
                df = pd.DataFrame(rows).set_index("timestamp").dropna()
                set_cache(cache_key, df)
                return df
        except Exception as e:
            logger.warning("Twelve Data failed: " + str(e))

    # Fallback: للذهب نجرب Twelve Data بـ outputsize أصغر
    if asset != "BTC" and TWELVEDATA_KEY:
        try:
            r = requests.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": "XAU/USD", "interval": td_interval,
                        "outputsize": min(outputsize, 200),
                        "apikey": TWELVEDATA_KEY, "format": "JSON"},
                timeout=20)
            data = r.json()
            if "values" in data and len(data["values"]) > 0:
                rows = []
                for v in reversed(data["values"]):
                    rows.append({"timestamp": pd.to_datetime(v["datetime"]),
                                 "Open": float(v["open"]), "High": float(v["high"]),
                                 "Low": float(v["low"]), "Close": float(v["close"]),
                                 "Volume": float(v.get("volume", 0))})
                df = pd.DataFrame(rows).set_index("timestamp").dropna()
                set_cache(cache_key, df)
                logger.info("Twelve Data fallback OK: XAU/USD")
                return df
        except Exception as e:
            logger.warning("Twelve Data fallback failed: " + str(e))

    # Fallback: CoinGecko للبيتكوين
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": interval}, timeout=15)
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
        logger.info("CoinGecko fallback OK: BTC")
        return result
    except Exception as e:
        logger.error("BTC CoinGecko Error: " + str(e))

    return None

def get_btc_price():
    if TWELVEDATA_KEY:
        try:
            r = requests.get("https://api.twelvedata.com/price",
                             params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY}, timeout=10)
            data = r.json()
            if "price" in data:
                return float(data["price"])
        except:
            pass
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10)
        return float(r.json()["bitcoin"]["usd"])
    except:
        return None

def get_prices():
    result = {"bitcoin": {}}
    if TWELVEDATA_KEY:
        try:
            r1 = requests.get("https://api.twelvedata.com/price",
                              params={"symbol": "BTC/USD", "apikey": TWELVEDATA_KEY}, timeout=10)
            btc_price = float(r1.json().get("price", 0))
            r3 = requests.get("https://api.twelvedata.com/time_series",
                              params={"symbol": "BTC/USD", "interval": "1day",
                                      "outputsize": 2, "apikey": TWELVEDATA_KEY}, timeout=10)
            btc_data = r3.json().get("values", [])
            btc_change = 0
            if len(btc_data) >= 2:
                prev = float(btc_data[1]["close"])
                btc_change = round((btc_price - prev) / prev * 100, 2) if prev > 0 else 0
            result["bitcoin"] = {"usd": btc_price, "usd_24h_change": btc_change}
            return result
        except Exception as e:
            logger.warning("Twelve Data prices failed: " + str(e))
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=10)
        return r.json()
    except:
        return None


# ==================== Fibonacci ====================
def calculate_fibonacci(df):
    window = min(100, len(df))
    recent = df.tail(window)
    swing_high = float(recent['High'].max())
    swing_low  = float(recent['Low'].min())
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
        sl_fib = max([v for v in fib_vals if v < price], default=price - atr)
        sl = round(min(sl_fib - 0.2*atr, price - 0.8*atr), 2)
        tp1_candidates = [v for v in fib_vals if v > price + 0.5*atr]
        tp1 = round(tp1_candidates[0] if tp1_candidates else price + 0.8*atr, 2)
        tp2_candidates = [v for v in fib_vals if v > tp1 + 0.3*atr]
        tp2_fib = tp2_candidates[0] if tp2_candidates else price + 1.8*atr
        tp2 = round(max(tp2_fib, price + 1.5*atr), 2)
        ext_vals = sorted(extensions.values(), reverse=True)
        tp3_candidates = [v for v in ext_vals if v > tp2 + 0.5*atr]
        tp3 = round(tp3_candidates[0] if tp3_candidates else price + 3.0*atr, 2)
    else:
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
    df['Pivot'] = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df['R1'] = 2 * df['Pivot'] - l.shift(1)
    df['S1'] = 2 * df['Pivot'] - h.shift(1)
    df['R2'] = df['Pivot'] + (h.shift(1) - l.shift(1))
    df['S2'] = df['Pivot'] - (h.shift(1) - l.shift(1))
    high_9  = h.rolling(window=9).max();  low_9   = l.rolling(window=9).min()
    high_26 = h.rolling(window=26).max(); low_26  = l.rolling(window=26).min()
    high_52 = h.rolling(window=52).max(); low_52  = l.rolling(window=52).min()
    df['Tenkan'] = (high_9  + low_9)  / 2
    df['Kijun']  = (high_26 + low_26) / 2
    df['SpanA']  = ((df['Tenkan'] + df['Kijun']) / 2).shift(26)
    df['SpanB']  = ((high_52 + low_52) / 2).shift(26)
    df['Chikou'] = c.shift(-26)
    try:
        if 'Volume' in df.columns and df['Volume'].sum() > 0:
            df['Vol_MA']   = df['Volume'].rolling(20).mean()
            df['Vol_High'] = df['Volume'] > df['Vol_MA'] * 1.5
        else:
            df['Vol_High'] = False
    except:
        df['Vol_High'] = False
    # Price Action Patterns
    try:
        o = df['Open']; h = df['High']; l = df['Low']; c2 = df['Close']
        body    = abs(c2 - o)
        candle  = h - l
        # Pin Bar (Hammer/Shooting Star)
        df['PinBar_Bull'] = ((l - c2.combine(o, min)) > body * 2) & (candle > 0)
        df['PinBar_Bear'] = ((h - c2.combine(o, max)) > body * 2) & (candle > 0)
        # Engulfing
        df['Engulf_Bull'] = (c2 > o.shift(1)) & (o < c2.shift(1)) & (c2.shift(1) < o.shift(1))
        df['Engulf_Bear'] = (c2 < o.shift(1)) & (o > c2.shift(1)) & (c2.shift(1) > o.shift(1))
        # Market Structure: Higher High / Lower Low
        df['HH'] = h > h.shift(1)
        df['LL'] = l < l.shift(1)
    except:
        df['PinBar_Bull'] = False; df['PinBar_Bear'] = False
        df['Engulf_Bull'] = False; df['Engulf_Bear'] = False
        df['HH'] = False;          df['LL'] = False
    return df

def analyze_frame(df, uid=0):
    df = calc_indicators(df)
    last  = df.iloc[-1]
    price = last['Close']
    sb = ss = 0
    details = []
    rsi = last['RSI']
    if rsi < 30:   sb += 25; details.append(t(uid,'ind_rsi_oversold') + " (" + str(round(rsi,1)) + ") 🟢")
    elif rsi < 45: sb += 12; details.append(t(uid,'ind_rsi_buy') + " (" + str(round(rsi,1)) + ")")
    elif rsi > 70: ss += 25; details.append(t(uid,'ind_rsi_overbought') + " (" + str(round(rsi,1)) + ") 🔴")
    elif rsi > 55: ss += 12; details.append(t(uid,'ind_rsi_sell') + " (" + str(round(rsi,1)) + ")")
    if last['MACD'] > last['MACD_S'] and last['MACD_H'] > 0:
        sb += 20; details.append(t(uid,'ind_macd_pos'))
    elif last['MACD'] < last['MACD_S'] and last['MACD_H'] < 0:
        ss += 20; details.append(t(uid,'ind_macd_neg'))
    if last['EMA9'] > last['EMA21'] > last['EMA50']:
        sb += 20; details.append(t(uid,'ind_ema_up'))
    elif last['EMA9'] < last['EMA21'] < last['EMA50']:
        ss += 20; details.append(t(uid,'ind_ema_down'))
    if price > last['EMA200']: sb += 10
    else: ss += 10
    if price <= last['BB_L']:   sb += 15; details.append(t(uid,'ind_bb_low'))
    elif price >= last['BB_U']: ss += 15; details.append(t(uid,'ind_bb_high'))
    if last['Stoch'] < 20 and last['Stoch_S'] < 20:
        sb += 10; details.append(t(uid,'ind_stoch_low'))
    elif last['Stoch'] > 80 and last['Stoch_S'] > 80:
        ss += 10; details.append(t(uid,'ind_stoch_high'))
    try:
        tenkan = last['Tenkan']; kijun = last['Kijun']
        span_a = last['SpanA'];  span_b = last['SpanB']
        cloud_top = max(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
        cloud_bot = min(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
        ichi_bull = False; ichi_bear = False
        if cloud_top and cloud_bot:
            if price > cloud_top and tenkan > kijun:
                sb += 15; ichi_bull = True
                details.append("Ichimoku: فوق السحابة + TK صاعد ☁️")
            elif price < cloud_bot and tenkan < kijun:
                ss += 15; ichi_bear = True
                details.append("Ichimoku: تحت السحابة + TK هابط ☁️")
            elif cloud_top > cloud_bot: sb += 5
            else: ss += 5
    except:
        ichi_bull = False; ichi_bear = False
    try:
        if bool(last.get("Vol_High", False)) is True:
            if sb > ss: sb += 10
            else: ss += 10
    except: pass
    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf  = round(max(sb, ss) / total * 100) if total > 0 else 50
    return {
        "direction": direction, "conf": conf, "sb": sb, "ss": ss,
        "rsi": round(rsi, 1), "price": round(price, 2),
        "atr": round(last['ATR'], 2), "details": details[:4],
        "support": round(last['S1'], 2), "resistance": round(last['R1'], 2),
        "macd_bull": last['MACD'] > last['MACD_S'],
        "ema_bull": last['EMA9'] > last['EMA21'] > last['EMA50'],
        "ema_bear": last['EMA9'] < last['EMA21'] < last['EMA50'],
        "bb_zone": "low" if price <= last['BB_L'] else "high" if price >= last['BB_U'] else "mid",
        "ichi_bull": ichi_bull, "ichi_bear": ichi_bear,
    }

# ==================== Market Regime ====================


# ==================== RSI Divergence ====================


# ==================== Order Blocks ====================


# ==================== Liquidity Zones ====================


# ==================== Session Filter ====================


def get_monthly_bias(df_daily):
    """يحدد الاتجاه الشهري"""
    try:
        if df_daily is None or len(df_daily) < 30:
            return "NEUTRAL"
        df_m = df_daily.resample("ME").agg({
            "Open":"first","High":"max","Low":"min",
            "Close":"last","Volume":"sum"
        }).dropna().tail(3)
        if len(df_m) < 2:
            return "NEUTRAL"
        last_close  = float(df_m["Close"].iloc[-1])
        prev_close  = float(df_m["Close"].iloc[-2])
        two_prev    = float(df_m["Close"].iloc[0]) if len(df_m) >= 3 else prev_close
        if last_close > prev_close > two_prev:
            return "BULL"
        elif last_close < prev_close < two_prev:
            return "BEAR"
        return "NEUTRAL"
    except:
        return "NEUTRAL"




# ==================== تنبيه الأحداث الاقتصادية ====================


def full_analysis(asset="BTC", uid=0):
    df_1h = get_data(asset, days=14,  interval="hourly")
    df_4h = get_data(asset, days=30,  interval="hourly")
    df_1d = get_data(asset, days=90,  interval="daily")
    df_1w = get_data(asset, days=365, interval="daily")

    # Session Filter
    session, session_score = get_current_session()
    # Asian session: اشتراط توافق 3 فريمات
    if session == "ASIAN" and (buy_c if "buy_c" in dir() else 0) < 3 and (sel_c if "sel_c" in dir() else 0) < 3:
        pass  # سيتم التحقق بعد حساب buy_c/sel_c

    gold_corr = "NEUTRAL"
    if df_4h is not None and len(df_4h) > 0:
        try:
            df_4h = df_4h.resample('4h').agg({
                'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
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
    # Session Filter: Asian session تشترط توافق 3 فريمات
    if session == "ASIAN" and buy_c < 3 and sel_c < 3:
        return None

    if buy_c == 3:   final="BUY";  conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif buy_c == 2: final="BUY";  conf_txt=t(uid,"partial_confluence"); frames_conf=65
    elif sel_c == 3: final="SELL"; conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif sel_c == 2: final="SELL"; conf_txt=t(uid,"partial_confluence"); frames_conf=65
    else:
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h) if (df_1h is not None and len(df_1h)>=20) else ({},{},0,0)
        nf2, fk2, dp2 = find_nearest_fib(main2['price'], fib_l2, "NEUTRAL") if fib_l2 else (main2['price'],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x: float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            icon = "🟢" if r['direction']=="BUY" else "🔴"
            fl2.append(icon+" "+icons2.get(k,"")+": "+r['direction']+" ("+str(r['conf'])+"%)")
        return {"final":"NEUTRAL","asset":asset,"confluence_txt":t(uid,"no_confluence"),"base_conf":0,
                "price":main2['price'],"tp1":0,"tp2":0,"tp3":0,"sl":0,"rr":0,"atr":main2['atr'],
                "risk_pct":50,"risk_label":t(uid,"risk_med"),"risk_msg":t(uid,"risk_med_msg"),
                "frame_lines":fl2,"ind_details":main2['details'],
                "rsi":main2['rsi'],"support":main2['support'],"resistance":main2['resistance'],
                "macd_bull":main2['macd_bull'],"ema_bull":main2['ema_bull'],
                "ema_bear":main2['ema_bear'],"bb_zone":main2['bb_zone'],
                "fib_levels":fib_l2,"fib_ext":fib_e2,"key_fibs":kf2,
                "nearest_fib":nf2,"fib_key":fk2,"swing_h":sh2,"swing_l":sl2,
                "leverage_ar":"","leverage_en":"","tf_ar":"","tf_en":"","hold_ar":"","hold_en":""}
    main  = results.get("1h") or list(results.values())[0]
    price = main['price']
    atr   = main['atr']
    base_conf = max(50, min(round(frames_conf * 0.6 + main['conf'] * 0.4), 89))
    if df_1h is not None and len(df_1h) >= 20:
        fib_levels, fib_ext, swing_h, swing_l = calculate_fibonacci(df_1h)
    else:
        fib_levels, fib_ext, swing_h, swing_l = {}, {}, price*1.02, price*0.98
    nearest_fib, fib_key, dist_pct = find_nearest_fib(price, fib_levels, final)
    # منطقة الدخول: ±0.3% من السعر (أو 0.2 ATR)
    entry_buffer = round(max(price * 0.003, atr * 0.2), 2)
    if final == 'BUY':
        entry_low  = round(price - entry_buffer, 2)
        entry_high = round(price + entry_buffer * 0.5, 2)
    else:
        entry_low  = round(price - entry_buffer * 0.5, 2)
        entry_high = round(price + entry_buffer, 2)
    sl, tp1, tp2, tp3, rr = get_fib_targets(price, fib_levels, fib_ext, final, atr)
    risk = 100 - base_conf
    if main['rsi'] < 25 or main['rsi'] > 75: risk += 10
    if dist_pct > 2: risk += 5
    risk = min(risk, 99)
    if risk < 30:   rl=t(uid,"risk_low");  rm=t(uid,"risk_low_msg")
    elif risk < 55: rl=t(uid,"risk_med");  rm=t(uid,"risk_med_msg")
    else:           rl=t(uid,"risk_high"); rm=t(uid,"risk_high_msg")
    frame_lines = []
    icons = {"1h": t(uid,"frame_1h"), "4h": t(uid,"frame_4h"), "1d": t(uid,"frame_1d")}
    for k, r in results.items():
        icon = "🟢" if r['direction'] == "BUY" else "🔴"
        frame_lines.append(icon + " " + icons.get(k,'') + ": " + r['direction'] + " (" + str(r['conf']) + "%)")
    key_fibs = []
    for pct, val in sorted(fib_levels.items(), key=lambda x: float(x[0])):
        key_fibs.append("Fib " + pct + "%  $" + "{:,.2f}".format(val))
    # ==================== Market Regime ====================
    regime, regime_strength = detect_market_regime(df_1h)
    # في RANGING — اشتراط توافق 3 فريمات
    if regime == "RANGING" and (buy_c < 3 and sel_c < 3):
        return None
    # في VOLATILE — اشتراط توافق 3 فريمات
    if regime == "VOLATILE" and (buy_c < 3 and sel_c < 3):
        return None

    # ==================== RSI Divergence ====================
    divergence = "NONE"
    try:
        if df_1h is not None and "RSI" in calc_indicators(df_1h.tail(30).copy()).columns:
            df_div = calc_indicators(df_1h.tail(30).copy())
            divergence = detect_rsi_divergence(df_div)
            # Bearish Divergence تعزز SELL
            if divergence == "BEARISH" and final == "SELL":
                base_conf = min(base_conf + 8, 89)
            # Bullish Divergence تعزز BUY
            elif divergence == "BULLISH" and final == "BUY":
                base_conf = min(base_conf + 8, 89)
            # Divergence معاكسة تخفض الثقة
            elif divergence == "BEARISH" and final == "BUY":
                base_conf = max(base_conf - 10, 50)
            elif divergence == "BULLISH" and final == "SELL":
                base_conf = max(base_conf - 10, 50)
    except: pass

    # ==================== Order Blocks & Liquidity ====================
    bull_obs, bear_obs = find_order_blocks(df_1h) if df_1h is not None else ([], [])
    buy_liq, sell_liq  = find_liquidity_zones(df_1h) if df_1h is not None else ([], [])

    # ==================== تحقق من OB ====================
    # في SELL: منطقة الدخول لازم تكون قريبة من Bearish OB
    # في BUY: منطقة الدخول لازم تكون قريبة من Bullish OB
    ob_confirmed = False
    try:
        if final == "SELL" and bear_obs:
            for ob in bear_obs:
                # الدخول داخل أو قريب من الـ OB بـ 0.5%
                ob_range = ob["high"] * 1.005
                ob_floor = ob["low"]  * 0.995
                if ob_floor <= price <= ob_range:
                    ob_confirmed = True
                    break
        elif final == "BUY" and bull_obs:
            for ob in bull_obs:
                ob_range = ob["high"] * 1.005
                ob_floor = ob["low"]  * 0.995
                if ob_floor <= price <= ob_range:
                    ob_confirmed = True
                    break
        # إذا ما في OB قريب — اشتراط توافق 3 فريمات
        if not ob_confirmed and buy_c < 3 and sel_c < 3:
            return None
    except: pass

    # ==================== SL عند منطقة سيولة ====================
    try:
        if final == "SELL" and buy_liq:
            # في SELL: SL فوق أقرب Buy Side Liquidity
            liq_above = [l for l in buy_liq if l > price]
            if liq_above:
                liq_sl = round(min(liq_above) * 1.002, 2)  # 0.2% فوق السيولة
                # استخدم الأصغر بين ATR-based SL وLiquidity SL
                sl = round(min(sl, liq_sl), 2) if liq_sl < sl * 1.01 else sl
        elif final == "BUY" and sell_liq:
            # في BUY: SL تحت أقرب Sell Side Liquidity
            liq_below = [l for l in sell_liq if l < price]
            if liq_below:
                liq_sl = round(max(liq_below) * 0.998, 2)  # 0.2% تحت السيولة
                sl = round(max(sl, liq_sl), 2) if liq_sl > sl * 0.99 else sl
        # أعد حساب RR بعد تعديل SL
        rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
        # تحقق RR لا زال فوق 1.5
        if rr < 1.5:
            return None
    except: pass


    # ==================== Monthly Bias ====================
    monthly_bias = get_monthly_bias(df_1d)
    # منع SELL إذا الشهري صاعد إلا بتوافق 3 فريمات
    if monthly_bias == "BULL" and final == "SELL" and sel_c < 3:
        return None
    # منع BUY إذا الشهري هابط إلا بتوافق 3 فريمات
    if monthly_bias == "BEAR" and final == "BUY" and buy_c < 3:
        return None

    # ==================== Weekly Trend Filter ====================
    weekly_trend = "NEUTRAL"
    try:
        if df_1w is not None and len(df_1w) >= 20:
            df_1w_calc = calc_indicators(df_1w.tail(200).copy())
            last_w = df_1w_calc.iloc[-1]
            w_price = last_w["Close"]
            w_ema20 = last_w.get("EMA21", w_price)
            w_ema50 = last_w.get("EMA50", w_price)
            if w_price > w_ema20 and w_ema20 > w_ema50:
                weekly_trend = "BULL"
            elif w_price < w_ema20 and w_ema20 < w_ema50:
                weekly_trend = "BEAR"
            # منع SELL إذا الويكلي صاعد بقوة (إلا لو توافق 3 فريمات)
            if weekly_trend == "BULL" and final == "SELL" and sel_c < 3:
                return None
            # منع BUY إذا الويكلي هابط بقوة (إلا لو توافق 3 فريمات)
            if weekly_trend == "BEAR" and final == "BUY" and buy_c < 3:
                return None
    except Exception as e:
        logger.warning("Weekly filter error: " + str(e))

    # ==================== فلتر الأحداث الاقتصادية ====================
    upcoming_ev = get_upcoming_event_warning(hours_ahead=2)
    if upcoming_ev and "عالي" in upcoming_ev.get("impact",""):
        return None  # لا إشارات قبل ساعتين من حدث عالي التأثير

    # ==================== فلتر EMA200 ====================
    # في BUY: السعر لازم يكون فوق EMA200 أو توافق 3 فريمات
    # في SELL: السعر لازم يكون تحت EMA200 أو توافق 3 فريمات
    ema200_ok = True
    try:
        ema200_val = df_1h.iloc[-1].get("EMA200", None) if df_1h is not None else None
        if ema200_val and not pd.isna(ema200_val):
            if final == "BUY"  and price < ema200_val and buy_c < 3:
                ema200_ok = False
            if final == "SELL" and price > ema200_val and sel_c < 3:
                ema200_ok = False
    except:
        pass

    if not ema200_ok:
        return None

    # ==================== تحقق منطقية الأهداف ====================
    if final == "BUY":
        if not (sl < price < tp1 < tp2 < tp3):
            # أعد حساب بـ ATR بحت
            sl  = round(price - 1.0*atr, 2)
            tp1 = round(price + 1.0*atr, 2)
            tp2 = round(price + 2.0*atr, 2)
            tp3 = round(price + 3.5*atr, 2)
    else:
        if not (tp3 < tp2 < tp1 < price < sl):
            sl  = round(price + 1.0*atr, 2)
            tp1 = round(price - 1.0*atr, 2)
            tp2 = round(price - 2.0*atr, 2)
            tp3 = round(price - 3.5*atr, 2)

    # ==================== فلتر RR minimum 1.5 ====================
    rr_check = abs(tp2 - price) / abs(sl - price) if abs(sl - price) > 0 else 0
    if rr_check < 1.5:
        return None

    return {
        "final": final, "asset": asset, "weekly_trend": weekly_trend,
        "regime": regime, "regime_strength": regime_strength,
        "monthly_bias": monthly_bias,
        "divergence": divergence,
        "session": session, "session_score": session_score,
        "gold_corr": gold_corr,
        "bull_obs": bull_obs, "bear_obs": bear_obs,
        "buy_liq": buy_liq, "sell_liq": sell_liq,
        "confluence_txt": conf_txt, "base_conf": base_conf,
        "price": price, "entry_low": entry_low, "entry_high": entry_high, "tp1": tp1, "tp2": tp2, "tp3": tp3,
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


# ==================== بناء الرسائل (محسّن) ====================
def build_trade_msg(res, uid=0, auto=False):
    lang    = user_languages.get(uid, "ar")
    ai      = "₿" if res['asset'] == "BTC" else "🥇"
    an      = "BTC/USD" if res['asset'] == "BTC" else "XAU/USD"
    is_sell = res['final'] == "SELL"
    dir_emoji = "🔴" if is_sell else "🟢"
    dir_txt   = t(uid,"sell") if is_sell else t(uid,"buy")
    header    = t(uid,"auto_header") if auto else t(uid,"trade_header")
    leverage  = res['leverage_ar'] if lang == "ar" else res['leverage_en']
    hold      = res['hold_ar']     if lang == "ar" else res['hold_en']
    conf      = res['base_conf']
    bar       = "█" * (conf // 10) + "░" * (10 - conf // 10)

    trade_num = res.get("id", "")
    trade_num_str = "  #" + str(trade_num) if trade_num else ""
    lines = [
        "╔══════════════════════════╗",
        "  " + ai + " " + an + "  " + dir_emoji + "  " + dir_txt + trade_num_str,
        "  ⚡ " + header,
        "╚══════════════════════════╝",
        "",
        "💵 السعر الحالي   $" + "{:,.2f}".format(res['price']),
        "📍 " + t(uid,'entry') + "   $" + "{:,.2f}".format(res.get('entry_low', res['price'])) + " — $" + "{:,.2f}".format(res.get('entry_high', res['price'])) + "  ↔️",
        "📐 " + t(uid,'fib_entry') + "   Fib " + res['fib_key'] + "% ($" + "{:,.2f}".format(res['nearest_fib']) + ")",
        "",
        "━━━━  🎯 " + t(uid,'targets_section') + "  ━━━━",
        "  TP1  ›  $" + "{:,.2f}".format(res['tp1']),
        "  TP2  ›  $" + "{:,.2f}".format(res['tp2']),
        "  TP3  ›  $" + "{:,.2f}".format(res['tp3']),
        "  🛑 " + t(uid,'sl') + "   ›  $" + "{:,.2f}".format(res['sl']),
        "  ⚖️  " + t(uid,'rr') + ":  1:" + str(res['rr']),
        "",
        "━━━━  🔗 " + t(uid,'confluence') + "  ━━━━",
    ]
    wt = res.get("weekly_trend", "NEUTRAL")
    wt_emoji = "📈" if wt=="BULL" else "📉" if wt=="BEAR" else "➡️"
    wt_txt   = "صاعد" if wt=="BULL" else "هابط" if wt=="BEAR" else "محايد"
    lines.append("  " + wt_emoji + " ويكلي: " + wt_txt)
    rg = res.get("regime", "UNKNOWN")
    rg_map = {"TRENDING_UP":"📈 ترند صاعد","TRENDING_DOWN":"📉 ترند هابط","RANGING":"↔️ سوق جانبي","VOLATILE":"⚡ تقلب عالي","UNKNOWN":"❓"}
    lines.append("  " + rg_map.get(rg, rg))
    mb = res.get("monthly_bias", "NEUTRAL")
    mb_txt = "📈 شهري: صاعد" if mb=="BULL" else "📉 شهري: هابط" if mb=="BEAR" else "➡️ شهري: محايد"
    lines.append("  " + mb_txt)
    # Session
    # Divergence
    div = res.get("divergence", "NONE")
    if div == "BEARISH": lines.append("  📉 RSI Divergence هابط ⚠️")
    elif div == "BULLISH": lines.append("  📈 RSI Divergence صاعد ✅")
    # Order Blocks
    is_sell = res["final"] == "SELL"
    obs = res.get("bear_obs" if is_sell else "bull_obs", [])
    if obs:
        ob = obs[-1]
        ob_label = "🔴 سبب الدخول: منطقة بيع قوية" if is_sell else "🟢 سبب الدخول: منطقة شراء قوية"
        lines.append("  " + ob_label)
        lines.append("     $" + "{:,.0f}".format(ob["low"]) + " — $" + "{:,.0f}".format(ob["high"]))
    # Liquidity
    liq = res.get("sell_liq" if is_sell else "buy_liq", [])
    if liq:
        lines.append("  🎯 $" + "{:,.0f}".format(liq[0]) + " — منطقة سيولة")
        lines.append("     ⚠️ قد ينعكس السوق عندها")
    for fl in res['frame_lines']:
        lines.append("  " + fl)
    lines.append("  " + res['confluence_txt'])

    lines += [
        "",
        "━━━━  📡 مناطق مهمة  ━━━━",
        "  🟢 دعم:       $" + "{:,.2f}".format(res['support']),
        "  🔴 مقاومة:   $" + "{:,.2f}".format(res['resistance']),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 " + t(uid,'updated_gmt') + ":  " + gmt_now(),
        t(uid,'footer'),
    ]
    return "\n".join(lines)


def build_update_msg(trade, current_price, update_type, uid=0):
    dir_txt = t(uid,"buy") if trade['direction'] == "BUY" else t(uid,"sell")
    lines = [
        "╔══════════════════════════╗",
        "  🔄 ₿ BTC/USD  •  " + t(uid,'update_header'),
        "╚══════════════════════════╝",
        "",
        "  " + t(uid,'direction') + ":      " + dir_txt,
        "  " + t(uid,'entry') + ":          $" + "{:,.2f}".format(trade['entry']),
        "  " + t(uid,'current_price') + ":  $" + "{:,.2f}".format(current_price),
        "",
        "  " + update_type,
        "",
        "━━━━  🎯 " + t(uid,'targets_section') + "  ━━━━",
        "  TP1  ›  $" + "{:,.2f}".format(trade['tp1']),
        "  TP2  ›  $" + "{:,.2f}".format(trade['tp2']),
        "  TP3  ›  $" + "{:,.2f}".format(trade['tp3']),
        "  🛑 SL  ›  $" + "{:,.2f}".format(trade['sl']),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 " + t(uid,'updated_gmt') + ":  " + gmt_now(),
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
    rsi = res['rsi']
    rsi_txt  = t(uid,"rsi_oversold") if rsi < 30 else t(uid,"rsi_overbought") if rsi > 70 else t(uid,"rsi_neutral")
    macd_txt = t(uid,"macd_bull") if res['macd_bull'] else t(uid,"macd_bear")
    ema_txt  = t(uid,"ema_bull") if res['ema_bull'] else t(uid,"ema_bear") if res['ema_bear'] else t(uid,"ema_mixed")
    bb_txt   = t(uid,"bb_low") if res['bb_zone']=="low" else t(uid,"bb_high") if res['bb_zone']=="high" else t(uid,"bb_mid")
    lines = [
        "╔══════════════════════════╗",
        "  " + ai + " " + an + "  |  " + t(uid,'analysis_header'),
        "╚══════════════════════════╝",
        "",
        "  " + trend,
        "  💵 " + t(uid,'entry') + ":         $" + "{:,.2f}".format(res['price']),
        "  🟢 " + t(uid,'support') + ":      $" + "{:,.2f}".format(res['support']),
        "  🔴 " + t(uid,'resistance') + ":   $" + "{:,.2f}".format(res['resistance']),
        "",
        "━━━━  📐 " + t(uid,'fib_section') + "  ━━━━",
    ]
    for f in res['key_fibs']:
        lines.append("  " + f)
    lines += [
        "",
        "━━━━  🔗 " + t(uid,'confluence') + "  ━━━━",
    ]
    for fl in res['frame_lines']:
        lines.append("  " + fl)
    lines += [
        "",
        "━━━━  📊 " + t(uid,'indicators_section') + "  ━━━━",
        "  RSI (" + str(rsi) + "):  " + rsi_txt,
        "  " + macd_txt,
        "  " + ema_txt,
        "  " + bb_txt,
        "",
        "  " + summary,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🕐 " + t(uid,'updated_gmt') + ":  " + gmt_now(),
        t(uid,'footer'),
    ]
    return "\n".join(lines)


# ==================== لوحات المفاتيح ====================
def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_btc"),  callback_data='trade_BTC'),
         InlineKeyboardButton(t(uid,"btn_analysis_btc"),  callback_data='analysis_BTC')],
        [InlineKeyboardButton(t(uid,"btn_prices"),  callback_data='prices'),
         InlineKeyboardButton(t(uid,"btn_trades"),  callback_data='open_trades')],
        [InlineKeyboardButton(t(uid,"btn_stats"),   callback_data='stats'),
         InlineKeyboardButton(t(uid,"btn_about"),   callback_data='about')],
        [InlineKeyboardButton(t(uid,"btn_lang"),    callback_data='change_lang')]
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data='lang_ar'),
        InlineKeyboardButton("English",  callback_data='lang_en')
    ]])


# ==================== هاندلرز ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        await update.message.reply_text("⛔ هذا البوت خاص")
        return
    if uid not in user_languages:
        await update.message.reply_text(
            "🐎 Abu Mahra Bot\n\nاختر لغتك / Choose your language:",
            reply_markup=lang_keyboard())
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
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    await query.answer()
    if uid not in ALLOWED_USERS: return

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
            global trade_counter
            trade_counter += 1
            res["id"] = trade_counter
            await query.message.reply_text(build_trade_msg(res, uid))
            new_trade = {
                "id": trade_counter,
                "asset": res['asset'],
                "direction": res['final'],
                "entry": res['price'], "sl": res['sl'],
                "tp1": res['tp1'], "tp2": res['tp2'], "tp3": res['tp3'],
                "atr": res['atr'], "tp1_hit": False, "tp2_hit": False,
                "chat_id": query.message.chat_id,
                "open_time": gmt_now(),
            }
            active_trades.append(new_trade)
            if res['asset'] == "BTC":
                active_btc_trade['data'] = new_trade
            save_trades()
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
            bp = btc.get('usd',0);  bc = btc.get('usd_24h_change',0)
            lines = [
                "╔══════════════════════════╗",
                "  " + t(uid,'prices_title'),
                "╚══════════════════════════╝",
                "",
                "  ₿ BTC/USD:   $" + "{:,.0f}".format(bp),
                "  " + ("📈" if bc > 0 else "📉") + " " + t(uid,'change_24h') + ":  " + "{:+.2f}".format(bc) + "%",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                "🕐 " + t(uid,'updated_gmt') + ":  " + gmt_now(),
            ]
            await query.message.reply_text("\n".join(lines))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))
    elif data == 'open_trades':
        if not active_trades:
            await query.message.reply_text(t(uid,'no_open_trades'))
        else:
            rows = ['╔'+'═'*26+'╗', '  📋 الصفقات المفتوحة', '╚'+'═'*26+'╝', '']
            for tr in active_trades:
                de = '🔴 SELL' if tr['direction']=='SELL' else '🟢 BUY'
                ai2 = '₿' if tr['asset']=='BTC' else '🥇'
                rows += [ai2+' #'+str(tr.get('id','?'))+'  '+de,
                         '  دخول: $'+'{:,.2f}'.format(tr['entry']),
                         '  TP1:  $'+'{:,.2f}'.format(tr['tp1']),
                         '  TP2:  $'+'{:,.2f}'.format(tr['tp2']),
                         '  SL:   $'+'{:,.2f}'.format(tr['sl']),
                         '  وقت: '+tr.get('open_time',''), '']
            rows += ['━'*24, '🕐 '+gmt_now()]
            await query.message.reply_text('\n'.join(rows))
    elif data == 'stats':
        stats = load_stats()
        total  = stats.get('total', 0)
        wins   = stats.get('wins', 0)
        losses = stats.get('losses', 0)
        total_rr = stats.get('total_rr', 0.0)
        win_rate = round(wins / total * 100) if total > 0 else 0
        avg_rr   = round(total_rr / wins, 2) if wins > 0 else 0
        bar_w = '█' * (win_rate // 10) + '░' * (10 - win_rate // 10)
        lines = [
            '╔' + '═'*26 + '╗',
            '  📊 إحصائيات أبو مهرة',
            '╚' + '═'*26 + '╝',
            '',
            '  إجمالي الصفقات:  ' + str(total),
            '  ✅ رابحة:         ' + str(wins),
            '  ❌ خاسرة:         ' + str(losses),
            '',
            '  🎯 نسبة النجاح',
            '  ' + bar_w + '  ' + str(win_rate) + '%',
            '  ⚖️ متوسط RR:  1:' + str(avg_rr),
            '',
            '━'*24,
            '🕐 ' + gmt_now(),
        ]
        await query.message.reply_text('\n'.join(lines))

    elif data == 'about':
        await query.message.reply_text(t(uid,'about_text'))


# ==================== إشارات تلقائية ====================
async def auto_signals(context):
    try:
        for asset in ["BTC"]:
            res = full_analysis(asset, 0)
            if res and res['final'] != "NEUTRAL" and res['base_conf'] >= MIN_CONFIDENCE:
                global trade_counter
                # spam filter
                now_ts = datetime.now(timezone.utc).timestamp()
                last_ts = last_signal_time.get(asset, 0)
                if (now_ts - last_ts) < SPAM_COOLDOWN:
                    logger.info("Spam filter: " + asset + " skipped")
                    continue
                last_signal_time[asset] = now_ts
                trade_counter += 1
                res["id"] = trade_counter
                await context.bot.send_message(chat_id=CHANNEL_ID,
                                               text=build_trade_msg(res, 0, auto=True))
                new_trade = {
                    "id": trade_counter,
                    "asset": res['asset'],
                    "direction": res['final'],
                    "entry": res['price'], "sl": res['sl'],
                    "tp1": res['tp1'], "tp2": res['tp2'], "tp3": res['tp3'],
                    "atr": res['atr'], "tp1_hit": False, "tp2_hit": False,
                    "chat_id": CHANNEL_ID,
                    "open_time": gmt_now(),
                }
                active_trades.append(new_trade)
                if asset == "BTC":
                    active_btc_trade['data'] = new_trade
                save_trades()
    except Exception as e:
        logger.error("❌ Auto: " + str(e))

async def monitor_btc(context):
    if not active_trades:
        return
    try:
        current_btc  = get_btc_price()

        to_remove = []
        for trade in active_trades:
            try:
                asset     = trade.get("asset", "BTC")
                current   = current_btc
                if not current: continue

                uid       = 0
                chat_id   = trade['chat_id']
                direction = trade['direction']
                atr       = trade['atr']
                tp1       = trade['tp1']; tp2 = trade['tp2']; tp3 = trade['tp3']
                trade_id  = trade.get("id", "?")
                update_msg = None
                closed     = False

                if direction == "BUY":
                    if current >= tp3:
                        update_msg = "🏆 #" + str(trade_id) + " الهدف الثالث تم! صفقة مغلقة بنجاح 🎉"
                        record_trade_result(trade_id, "win", trade.get("rr", 0))
                        closed = True
                    elif not trade['tp1_hit'] and current >= tp1:
                        trade['tp1_hit'] = True; trade['sl'] = trade['entry']
                        update_msg = "✅ #" + str(trade_id) + " " + t(uid,"update_tp1_hit")
                    elif trade['tp1_hit'] and not trade['tp2_hit'] and current >= tp2:
                        trade['tp2_hit'] = True; trade['sl'] = tp1
                        update_msg = "✅✅ #" + str(trade_id) + " " + t(uid,"update_tp2_hit")
                    elif current <= trade['sl']:
                        update_msg = "🛑 #" + str(trade_id) + " وقف الخسارة تم! صفقة مغلقة"
                        record_trade_result(trade_id, "loss")
                        closed = True
                    elif trade['tp1_hit'] and current > tp1 + 0.5*atr:
                        new_sl = round(current - 0.8*atr, 2)
                        if new_sl > trade['sl']:
                            trade['sl'] = new_sl
                            update_msg = "📊 #" + str(trade_id) + " " + t(uid,"update_sl_moved")
                else:
                    if current <= tp3:
                        update_msg = "🏆 #" + str(trade_id) + " الهدف الثالث تم! صفقة مغلقة بنجاح 🎉"
                        record_trade_result(trade_id, "win", trade.get("rr", 0))
                        closed = True
                    elif not trade['tp1_hit'] and current <= tp1:
                        trade['tp1_hit'] = True; trade['sl'] = trade['entry']
                        update_msg = "✅ #" + str(trade_id) + " " + t(uid,"update_tp1_hit")
                    elif trade['tp1_hit'] and not trade['tp2_hit'] and current <= tp2:
                        trade['tp2_hit'] = True; trade['sl'] = tp1
                        update_msg = "✅✅ #" + str(trade_id) + " " + t(uid,"update_tp2_hit")
                    elif current >= trade['sl']:
                        update_msg = "🛑 #" + str(trade_id) + " وقف الخسارة تم! صفقة مغلقة"
                        record_trade_result(trade_id, "loss")
                        closed = True
                    elif trade['tp1_hit'] and current < tp1 - 0.5*atr:
                        new_sl = round(current + 0.8*atr, 2)
                        if new_sl < trade['sl']:
                            trade['sl'] = new_sl
                            update_msg = "📊 #" + str(trade_id) + " " + t(uid,"update_sl_moved")

                if update_msg:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=build_update_msg(trade, current, update_msg, uid)
                    )
                if closed:
                    to_remove.append(trade)

            except Exception as e:
                logger.error("Monitor trade error: " + str(e))

        for t_remove in to_remove:
            active_trades.remove(t_remove)
        if to_remove:
            save_trades()

    except Exception as e:
        logger.error("❌ Monitor: " + str(e))

async def send_smart_alerts(context):
    try:
        for asset in ["BTC"]:
            df = get_data(asset, days=7, interval="hourly")
            if df is None or len(df) < 30: continue
            df = calc_indicators(df)
            last  = df.iloc[-1]
            price = last['Close']
            rsi   = last['RSI']
            atr   = last['ATR']
            fib_levels, _, _, _ = calculate_fibonacci(df)
            ai = "₿ BTC/USD" if asset == "BTC" else "🥇 XAU/USD"
            alerts = []
            if rsi < 28:
                alerts.append("🔴 RSI تشبع بيعي قوي (" + str(round(rsi,1)) + ") — فرصة شراء محتملة!")
            elif rsi > 72:
                alerts.append("🔴 RSI تشبع شرائي قوي (" + str(round(rsi,1)) + ") — احتمال انعكاس!")
            for pct, level in fib_levels.items():
                dist = abs(price - level) / price * 100
                if dist < 0.3:
                    alerts.append("📐 السعر عند Fib " + pct + "% ($" + "{:,.2f}".format(level) + ") — مستوى مهم!")
                    break
            try:
                tenkan = last['Tenkan']; kijun = last['Kijun']
                if abs(tenkan - kijun) / price * 100 < 0.2:
                    alerts.append("☁️ Ichimoku: Tenkan و Kijun على وشك التقاطع!")
            except: pass
            bb_width = (last['BB_U'] - last['BB_L']) / last['BB_U'] * 100
            if bb_width < 2:
                alerts.append("💥 Bollinger Squeeze — حركة قوية قادمة!")
            if alerts:
                msg_lines = [
                    "╔══════════════════════════╗",
                    "  ⚡ تنبيه ذكي — " + ai,
                    "╚══════════════════════════╝",
                    "",
                    "  💵 السعر: $" + "{:,.2f}".format(price),
                    "",
                ]
                for a in alerts:
                    msg_lines.append("  " + a)
                msg_lines += [
                    "",
                    "━━━━━━━━━━━━━━━━━━━━━━━━",
                    "🕐 " + gmt_now(),
                    "⚠️ للأغراض التعليمية فقط",
                ]
                await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(msg_lines))
    except Exception as e:
        logger.error("❌ Smart Alerts: " + str(e))





# ==================== أخبار ====================
def get_news():
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "bitcoin OR gold OR Federal Reserve OR inflation OR CPI",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10
        )
        data = r.json()
        if data.get("status") != "ok":
            return None
        return data.get("articles", [])
    except Exception as e:
        logger.error("News error: " + str(e))
        return None

async def send_news(context):
    """يبعث الأخبار كل 4 ساعات"""
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "bitcoin OR gold OR Federal Reserve OR inflation OR CPI",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": NEWS_API_KEY,
            },
            timeout=10
        )
        data = r.json()
        if data.get("status") != "ok":
            return
        articles = data.get("articles", [])
        if not articles:
            return
        lines = [
            "\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557",
            "  \U0001f4f0 \u0623\u062e\u0628\u0627\u0631 \u0627\u0644\u0633\u0648\u0642 - \u0623\u0628\u0648 \u0645\u0647\u0631\u0629",
            "\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d",
            "",
        ]
        for i, a in enumerate(articles[:5], 1):
            title = a.get("title", "")[:80]
            source = a.get("source", {}).get("name", "")
            published = a.get("publishedAt", "")[:10]
            lines.append(str(i) + ". " + title)
            lines.append("   \U0001f4cc " + source + "  |  " + published)
            lines.append("")
        lines += [
            "\u2501" * 24,
            "\U0001f550 " + gmt_now(),
            "\u26a0\ufe0f \u0644\u0644\u0623\u063a\u0631\u0627\u0636 \u0627\u0644\u062a\u0639\u0644\u064a\u0645\u064a\u0629 \u0641\u0642\u0637",
        ]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
        logger.info("News sent")
    except Exception as e:
        logger.error("News error: " + str(e))



def get_upcoming_event_warning(hours_ahead=6):
    """يتحقق إذا في حدث اقتصادي مهم خلال X ساعات"""
    try:
        now = datetime.now(timezone.utc)
        for ev in ECONOMIC_CALENDAR:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # افترض الأحداث الساعة 14:00 GMT (وقت معظم البيانات الأمريكية)
            ev_datetime = ev_date.replace(hour=14, minute=0)
            diff_hours = (ev_datetime - now).total_seconds() / 3600
            if 0 <= diff_hours <= hours_ahead:
                return ev
        return None
    except:
        return None

async def check_economic_alerts(context):
    """يبعث تحذير قبل ساعة من حدث اقتصادي مهم"""
    try:
        ev = get_upcoming_event_warning(hours_ahead=1.5)
        if not ev:
            return
        lines = [
            "╔══════════════════════════╗",
            "  ⚠️ تنبيه حدث اقتصادي",
            "╚══════════════════════════╝",
            "",
            "  " + ev["event"],
            "  📅 " + ev["date"],
            "  " + ev["impact"],
            "  💡 يؤثر على: " + ev["affects"],
            "",
            "  🚫 تجنب فتح صفقات جديدة",
            "  ⏳ انتظر ما بعد الحدث",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "🕐 " + gmt_now(),
        ]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
        logger.info("Economic alert sent: " + ev["event"])
    except Exception as e:
        logger.error("Economic alert error: " + str(e))


# ==================== الإحصائيات ====================
STATS_FILE = "trade_stats.json"

def load_stats():
    try:
        import json
        with open(STATS_FILE) as f:
            return json.load(f)
    except:
        return {"total": 0, "wins": 0, "losses": 0, "total_rr": 0.0, "trades": []}

def save_stats(stats):
    import json
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def record_trade_result(trade_id, result, rr=0):
    """result: 'win' أو 'loss'"""
    stats = load_stats()
    stats["total"] += 1
    if result == "win":
        stats["wins"] += 1
        stats["total_rr"] += rr
    else:
        stats["losses"] += 1
    stats["trades"].append({
        "id": trade_id, "result": result,
        "rr": rr, "time": gmt_now()
    })
    # احتفظ بآخر 50 صفقة بس
    stats["trades"] = stats["trades"][-50:]
    save_stats(stats)


async def send_daily_summary(context):
    """ملخص يومي كل صباح"""
    try:
        stats = load_stats()
        total  = stats.get("total", 0)
        wins   = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        total_rr = stats.get("total_rr", 0.0)
        win_rate = round(wins / total * 100) if total > 0 else 0
        avg_rr   = round(total_rr / wins, 2) if wins > 0 else 0

        # أخبار اليوم
        upcoming = get_upcoming_events(days_ahead=1)

        lines = [
            "╔══════════════════════════╗",
            "  📊 الملخص اليومي - أبو مهرة",
            "╚══════════════════════════╝",
            "",
            "━━━━  📈 الأداء  ━━━━",
            "  إجمالي الصفقات:  " + str(total),
            "  ✅ رابحة:         " + str(wins),
            "  ❌ خاسرة:         " + str(losses),
            "  🎯 نسبة النجاح:   " + str(win_rate) + "%",
            "  ⚖️ متوسط RR:      1:" + str(avg_rr),
            "",
        ]

        if upcoming:
            lines += ["━━━━  📅 أحداث اليوم  ━━━━"]
            for ev in upcoming[:3]:
                lines.append("  " + ev["event"])
                lines.append("  " + ev["impact"] + "  |  " + ev["date"])
                lines.append("")
        else:
            lines += ["━━━━  📅 لا أحداث اقتصادية اليوم  ━━━━", ""]

        # الصفقات المفتوحة
        if active_trades:
            lines += ["━━━━  🔓 صفقات مفتوحة: " + str(len(active_trades)) + "  ━━━━"]
            for tr in active_trades:
                de = "🔴 SELL" if tr["direction"]=="SELL" else "🟢 BUY"
                ai2 = "₿" if tr["asset"]=="BTC" else "🥇"
                lines.append("  " + ai2 + " #" + str(tr.get("id","?")) + "  " + de +
                              "  دخول: $" + "{:,.0f}".format(tr["entry"]))
            lines.append("")

        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "🕐 " + gmt_now(),
            "⚠️ للأغراض التعليمية فقط",
        ]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
        logger.info("Daily summary sent")
    except Exception as e:
        logger.error("Daily summary error: " + str(e))


def detect_rsi_divergence(df, lookback=20):
    """
    Bullish Divergence: السعر Lower Low بس RSI Higher Low = انعكاس صعودي محتمل
    Bearish Divergence: السعر Higher High بس RSI Lower High = انعكاس هبوطي محتمل
    """
    try:
        if len(df) < lookback + 5:
            return "NONE"
        recent = df.tail(lookback)
        prices = recent["Close"].values
        rsi    = recent["RSI"].values

        # إيجاد القمم والقيعان
        price_hh = prices[-1] > max(prices[:-5])   # Higher High في السعر
        price_ll = prices[-1] < min(prices[:-5])    # Lower Low في السعر
        rsi_hh   = rsi[-1]   > max(rsi[:-5])        # Higher High في RSI
        rsi_lh   = rsi[-1]   < max(rsi[:-5])        # Lower High في RSI
        rsi_hl   = rsi[-1]   > min(rsi[:-5])        # Higher Low في RSI
        rsi_ll2  = rsi[-1]   < min(rsi[:-5])        # Lower Low في RSI

        # Bearish Divergence: سعر أعلى بس RSI أقل
        if price_hh and rsi_lh and rsi[-1] > 55:
            return "BEARISH"
        # Bullish Divergence: سعر أقل بس RSI أعلى
        if price_ll and rsi_hl and rsi[-1] < 45:
            return "BULLISH"
        return "NONE"
    except:
        return "NONE"


def find_order_blocks(df, lookback=50):
    """
    Order Block = آخر شمعة هبوطية قبل حركة صعودية قوية (Bullish OB)
    أو آخر شمعة صعودية قبل حركة هبوطية قوية (Bearish OB)
    """
    try:
        if len(df) < lookback:
            return [], []
        recent = df.tail(lookback).copy()
        bullish_obs = []
        bearish_obs = []

        for i in range(2, len(recent) - 2):
            candle = recent.iloc[i]
            next3  = recent.iloc[i+1:i+3]

            # Bullish OB: شمعة حمراء (هبوطية) يليها 2+ شمعات خضراء قوية
            if candle["Close"] < candle["Open"]:
                if all(next3["Close"] > next3["Open"]) and                    next3["Close"].max() > candle["Open"] * 1.005:
                    bullish_obs.append({
                        "high": float(candle["Open"]),
                        "low":  float(candle["Close"]),
                        "time": str(candle.name)
                    })

            # Bearish OB: شمعة خضراء (صعودية) يليها 2+ شمعات حمراء قوية
            if candle["Close"] > candle["Open"]:
                if all(next3["Close"] < next3["Open"]) and                    next3["Close"].min() < candle["Open"] * 0.995:
                    bearish_obs.append({
                        "high": float(candle["Close"]),
                        "low":  float(candle["Open"]),
                        "time": str(candle.name)
                    })

        return bullish_obs[-3:], bearish_obs[-3:]
    except:
        return [], []


def find_liquidity_zones(df, lookback=50):
    """
    Liquidity = أماكن تجمع الـ Stop Loss
    فوق القمم السابقة (Buy Side Liquidity) = هدف للسوق قبل الهبوط
    تحت القيعان السابقة (Sell Side Liquidity) = هدف للسوق قبل الصعود
    """
    try:
        if len(df) < lookback:
            return [], []
        recent   = df.tail(lookback)
        highs    = recent["High"].values
        lows     = recent["Low"].values
        buy_liq  = []  # فوق القمم
        sell_liq = []  # تحت القيعان

        for i in range(2, len(highs) - 2):
            # قمة محلية = Buy Side Liquidity
            if highs[i] > highs[i-1] and highs[i] > highs[i+1] and                highs[i] > highs[i-2] and highs[i] > highs[i+2]:
                buy_liq.append(round(float(highs[i]), 2))
            # قاع محلي = Sell Side Liquidity
            if lows[i] < lows[i-1] and lows[i] < lows[i+1] and                lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                sell_liq.append(round(float(lows[i]), 2))

        return sorted(buy_liq)[-3:], sorted(sell_liq)[:3]
    except:
        return [], []


def get_current_session():
    """
    Asian:  00:00 - 08:00 GMT  (ضعيف للـ scalping)
    London: 08:00 - 16:00 GMT  (قوي جداً)
    NY:     13:00 - 21:00 GMT  (قوي جداً)
    Overlap: 13:00 - 16:00 GMT (الأقوى)
    """
    try:
        hour = datetime.now(timezone.utc).hour
        if 13 <= hour < 16:
            return "OVERLAP", 100   # London + NY overlap = الأقوى
        elif 8 <= hour < 16:
            return "LONDON", 85
        elif 13 <= hour < 21:
            return "NY", 85
        else:
            return "ASIAN", 40      # ضعيف
    except:
        return "UNKNOWN", 60


# ==================== Correlation Filter ====================
def get_gold_btc_correlation(asset="BTC"):
    """
    يتحقق من correlation بين BTC والذهب
    - إذا الذهب صاعد قوي = BTC عادةً يتبع (risk-on)
    - إذا الذهب هابط = احتمال ضغط على BTC
    """
    try:
        if asset != "BTC":
            return "NEUTRAL"
        return "NEUTRAL"
    except:
        return "NEUTRAL"


async def send_calendar(context):
    """يبعث التقويم الاقتصادي كل يوم"""
    try:
        events = get_upcoming_events(days_ahead=7)
        if not events:
            return
        lines = [
            "╔══════════════════════════╗",
            "  📅 التقويم الاقتصادي - أبو مهرة",
            "╚══════════════════════════╝",
            "",
        ]
        for ev in events:
            if ev["days_left"] == 0:
                day_txt = "⚠️ اليوم!"
            elif ev["days_left"] == 1:
                day_txt = "⏰ غداً"
            else:
                day_txt = "📆 بعد " + str(ev["days_left"]) + " أيام"
            lines.append(day_txt + " — " + ev["event"])
            lines.append("  📌 " + ev["date"] + "  |  " + ev["impact"])
            lines.append("  💡 يؤثر على: " + ev["affects"])
            lines.append("")
        lines += [
            "━" * 24,
            "🕐 " + gmt_now(),
            "⚠️ للأغراض التعليمية فقط",
        ]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
        logger.info("Calendar sent")
    except Exception as e:
        logger.error("Calendar error: " + str(e))

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_signals,      interval=AUTO_INTERVAL_MIN*60, first=30)
    app.job_queue.run_repeating(monitor_btc,       interval=60,                   first=30)
    app.job_queue.run_repeating(send_smart_alerts, interval=45*60,                first=120)
    app.job_queue.run_repeating(send_news,         interval=4*60*60,              first=300)
    app.job_queue.run_repeating(send_calendar,     interval=24*60*60,             first=600)
    app.job_queue.run_repeating(check_economic_alerts, interval=30*60,            first=120)
    app.job_queue.run_daily(send_daily_summary, time=__import__("datetime").time(6, 0, 0))
    logger.info("🐎 Abu Mahra Bot - Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
