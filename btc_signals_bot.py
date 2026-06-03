import os
import logging
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import ta

BOT_TOKEN  = os.environ.get("BOT_TOKEN",  "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
AUTO_INTERVAL_MIN = 30
MONITOR_MIN       = 5
MIN_CONFIDENCE    = 68

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
user_languages = {}
active_btc_trade = {}  # فقط BTC للمراقبة

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
CONFUSED_AR = [
    "ما فهمت 😅 استخدم الأزرار 👇",
    "🤔 اختر من القائمة 👇",
]
CONFUSED_EN = [
    "Didn't get that 😅 Use the buttons 👇",
    "🤔 Choose from the menu 👇",
]

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
▫️ صفقات قصيرة (Scalp) دقيقة
▫️ إشارات تلقائية كل 30 دقيقة
▫️ مراقبة BTC وتحديث SL/TP تلقائياً
▫️ تحليل 3 فريمات زمنية
▫️ درجة الثقة والمخاطرة
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

        "trade_header":    "⚡ صفقة قصيرة (Scalp) - أبو مهرة",
        "auto_header":     "🔔 إشارة تلقائية - أبو مهرة",
        "update_header":   "🔄 تحديث صفقة BTC - أبو مهرة",
        "analysis_header": "📊 تحليل السوق - أبو مهرة",

        "entry":     "💰 سعر الدخول",
        "direction": "📌 نوع الصفقة",
        "buy":       "شراء  BUY ⬆️",
        "sell":      "بيع  SELL ⬇️",
        "targets_section": "🎯 الأهداف",
        "tp1": "الهدف الأول   TP1",
        "tp2": "الهدف الثاني  TP2",
        "tp3": "الهدف الثالث  TP3",
        "sl":  "وقف الخسارة  SL",
        "rr":  "⚖️ العائد / المخاطرة",
        "leverage":  "🔧 الرافعة المقترحة",
        "timeframe": "⏱️ الفريم",
        "hold_time": "⏳ المدة",
        "support":    "🟢 دعم",
        "resistance": "🔴 مقاومة",
        "confluence": "🔗 توافق الفريمات",
        "frame_15m": "⚡ 15د",
        "frame_1h":  "🕐 ساعة",
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

⚡ صفقات قصيرة (Scalp) فقط
📡 إشارات تلقائية كل 30 دقيقة
🔄 مراقبة BTC وتحديث SL/TP كل 5 دقائق
🔬 المؤشرات: RSI, MACD, EMA, BB, Stoch, ATR, Pivot
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
▫️ Scalp trade signals
▫️ Auto signals every 30 minutes
▫️ BTC live SL/TP monitoring
▫️ 3 timeframe confluence
▫️ Confidence & risk scoring
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

        "trade_header":    "⚡ Scalp Trade - Abu Mahra",
        "auto_header":     "🔔 Auto Signal - Abu Mahra",
        "update_header":   "🔄 BTC Trade Update - Abu Mahra",
        "analysis_header": "📊 Market Analysis - Abu Mahra",

        "entry":     "💰 Entry Price",
        "direction": "📌 Trade Type",
        "buy":       "BUY ⬆️",
        "sell":      "SELL ⬇️",
        "targets_section": "🎯 Targets",
        "tp1": "First Target   TP1",
        "tp2": "Second Target  TP2",
        "tp3": "Third Target   TP3",
        "sl":  "Stop Loss      SL",
        "rr":  "⚖️ Reward / Risk",
        "leverage":  "🔧 Suggested Leverage",
        "timeframe": "⏱️ Timeframe",
        "hold_time": "⏳ Hold Time",
        "support":    "🟢 Support",
        "resistance": "🔴 Resistance",
        "confluence": "🔗 Timeframe Confluence",
        "frame_15m": "⚡ 15m",
        "frame_1h":  "🕐 1h",
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

⚡ Scalp trades only
📡 Auto signals every 30 minutes
🔄 BTC live SL/TP monitoring every 5 minutes
🔬 Indicators: RSI, MACD, EMA, BB, Stoch, ATR, Pivot
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
def get_data(asset="BTC", days=7, interval="hourly"):
    try:
        coin = "bitcoin" if asset == "BTC" else "tether-gold"
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/" + coin + "/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": interval},
            timeout=15)
        data = r.json()
        df = pd.DataFrame(data['prices'], columns=['timestamp', 'Close'])
        df['Volume'] = [v[1] for v in data['total_volumes']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        df['High'] = df['Close'].rolling(3).max()
        df['Low']  = df['Close'].rolling(3).min()
        df['Open'] = df['Close'].shift(1)
        return df.dropna()
    except Exception as e:
        logger.error(asset + " Error: " + str(e))
        return None

def get_btc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=10)
        return float(r.json()['bitcoin']['usd'])
    except:
        return None

def get_prices():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether-gold&vs_currencies=usd&include_24hr_change=true",
            timeout=10)
        return r.json()
    except:
        return None


# ==================== التحليل ====================
def calc_indicators(df):
    c = df['Close']; h = df['High']; l = df['Low']
    df['EMA9']  = ta.trend.EMAIndicator(c, window=9).ema_indicator()
    df['EMA21'] = ta.trend.EMAIndicator(c, window=21).ema_indicator()
    df['EMA50'] = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    df['RSI']   = ta.momentum.RSIIndicator(c, window=14).rsi()
    macd = ta.trend.MACD(c)
    df['MACD']  = macd.macd()
    df['MACD_S']= macd.macd_signal()
    bb = ta.volatility.BollingerBands(c)
    df['BB_U'] = bb.bollinger_hband()
    df['BB_L'] = bb.bollinger_lband()
    df['ATR']  = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    stoch = ta.momentum.StochasticOscillator(h, l, c)
    df['Stoch'] = stoch.stoch()
    df['Pivot'] = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df['R1'] = 2 * df['Pivot'] - l.shift(1)
    df['S1'] = 2 * df['Pivot'] - h.shift(1)
    return df

def analyze_frame(df, uid=0):
    df = calc_indicators(df)
    last = df.iloc[-1]
    price = last['Close']
    sb = ss = 0
    details = []
    rsi = last['RSI']
    if rsi < 30:   sb += 25; details.append(t(uid,'ind_rsi_oversold') + " (" + str(round(rsi,0)) + ") 🟢")
    elif rsi < 45: sb += 12; details.append(t(uid,'ind_rsi_buy') + " (" + str(round(rsi,0)) + ")")
    elif rsi > 70: ss += 25; details.append(t(uid,'ind_rsi_overbought') + " (" + str(round(rsi,0)) + ") 🔴")
    elif rsi > 55: ss += 12; details.append(t(uid,'ind_rsi_sell') + " (" + str(round(rsi,0)) + ")")
    if last['MACD'] > last['MACD_S']: sb += 20; details.append(t(uid,'ind_macd_pos'))
    else: ss += 20; details.append(t(uid,'ind_macd_neg'))
    if last['EMA9'] > last['EMA21'] > last['EMA50']:   sb += 20; details.append(t(uid,'ind_ema_up'))
    elif last['EMA9'] < last['EMA21'] < last['EMA50']: ss += 20; details.append(t(uid,'ind_ema_down'))
    if price <= last['BB_L']:   sb += 15; details.append(t(uid,'ind_bb_low'))
    elif price >= last['BB_U']: ss += 15; details.append(t(uid,'ind_bb_high'))
    if last['Stoch'] < 20:   sb += 10; details.append(t(uid,'ind_stoch_low'))
    elif last['Stoch'] > 80: ss += 10; details.append(t(uid,'ind_stoch_high'))
    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf = round(max(sb, ss) / total * 100) if total > 0 else 50
    return {
        "direction": direction, "conf": conf, "sb": sb, "ss": ss,
        "rsi": round(rsi, 1), "price": round(price, 2), "atr": round(last['ATR'], 2),
        "details": details[:4],
        "support": round(last['S1'], 2), "resistance": round(last['R1'], 2),
        "macd_bull": last['MACD'] > last['MACD_S'],
        "ema_bull": last['EMA9'] > last['EMA21'] > last['EMA50'],
        "ema_bear": last['EMA9'] < last['EMA21'] < last['EMA50'],
        "bb_zone": "low" if price <= last['BB_L'] else "high" if price >= last['BB_U'] else "mid",
    }

def scalp_analysis(asset="BTC", uid=0):
    frames = {
        "15m": get_data(asset, days=3,  interval="hourly"),
        "1h":  get_data(asset, days=7,  interval="hourly"),
        "1d":  get_data(asset, days=30, interval="daily"),
    }
    results = {}
    for label, df in frames.items():
        if df is not None and len(df) >= 20:
            results[label] = analyze_frame(df, uid)
    if len(results) < 2:
        return None

    buy_c = sum(1 for r in results.values() if r['direction'] == "BUY")
    sel_c = sum(1 for r in results.values() if r['direction'] == "SELL")

    if buy_c == 3:   final = "BUY";  conf_txt = t(uid,"full_confluence");    base_conf = 92
    elif buy_c == 2: final = "BUY";  conf_txt = t(uid,"partial_confluence"); base_conf = 74
    elif sel_c == 3: final = "SELL"; conf_txt = t(uid,"full_confluence");    base_conf = 92
    elif sel_c == 2: final = "SELL"; conf_txt = t(uid,"partial_confluence"); base_conf = 74
    else: return {"final": "NEUTRAL", "confluence_txt": t(uid,"no_confluence")}

    main  = results.get("1h") or results.get("15m") or list(results.values())[0]
    price = main['price']
    atr   = main['atr']

    if final == "BUY":
        sl  = round(price - 0.8*atr, 2)
        tp1 = round(price + 0.6*atr, 2)
        tp2 = round(price + 1.3*atr, 2)
        tp3 = round(price + 2.2*atr, 2)
    else:
        sl  = round(price + 0.8*atr, 2)
        tp1 = round(price - 0.6*atr, 2)
        tp2 = round(price - 1.3*atr, 2)
        tp3 = round(price - 2.2*atr, 2)

    rr = round(abs(tp2-price) / abs(sl-price), 2) if abs(sl-price) > 0 else 0
    risk = 100 - base_conf
    if main['rsi'] < 25 or main['rsi'] > 75: risk += 10
    risk = min(risk, 99)
    if risk < 30:   rl = t(uid,"risk_low");  rm = t(uid,"risk_low_msg")
    elif risk < 55: rl = t(uid,"risk_med");  rm = t(uid,"risk_med_msg")
    else:           rl = t(uid,"risk_high"); rm = t(uid,"risk_high_msg")

    lang = user_languages.get(uid, "ar")
    frame_lines = []
    icons = {"15m": t(uid,"frame_15m"), "1h": t(uid,"frame_1h"), "1d": t(uid,"frame_1d")}
    for k, r in results.items():
        icon = "🟢" if r['direction'] == "BUY" else "🔴"
        frame_lines.append(icon + " " + icons.get(k,'') + ": " + r['direction'] + " (" + str(r['conf']) + "%)")

    return {
        "final": final, "asset": asset,
        "confluence_txt": conf_txt, "base_conf": base_conf,
        "price": price, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": atr,
        "risk_pct": risk, "risk_label": rl, "risk_msg": rm,
        "frame_lines": frame_lines, "ind_details": main['details'],
        "rsi": main['rsi'], "support": main['support'], "resistance": main['resistance'],
        "macd_bull": main['macd_bull'], "ema_bull": main['ema_bull'],
        "ema_bear": main['ema_bear'], "bb_zone": main['bb_zone'],
        "leverage_ar": "10x — 15x\n⚠️ لا تتجاوز 15x للمبتدئين",
        "leverage_en": "10x — 15x\n⚠️ Max 15x for beginners",
        "tf_ar": "15 دقيقة — ساعة", "tf_en": "15min — 1 hour",
        "hold_ar": "دقائق حتى ساعات قليلة", "hold_en": "Minutes to a few hours",
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

    lines = [
        emoji*3 + "  " + ai + " " + an + "  " + emoji*3,
        header,
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        t(uid,'direction') + ":  " + dir_txt,
        t(uid,'entry') + ":  $" + "{:,.2f}".format(res['price']),
        "",
        "━━━━  " + t(uid,'targets_section') + "  ━━━━",
        "✅  " + t(uid,'tp1') + "  »  $" + "{:,.2f}".format(res['tp1']),
        "✅  " + t(uid,'tp2') + "  »  $" + "{:,.2f}".format(res['tp2']),
        "✅  " + t(uid,'tp3') + "  »  $" + "{:,.2f}".format(res['tp3']),
        "🛑  " + t(uid,'sl')  + "  »   $" + "{:,.2f}".format(res['sl']),
        t(uid,'rr') + ":  1:" + str(res['rr']),
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
    ai      = "₿"
    an      = "BTC/USD"
    dir_txt = t(uid,"buy") if trade['direction'] == "BUY" else t(uid,"sell")
    lines = [
        "🔄  " + ai + " " + an + "  •  " + t(uid,'update_header'),
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
            res = scalp_analysis(asset, uid)
            if not res or res['final'] == "NEUTRAL":
                await query.message.reply_text(t(uid,"no_signal")); return
            await query.message.reply_text(build_trade_msg(res, uid))
            # مراقبة BTC فقط
            if asset == "BTC":
                active_btc_trade['data'] = {
                    "asset": "BTC", "direction": res['final'],
                    "entry": res['price'], "sl": res['sl'],
                    "tp1": res['tp1'], "tp2": res['tp2'], "tp3": res['tp3'],
                    "atr": res['atr'], "tp1_hit": False, "tp2_hit": False,
                    "chat_id": query.message.chat_id,
                }
                logger.info("📌 BTC صفقة مفتوحة - " + res['final'] + " @ " + str(res['price']))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data.startswith('analysis_'):
        asset = data.split('_')[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            res = scalp_analysis(asset, uid)
            if not res:
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


# ==================== إشارات تلقائية كل 30 دقيقة ====================
async def auto_signals(context):
    try:
        for asset in ["BTC", "GOLD"]:
            res = scalp_analysis(asset, 0)
            if res and res['final'] != "NEUTRAL" and res['base_conf'] >= MIN_CONFIDENCE:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_trade_msg(res, 0, auto=True))
                # مراقبة BTC فقط
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


# ==================== مراقبة BTC فقط كل 5 دقائق ====================
async def monitor_btc(context):
    if 'data' not in active_btc_trade:
        return

    trade = active_btc_trade['data']
    try:
        current = get_btc_price()
        if not current:
            return

        entry     = trade['entry']
        sl        = trade['sl']
        tp1       = trade['tp1']
        tp2       = trade['tp2']
        tp3       = trade['tp3']
        atr       = trade['atr']
        direction = trade['direction']
        chat_id   = trade['chat_id']
        uid       = 0
        update_msg = None

        if direction == "BUY":
            if not trade['tp1_hit'] and current >= tp1:
                trade['tp1_hit'] = True
                trade['sl'] = entry
                update_msg = t(uid,"update_tp1_hit")
            elif not trade['tp2_hit'] and current >= tp2:
                trade['tp2_hit'] = True
                trade['sl'] = tp1
                update_msg = t(uid,"update_tp2_hit")
            elif current <= sl * 1.003:
                update_msg = t(uid,"update_near_sl")
            elif trade['tp1_hit'] and current > tp1 + 0.5*atr:
                new_sl = round(current - 0.8*atr, 2)
                if new_sl > trade['sl']:
                    trade['sl'] = new_sl
                    update_msg = t(uid,"update_sl_moved")
            if current >= tp3:
                update_msg = t(uid,"update_tp3_hit")
                active_btc_trade.clear()

        else:  # SELL
            if not trade['tp1_hit'] and current <= tp1:
                trade['tp1_hit'] = True
                trade['sl'] = entry
                update_msg = t(uid,"update_tp1_hit")
            elif not trade['tp2_hit'] and current <= tp2:
                trade['tp2_hit'] = True
                trade['sl'] = tp1
                update_msg = t(uid,"update_tp2_hit")
            elif current >= sl * 0.997:
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
            logger.info("🔄 BTC Update: " + update_msg)

    except Exception as e:
        logger.error("❌ Monitor BTC: " + str(e))


# ==================== تشغيل ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_signals, interval=AUTO_INTERVAL_MIN*60, first=30)
    app.job_queue.run_repeating(monitor_btc,  interval=MONITOR_MIN*60,       first=60)
    logger.info("🐎 Abu Mahra Bot - BTC Monitor Edition!")
    app.run_polling()

if __name__ == "__main__":
    main()
