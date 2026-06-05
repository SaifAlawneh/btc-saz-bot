import os
import logging
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

AUTO_INTERVAL_MIN = 30
MIN_CONFIDENCE    = 68
SPAM_COOLDOWN     = 1800
CACHE_TTL         = 900
TRADES_FILE       = "active_trades.json"
STATS_FILE        = "trade_stats.json"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== حالة البوت ====================
user_languages        = {}
active_trades         = []
active_btc_trade      = {}
pending_trade_replace = {}
last_signal_time      = {}
trade_counter         = 0
_cache                = {}

ALLOWED_USERS = {8490817794, 1548286220}

# ==================== تحميل الصفقات ====================
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

_loaded_trades, _loaded_counter = load_trades()
_valid_trades = [t for t in _loaded_trades if t.get("asset") == "BTC" and t.get("entry", 0) > 10000]
active_trades.extend(_valid_trades)
trade_counter = _loaded_counter

# ==================== كاش ====================
def get_cached(key):
    if key in _cache:
        data, ts = _cache[key]
        if (datetime.now(timezone.utc).timestamp() - ts) < CACHE_TTL:
            return data
    return None

def set_cache(key, data):
    _cache[key] = (data, datetime.now(timezone.utc).timestamp())

# ==================== نصوص ====================
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
        "welcome": "🐎 أهلاً وسهلاً في بوت أبو مهرة!\n\n━━━━━━━━━━━━━━━━━━━━\nمتخصص في:\n₿ البيتكوين  BTC/USD\n\n✨ مميزاتي:\n▫️ صفقات مبنية على فريم الساعة\n▫️ Fibonacci + ATR للأهداف\n▫️ مستويات دعم ومقاومة دقيقة\n▫️ إشارات تلقائية كل 30 دقيقة\n▫️ مراقبة BTC وتحديث SL/TP\n━━━━━━━━━━━━━━━━━━━━\n⚠️ للأغراض التعليمية فقط",
        "btn_btc": "₿ صفقة BTC", "btn_gold": "🥇 صفقة ذهب",
        "btn_analysis_btc": "📈 تحليل BTC", "btn_analysis_gold": "📈 تحليل ذهب",
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
        "update_tp2_hit": "✅✅ الهدف الثاني تم! تم نقل SL للـ TP1",
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
        "about_text": "ℹ️ عن بوت أبو مهرة 🐎\n\n⏱️ فريم الساعة (1H)\n📐 Fibonacci + ATR للأهداف\n📡 إشارات تلقائية كل 30 دقيقة\n🔄 مراقبة BTC كل دقيقة\n🔬 RSI, MACD, EMA, BB, Stoch, ATR, Ichimoku\n⚙️ توافق 3 فريمات\n⚠️ للأغراض التعليمية فقط",
        "ind_rsi_oversold": "RSI تشبع بيعي", "ind_rsi_buy": "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي", "ind_rsi_sell": "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️", "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up": "EMAs صاعدة 📈", "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low": "بولنجر: دعم سفلي 🟢", "ind_bb_high": "بولنجر: مقاومة عليا 🔴",
        "ind_stoch_low": "Stochastic تشبع بيعي", "ind_stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "welcome": "🐎 Welcome to Abu Mahra Bot!\n\n━━━━━━━━━━━━━━━━━━━━\nSpecializing in:\n₿ Bitcoin  BTC/USD\n\n✨ Features:\n▫️ 1H timeframe based signals\n▫️ Fibonacci + ATR targets\n▫️ Precise support & resistance\n▫️ Auto signals every 30 minutes\n▫️ BTC live SL/TP monitoring\n━━━━━━━━━━━━━━━━━━━━\n⚠️ For educational purposes only",
        "btn_btc": "₿ BTC Trade", "btn_gold": "🥇 Gold Trade",
        "btn_analysis_btc": "📈 BTC Analysis", "btn_analysis_gold": "📈 Gold Analysis",
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
        "update_tp2_hit": "✅✅ TP2 reached! SL moved to TP1",
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
        "about_text": "ℹ️ About Abu Mahra Bot 🐎\n\n⏱️ 1H timeframe as base\n📐 Fibonacci + ATR targets\n📡 Auto signals every 30 minutes\n🔄 BTC live monitoring every minute\n🔬 RSI, MACD, EMA, BB, Stoch, ATR, Ichimoku\n⚙️ 3 timeframe confluence\n⚠️ For educational purposes only",
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


# ==================== البيانات ====================
def get_data(asset="BTC", days=30, interval="hourly"):
    cache_key = asset + "_" + str(days) + "_" + interval
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    symbol = "BTC/USD" if asset == "BTC" else "XAU/USD"
    td_interval = "1h" if interval == "hourly" else "1day"
    outputsize = min(days * 24 if interval == "hourly" else days, 500)

    if TWELVEDATA_KEY:
        try:
            r = requests.get("https://api.twelvedata.com/time_series",
                params={"symbol": symbol, "interval": td_interval,
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

    if asset == "BTC":
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
            if interval == "hourly":
                result = result.resample("1h").interpolate(method="linear").dropna()
            set_cache(cache_key, result)
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
        import time; time.sleep(1)
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=10)
        if r.status_code == 200:
            return r.json()
    except: pass
    return None


# ==================== Fibonacci ====================
def calculate_fibonacci(df):
    window = min(100, len(df))
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
        sl_fib = max([v for v in fib_vals if v < price], default=price - atr)
        sl  = round(min(sl_fib - 0.2*atr, price - 0.8*atr), 2)
        tp1_c = [v for v in fib_vals if v > price + 0.5*atr]
        tp1 = round(tp1_c[0] if tp1_c else price + 0.8*atr, 2)
        tp2_c = [v for v in fib_vals if v > tp1 + 0.3*atr]
        tp2 = round(max(tp2_c[0] if tp2_c else price + 1.8*atr, price + 1.5*atr), 2)
        # TP3: أقصى حد 4 ATR من السعر (واقعي للـ scalp)
        tp3_raw = round(price + 2.5*atr, 2)
        ext_v = sorted(extensions.values(), reverse=True)
        tp3_fib = next((v for v in ext_v if tp2 + 0.3*atr < v < price + 3.0*atr), None)
        tp3 = round(min(tp3_fib, tp3_raw) if tp3_fib else tp3_raw, 2)
    else:
        sl_fib = min([v for v in fib_vals if v > price], default=price + atr)
        sl  = round(max(sl_fib + 0.2*atr, price + 0.8*atr), 2)
        tp1_c = [v for v in reversed(fib_vals) if v < price - 0.5*atr]
        tp1 = round(tp1_c[0] if tp1_c else price - 0.8*atr, 2)
        tp2_c = [v for v in reversed(fib_vals) if v < tp1 - 0.3*atr]
        tp2 = round(min(tp2_c[0] if tp2_c else price - 1.8*atr, price - 1.5*atr), 2)
        # TP3: أقصى حد 4 ATR من السعر (واقعي للـ scalp)
        tp3_raw = round(price - 2.5*atr, 2)
        ext_v = sorted(extensions.values())
        tp3_fib = next((v for v in ext_v if price - 3.0*atr < v < tp2 - 0.3*atr), None)
        tp3 = round(max(tp3_fib, tp3_raw) if tp3_fib else tp3_raw, 2)
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
    s1    = safe(last["S1"],  price * 0.99)
    r1    = safe(last["R1"],  price * 1.01)

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
    if 13 <= hour < 16:  return "OVERLAP", 100
    elif 8 <= hour < 16: return "LONDON", 85
    elif 13 <= hour < 21:return "NY", 85
    else:                return "ASIAN", 40


# ==================== Full Analysis ====================
def full_analysis(asset="BTC", uid=0):
    try:
        df_1h = get_data(asset, days=14,  interval="hourly")
        df_4h = get_data(asset, days=30,  interval="hourly")
        df_1d = get_data(asset, days=90,  interval="daily")
        df_1w = get_data(asset, days=365, interval="daily")
    except Exception as e:
        logger.error("Data fetch: " + str(e))
        return None

    if df_1h is None or len(df_1h) < 20:
        logger.warning("Insufficient 1H data for " + asset)
        return None

    session, session_score = get_current_session()

    if df_4h is not None and len(df_4h) > 0:
        try:
            df_4h = df_4h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
        except:
            df_4h = None

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

    buy_c = sum(1 for r in results.values() if r["direction"] == "BUY")
    sel_c = sum(1 for r in results.values() if r["direction"] == "SELL")

    # Session filter
    if session == "ASIAN" and buy_c < 3 and sel_c < 3:
        return None

    if   buy_c == 3: final="BUY";  conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif sel_c == 3: final="SELL"; conf_txt=t(uid,"full_confluence");    frames_conf=85
    elif buy_c == 2: final="BUY";  conf_txt=t(uid,"partial_confluence"); frames_conf=65
    elif sel_c == 2: final="SELL"; conf_txt=t(uid,"partial_confluence"); frames_conf=65
    else:
        # لا توافق — أرجع NEUTRAL للتحليل فقط
        main2 = results.get("1h") or list(results.values())[0]
        fib_l2, fib_e2, sh2, sl2 = calculate_fibonacci(df_1h)
        nf2, fk2, _ = find_nearest_fib(main2["price"], fib_l2, "NEUTRAL") if fib_l2 else (main2["price"],"50.0",0)
        kf2 = ["Fib "+k+"%  $"+"{:,.2f}".format(v) for k,v in sorted(fib_l2.items(), key=lambda x:float(x[0]))][:5]
        fl2 = []
        icons2 = {"1h":t(uid,"frame_1h"),"4h":t(uid,"frame_4h"),"1d":t(uid,"frame_1d")}
        for k,r in results.items():
            fl2.append(("🟢" if r["direction"]=="BUY" else "🔴")+" "+icons2.get(k,"")+": "+r["direction"]+" ("+str(r["conf"])+"%)")
        return {"final":"NEUTRAL","asset":asset,"confluence_txt":t(uid,"no_confluence"),"base_conf":0,
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

    # ✅ سعر الدخول الذكي: أقرب Fib ضمن 0.8% من السعر
    if dist_pct <= 0.8:
        entry_price = nearest_fib  # ادخل عند مستوى Fib
    elif final == "BUY":
        # BUY: ادخل عند أقرب دعم (Fib أدنى من السعر)
        fib_vals_sorted = sorted(fib_levels.values())
        supports = [v for v in fib_vals_sorted if v < price]
        entry_price = round(supports[-1], 2) if supports and (price - supports[-1])/price < 0.015 else price
    else:
        # SELL: ادخل عند أقرب مقاومة (Fib أعلى من السعر)
        fib_vals_sorted = sorted(fib_levels.values())
        resistances = [v for v in fib_vals_sorted if v > price]
        entry_price = round(resistances[0], 2) if resistances and (resistances[0] - price)/price < 0.015 else price

    sl, tp1, tp2, tp3, rr = get_fib_targets(price, fib_levels, fib_ext, final, atr)

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

    # Market Regime
    regime, regime_strength = detect_market_regime(df_1h)
    # VOLATILE — تحذير فقط

    # RSI Divergence
    divergence = "NONE"
    try:
        df_div = calc_indicators(df_1h.tail(30).copy())
        divergence = detect_rsi_divergence(df_div)
        if   divergence == "BEARISH" and final == "SELL": base_conf = min(base_conf + 8, 89)
        elif divergence == "BULLISH" and final == "BUY":  base_conf = min(base_conf + 8, 89)
        elif divergence == "BEARISH" and final == "BUY":  base_conf = max(base_conf - 10, 50)
        elif divergence == "BULLISH" and final == "SELL": base_conf = max(base_conf - 10, 50)
    except: pass

    # Order Blocks & Liquidity
    bull_obs, bear_obs = find_order_blocks(df_1h)
    buy_liq, sell_liq  = find_liquidity_zones(df_1h)

    # SL عند منطقة سيولة
    try:
        if final == "SELL" and buy_liq:
            liq_above = [lv for lv in buy_liq if lv > price]
            if liq_above:
                liq_sl = round(min(liq_above) * 1.002, 2)
                sl = round(min(sl, liq_sl), 2) if liq_sl < sl * 1.01 else sl
        elif final == "BUY" and sell_liq:
            liq_below = [lv for lv in sell_liq if lv < price]
            if liq_below:
                liq_sl = round(max(liq_below) * 0.998, 2)
                sl = round(max(sl, liq_sl), 2) if liq_sl > sl * 0.99 else sl
        rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
    except: pass

    # Monthly Bias
    monthly_bias = get_monthly_bias(df_1d)
    # monthly bias — تحذير فقط، لا حجب

    # Weekly Trend
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
            pass  # weekly trend — تحذير فقط في risk_warnings
    except Exception as e:
        logger.warning("Weekly: " + str(e))

    # EMA200 Filter
    try:
        df_1h_c = calc_indicators(df_1h.tail(210).copy())
        e200 = safe(df_1h_c.iloc[-1]["EMA200"], float("nan"))
        pass  # EMA200 — تحذير فقط في risk_warnings
    except: pass

    # تحقق منطقية الأهداف
    if final == "BUY":
        if not (sl < price < tp1 < tp2 < tp3):
            sl=round(price-atr,2); tp1=round(price+atr,2); tp2=round(price+2*atr,2); tp3=round(price+3.5*atr,2)
    else:
        if not (tp3 < tp2 < tp1 < price < sl):
            sl=round(price+atr,2); tp1=round(price-atr,2); tp2=round(price-2*atr,2); tp3=round(price-3.5*atr,2)

    rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
    if rr < 1.0:
        sl = round(price-1.2*atr,2) if final=="BUY" else round(price+1.2*atr,2)
        rr = round(abs(tp2-price)/abs(sl-price),2) if abs(sl-price)>0 else 1.0

    # ==================== تقييم المخاطر ====================
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
    an      = "BTC/USD" if res["asset"] == "BTC" else "XAU/USD"
    is_sell = res["final"] == "SELL"
    dir_emoji = "🔴" if is_sell else "🟢"
    dir_txt   = t(uid,"sell") if is_sell else t(uid,"buy")
    header    = t(uid,"auto_header") if auto else t(uid,"trade_header")
    trade_num = res.get("id","")
    num_str   = "  #"+str(trade_num) if trade_num else ""

    lines = [
        "╔══════════════════════════╗",
        "  "+ai+" "+an+"  "+dir_emoji+"  "+dir_txt+num_str,
        "  ⚡ "+header,
        "╚══════════════════════════╝",
        "",
        "💵 "+t(uid,"current_price")+"   $"+"{:,.2f}".format(res["price"]),
        "📍 "+t(uid,"entry")+"   $"+"{:,.2f}".format(res.get("entry_price", res["price"])),
        "📐 "+t(uid,"fib_entry")+"   Fib "+res["fib_key"]+"% ($"+"{:,.2f}".format(res["nearest_fib"])+")",
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

    # ==================== مستوى الخطورة والتحذيرات ====================
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
    an = "BTC/USD" if res["asset"] == "BTC" else "XAU/USD"
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
        [InlineKeyboardButton(t(uid,"btn_btc"),  callback_data="trade_BTC"),
         InlineKeyboardButton(t(uid,"btn_gold"), callback_data="trade_GOLD")],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"),  callback_data="analysis_BTC"),
         InlineKeyboardButton(t(uid,"btn_analysis_gold"), callback_data="analysis_GOLD")],
        [InlineKeyboardButton(t(uid,"btn_prices"), callback_data="prices"),
         InlineKeyboardButton(t(uid,"btn_trades"), callback_data="open_trades")],
        [InlineKeyboardButton(t(uid,"btn_stats"),  callback_data="stats"),
         InlineKeyboardButton(t(uid,"btn_about"),  callback_data="about")],
        [InlineKeyboardButton(t(uid,"btn_lang"),   callback_data="change_lang")],
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data="lang_ar"),
        InlineKeyboardButton("English", callback_data="lang_en"),
    ]])

def confirm_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ نعم، افتح جديدة", callback_data="confirm_replace_yes"),
        InlineKeyboardButton("❌ لا، خلي القديمة", callback_data="confirm_replace_no"),
    ]])


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
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    await query.answer()
    if uid not in ALLOWED_USERS: return

    # ── اللغة ──
    if data == "lang_ar":
        user_languages[uid] = "ar"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == "lang_en":
        user_languages[uid] = "en"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif data == "change_lang":
        await query.message.reply_text(t(uid,"choose_lang"), reply_markup=lang_keyboard())

    # ── صفقة ──
    elif data.startswith("trade_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            res = full_analysis(asset, uid)
            if not res:
                await query.message.reply_text("⚪ البيانات غير متوفرة الآن\nحاول بعد دقيقتين 🕐"); return
            if res["final"] == "NEUTRAL":
                fls = res.get("frame_lines", [])
                parts = ["⚪ لا توجد إشارة واضحة الآن", ""]
                if fls:
                    parts.append("📊 حالة الفريمات:")
                    for fl in fls:
                        parts.append("  " + fl)
                parts += ["", "💡 الفريمات غير متوافقة — انتظر إشارة أقوى"]
                await query.message.reply_text("\n".join(parts)); return
            global trade_counter
            trade_counter += 1
            res["id"] = trade_counter
            await query.message.reply_text(build_trade_msg(res, uid))
            new_trade = {
                "id": trade_counter, "asset": res["asset"],
                "direction": res["final"], "entry": res["price"],
                "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"], "tp3": res["tp3"],
                "atr": res["atr"], "tp1_hit": False, "tp2_hit": False,
                "chat_id": query.message.chat_id, "open_time": gmt_now(),
            }
            already_open = next((tr for tr in active_trades
                if tr["asset"] == new_trade["asset"] and tr["direction"] == new_trade["direction"]), None)
            if already_open:
                dir_ar = "شراء BUY" if new_trade["direction"] == "BUY" else "بيع SELL"
                ai_sym = "₿ BTC" if new_trade["asset"] == "BTC" else "🥇 GOLD"
                pending_trade_replace[uid] = {"new": new_trade, "old": already_open, "res": res}
                await query.message.reply_text(
                    "⚠️ في صفقة مفتوحة بالفعل\n"+ai_sym+" — "+dir_ar+"\n\nتبي تغلق القديمة وتفتح صفقة جديدة؟",
                    reply_markup=confirm_keyboard())
            else:
                active_trades.append(new_trade)
                if res["asset"] == "BTC":
                    active_btc_trade["data"] = new_trade
                save_trades()
        except Exception as e:
            logger.error("Trade handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    # ── تأكيد استبدال الصفقة ──
    elif data == "confirm_replace_yes":
        pending = pending_trade_replace.pop(uid, None)
        if pending:
            old_tr = pending["old"]
            if old_tr in active_trades:
                active_trades.remove(old_tr)
            new_tr  = pending["new"]
            res_old = pending["res"]
            active_trades.append(new_tr)
            if new_tr["asset"] == "BTC":
                active_btc_trade["data"] = new_tr
            save_trades()
            # ✅ عرض الصفقة المحفوظة مباشرة بدون تحليل جديد
            await query.message.reply_text(build_trade_msg(res_old, uid))
        else:
            await query.message.reply_text("⚠️ انتهت صلاحية الطلب، اطلب صفقة جديدة")

    elif data == "confirm_replace_no":
        pending_trade_replace.pop(uid, None)
        await query.message.reply_text("👍 تم الإبقاء على الصفقة القديمة")

    # ── تحليل ──
    elif data.startswith("analysis_"):
        asset = data.split("_")[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            res = full_analysis(asset, uid)
            if not res:
                await query.message.reply_text("⚪ الفلاتر منعت التحليل أو البيانات غير متوفرة\n\nحاول بعد دقيقتين 🕐"); return
            await query.message.reply_text(build_analysis_msg(res, uid))
        except Exception as e:
            logger.error("Analysis handler: " + str(e))
            await query.message.reply_text(t(uid,"error") + str(e))

    # ── الأسعار ──
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

    # ── الصفقات المفتوحة ──
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

    # ── الإحصائيات ──
    elif data == "stats":
        stats    = load_stats()
        total    = stats.get("total", 0)
        wins     = stats.get("wins", 0)
        losses   = stats.get("losses", 0)
        total_rr = stats.get("total_rr", 0.0)
        win_rate = round(wins / total * 100) if total > 0 else 0
        avg_rr   = round(total_rr / wins, 2) if wins > 0 else 0
        bar_w    = "█" * (win_rate // 10) + "░" * (10 - win_rate // 10)
        lines = [
            "╔"+"═"*26+"╗", "  📊 إحصائيات أبو مهرة", "╚"+"═"*26+"╝", "",
            "  إجمالي الصفقات:  "+str(total),
            "  ✅ رابحة:         "+str(wins),
            "  ❌ خاسرة:         "+str(losses), "",
            "  🎯 نسبة النجاح",
            "  "+bar_w+"  "+str(win_rate)+"%",
            "  ⚖️ متوسط RR:  1:"+str(avg_rr), "",
            "━"*24, "🕐 "+gmt_now(),
        ]
        await query.message.reply_text("\n".join(lines))

    elif data == "about":
        await query.message.reply_text(t(uid,"about_text"))


# ==================== إشارات تلقائية ====================
async def auto_signals(context):
    try:
        res = full_analysis("BTC", 0)
        if res and res["final"] != "NEUTRAL" and res["base_conf"] >= MIN_CONFIDENCE:
            global trade_counter
            now_ts  = datetime.now(timezone.utc).timestamp()
            last_ts = last_signal_time.get("BTC", 0)
            if (now_ts - last_ts) < SPAM_COOLDOWN:
                return
            last_signal_time["BTC"] = now_ts
            trade_counter += 1
            res["id"] = trade_counter
            await context.bot.send_message(chat_id=CHANNEL_ID, text=build_trade_msg(res, 0, auto=True))
            new_trade = {
                "id": trade_counter, "asset": "BTC",
                "direction": res["final"], "entry": res["price"],
                "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"], "tp3": res["tp3"],
                "atr": res["atr"], "tp1_hit": False, "tp2_hit": False,
                "chat_id": CHANNEL_ID, "open_time": gmt_now(),
            }
            already_open = any(tr["asset"] == "BTC" and tr["direction"] == new_trade["direction"] for tr in active_trades)
            if not already_open:
                active_trades.append(new_trade)
                active_btc_trade["data"] = new_trade
                save_trades()
    except Exception as e:
        logger.error("Auto signals: " + str(e))


# ==================== مراقبة الصفقات ====================
async def monitor_btc(context):
    if not active_trades:
        return
    try:
        current_btc = get_btc_price()
        to_remove   = []
        for trade in list(active_trades):
            try:
                current  = current_btc
                if not current: continue
                uid      = 0
                chat_id  = trade["chat_id"]
                direction= trade["direction"]
                atr      = trade["atr"]
                tp1      = trade["tp1"]; tp2 = trade["tp2"]; tp3 = trade["tp3"]
                trade_id = trade.get("id","?")
                update_msg= None; closed = False

                if direction == "BUY":
                    if current >= tp3:
                        update_msg = "🏆 #"+str(trade_id)+" الهدف الثالث تم! صفقة مغلقة بنجاح 🎉"
                        record_trade_result(trade_id, "win", trade.get("rr",0)); closed = True
                    elif not trade["tp1_hit"] and current >= tp1:
                        trade["tp1_hit"] = True; trade["sl"] = trade["entry"]
                        update_msg = "✅ #"+str(trade_id)+" "+t(uid,"update_tp1_hit")
                    elif trade["tp1_hit"] and not trade["tp2_hit"] and current >= tp2:
                        trade["tp2_hit"] = True; trade["sl"] = tp1
                        update_msg = "✅✅ #"+str(trade_id)+" "+t(uid,"update_tp2_hit")
                    elif current <= trade["sl"]:
                        update_msg = "🛑 #"+str(trade_id)+" وقف الخسارة تم! صفقة مغلقة"
                        record_trade_result(trade_id, "loss"); closed = True
                    elif trade["tp1_hit"] and current > tp1 + 0.5*atr:
                        new_sl = round(current - 0.8*atr, 2)
                        if new_sl > trade["sl"]:
                            trade["sl"] = new_sl
                            update_msg = "📊 #"+str(trade_id)+" "+t(uid,"update_sl_moved")
                else:
                    if current <= tp3:
                        update_msg = "🏆 #"+str(trade_id)+" الهدف الثالث تم! صفقة مغلقة بنجاح 🎉"
                        record_trade_result(trade_id, "win", trade.get("rr",0)); closed = True
                    elif not trade["tp1_hit"] and current <= tp1:
                        trade["tp1_hit"] = True; trade["sl"] = trade["entry"]
                        update_msg = "✅ #"+str(trade_id)+" "+t(uid,"update_tp1_hit")
                    elif trade["tp1_hit"] and not trade["tp2_hit"] and current <= tp2:
                        trade["tp2_hit"] = True; trade["sl"] = tp1
                        update_msg = "✅✅ #"+str(trade_id)+" "+t(uid,"update_tp2_hit")
                    elif current >= trade["sl"]:
                        update_msg = "🛑 #"+str(trade_id)+" وقف الخسارة تم! صفقة مغلقة"
                        record_trade_result(trade_id, "loss"); closed = True
                    elif trade["tp1_hit"] and current < tp1 - 0.5*atr:
                        new_sl = round(current + 0.8*atr, 2)
                        if new_sl < trade["sl"]:
                            trade["sl"] = new_sl
                            update_msg = "📊 #"+str(trade_id)+" "+t(uid,"update_sl_moved")

                if update_msg:
                    await context.bot.send_message(chat_id=chat_id,
                        text=build_update_msg(trade, current, update_msg, uid))
                if closed:
                    to_remove.append(trade)
            except Exception as e:
                logger.error("Monitor trade: " + str(e))

        for tr in to_remove:
            if tr in active_trades:
                active_trades.remove(tr)
        if to_remove:
            save_trades()
    except Exception as e:
        logger.error("Monitor: " + str(e))


# ==================== تنبيهات ذكية ====================
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

        if alerts:
            msg = ["╔══════════════════════════╗","  ⚡ تنبيه ذكي — ₿ BTC/USD","╚══════════════════════════╝",
                   "","  💵 السعر: $"+"{:,.2f}".format(price),""]
            for a in alerts: msg.append("  "+a)
            msg += ["","━━━━━━━━━━━━━━━━━━━━━━━━","🕐 "+gmt_now(),"⚠️ للأغراض التعليمية فقط"]
            await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(msg))
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


# ==================== الإحصائيات ====================
def load_stats():
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except:
        return {"total":0,"wins":0,"losses":0,"total_rr":0.0,"trades":[]}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def record_trade_result(trade_id, result, rr=0):
    stats = load_stats()
    stats["total"] += 1
    if result == "win":
        stats["wins"] += 1; stats["total_rr"] += rr
    else:
        stats["losses"] += 1
    stats["trades"].append({"id":trade_id,"result":result,"rr":rr,"time":gmt_now()})
    stats["trades"] = stats["trades"][-50:]
    save_stats(stats)


# ==================== ملخص يومي ====================
async def send_daily_summary(context):
    try:
        stats    = load_stats()
        total    = stats.get("total",0); wins = stats.get("wins",0)
        losses   = stats.get("losses",0); total_rr = stats.get("total_rr",0.0)
        win_rate = round(wins/total*100) if total > 0 else 0
        avg_rr   = round(total_rr/wins,2) if wins > 0 else 0
        lines = [
            "╔══════════════════════════╗","  📊 الملخص اليومي - أبو مهرة","╚══════════════════════════╝","",
            "━━━━  📈 الأداء  ━━━━",
            "  إجمالي الصفقات:  "+str(total),
            "  ✅ رابحة:         "+str(wins),
            "  ❌ خاسرة:         "+str(losses),
            "  🎯 نسبة النجاح:   "+str(win_rate)+"%",
            "  ⚖️ متوسط RR:      1:"+str(avg_rr),"",
        ]
        if active_trades:
            lines += ["━━━━  🔓 صفقات مفتوحة: "+str(len(active_trades))+"  ━━━━"]
            for tr in active_trades:
                lines.append("  "+("₿" if tr["asset"]=="BTC" else "🥇")+" #"+str(tr.get("id","?"))
                             +"  "+("🔴 SELL" if tr["direction"]=="SELL" else "🟢 BUY")
                             +"  دخول: $"+"{:,.0f}".format(tr["entry"]))
            lines.append("")
        lines += ["━━━━━━━━━━━━━━━━━━━━━━━━","🕐 "+gmt_now(),"⚠️ للأغراض التعليمية فقط"]
        await context.bot.send_message(chat_id=CHANNEL_ID, text="\n".join(lines))
    except Exception as e:
        logger.error("Daily summary: " + str(e))


# ==================== Main ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_signals,      interval=AUTO_INTERVAL_MIN*60, first=30)
    app.job_queue.run_repeating(monitor_btc,       interval=60,                   first=30)
    app.job_queue.run_repeating(send_smart_alerts, interval=45*60,                first=120)
    app.job_queue.run_repeating(send_news,         interval=4*60*60,              first=300)
    app.job_queue.run_daily(send_daily_summary, time=__import__("datetime").time(6, 0, 0))
    logger.info("🐎 Abu Mahra Bot - Ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
