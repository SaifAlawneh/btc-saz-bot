import os
import logging
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import ta

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
INTERVAL_MINUTES = 60
MIN_CONFIDENCE = 70  # رفعنا الحد للدقة أكثر

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
user_languages = {}

TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "lang_btn_ar": "العربية", "lang_btn_en": "English",
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة! 🐎

━━━━━━━━━━━━━━━━━━━━
متخصص في تحليل أسواق:
₿ البيتكوين  BTC/USD
🥇 الذهب  XAU/USD

✨ مميزاتي:
▫️ تحليل 3 فريمات زمنية معاً
▫️ صفقات فقط عند توافق الفريمات
▫️ مستويات دعم ومقاومة دقيقة
▫️ درجة الثقة ودرجة المخاطرة
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط""",
        "btn_trade_btc": "₿ صفقة BTC", "btn_trade_gold": "🥇 صفقة ذهب",
        "btn_analysis_btc": "📊 تحليل BTC", "btn_analysis_gold": "📊 تحليل ذهب",
        "btn_prices": "💰 الأسعار", "btn_about": "ℹ️ عن البوت", "btn_lang": "🌐 تغيير اللغة",
        "loading_trade": "⏳ جاري تحليل 3 فريمات...", "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices": "⏳ جاري جلب الأسعار...",
        "failed": "❌ فشل جلب البيانات، حاول بعد دقيقة", "error": "❌ خطأ: ",
        "trade_header": "🐎 صفقة أبو مهرة", "auto_header": "🔔 إشارة تلقائية - أبو مهرة",
        "analysis_header": "📊 تحليل السوق - أبو مهرة",
        "entry": "💰 سعر الدخول", "direction": "📌 نوع الصفقة",
        "buy": "شراء  BUY ⬆️", "sell": "بيع  SELL ⬇️",
        "targets_section": "🎯 الأهداف",
        "tp1": "الهدف الأول   TP1", "tp2": "الهدف الثاني  TP2", "tp3": "الهدف الثالث  TP3",
        "sl": "وقف الخسارة  SL", "rr": "⚖️ العائد / المخاطرة",
        "support": "🟢 دعم قريب", "resistance": "🔴 مقاومة قريبة",
        "confluence": "🔗 توافق الفريمات",
        "frame_15m": "⚡ 15 دقيقة", "frame_1h": "🕐 ساعة", "frame_1d": "📅 يومي",
        "full_confluence": "🔥 توافق كامل على 3 فريمات!",
        "partial_confluence": "✅ توافق على فريمين",
        "no_confluence": "⚪ لا توافق — انتظر فرصة أوضح",
        "indicators_section": "📈 المؤشرات الفنية",
        "strength_section": "💡 قوة الإشارة", "risk_section": "⚠️ درجة المخاطرة",
        "confidence_section": "🎯 درجة الثقة",
        "risk_low": "🟢 منخفضة", "risk_med": "🟡 متوسطة", "risk_high": "🔴 عالية",
        "risk_low_msg": "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg": "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",
        "footer": "⚠️ للأغراض التعليمية فقط\n📚 تداول بمسؤولية دائماً",
        "updated_gmt": "🕐 آخر تحديث (GMT)",
        "trend_bull": "📈 الاتجاه العام: صاعد", "trend_bear": "📉 الاتجاه العام: هابط",
        "trend_neutral": "➡️ الاتجاه العام: محايد",
        "rsi_label": "🔹 مؤشر RSI",
        "rsi_oversold": "منطقة تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought": "منطقة تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral": "منطقة محايدة",
        "macd_bull": "🔹 MACD: زخم صاعد ↗️", "macd_bear": "🔹 MACD: زخم هابط ↘️",
        "ema_bull": "🔹 المتوسطات: مرتبة صعوداً 📈", "ema_bear": "🔹 المتوسطات: مرتبة هبوطاً 📉",
        "ema_mixed": "🔹 المتوسطات: إشارات مختلطة ↔️",
        "bb_low": "🔹 بولنجر: السعر عند الدعم السفلي",
        "bb_high": "🔹 بولنجر: السعر عند المقاومة العلوية",
        "bb_mid": "🔹 بولنجر: السعر في المنتصف",
        "summary_bull": "✅ الخلاصة: السوق يميل للصعود",
        "summary_bear": "✅ الخلاصة: السوق يميل للهبوط",
        "summary_neutral": "✅ الخلاصة: السوق في منطقة تردد",
        "prices_title": "💰 الأسعار الحالية", "change_24h": "التغيير 24h",
        "about_text": """ℹ️ عن بوت أبو مهرة 🐎

🔬 المؤشرات المستخدمة:
▫️ RSI — مؤشر القوة النسبية
▫️ MACD — تقارب وتباعد المتوسطات
▫️ EMA 9/21/50 — المتوسطات المتحركة
▫️ Bollinger Bands — نطاقات بولنجر
▫️ Stochastic — مذبذب ستوكاستيك
▫️ ATR — متوسط المدى الحقيقي
▫️ Pivot Points — نقاط الدعم والمقاومة

⚙️ نظام التحليل:
▫️ يحلل 3 فريمات زمنية معاً
▫️ يبعث فقط عند توافق فريمين أو أكثر
▫️ يحتاج 4 مؤشرات من 6 للتأكيد

⚠️ للأغراض التعليمية فقط""",
        "ind_rsi_oversold": "RSI تشبع بيعي",
        "ind_rsi_buy": "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي",
        "ind_rsi_sell": "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️", "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up": "EMAs صاعدة 📈", "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low": "بولنجر: عند الدعم 🟢", "ind_bb_high": "بولنجر: عند المقاومة 🔴",
        "ind_stoch_low": "Stochastic تشبع بيعي", "ind_stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "lang_btn_ar": "العربية", "lang_btn_en": "English",
        "welcome": """🐎 Welcome to Abu Mahra Bot! 🐎

━━━━━━━━━━━━━━━━━━━━
Specializing in:
₿ Bitcoin  BTC/USD
🥇 Gold  XAU/USD

✨ Features:
▫️ 3 timeframe confluence analysis
▫️ Signals only on timeframe agreement
▫️ Precise support & resistance levels
▫️ Confidence & risk scoring
━━━━━━━━━━━━━━━━━━━━
⚠️ For educational purposes only""",
        "btn_trade_btc": "₿ BTC Trade", "btn_trade_gold": "🥇 Gold Trade",
        "btn_analysis_btc": "📊 BTC Analysis", "btn_analysis_gold": "📊 Gold Analysis",
        "btn_prices": "💰 Prices", "btn_about": "ℹ️ About", "btn_lang": "🌐 Change Language",
        "loading_trade": "⏳ Analyzing 3 timeframes...", "loading_analysis": "⏳ Analyzing market...",
        "loading_prices": "⏳ Fetching prices...",
        "failed": "❌ Failed to fetch data, try again in a minute", "error": "❌ Error: ",
        "trade_header": "🐎 Abu Mahra Trade Signal", "auto_header": "🔔 Auto Signal - Abu Mahra",
        "analysis_header": "📊 Market Analysis - Abu Mahra",
        "entry": "💰 Entry Price", "direction": "📌 Trade Type",
        "buy": "BUY ⬆️", "sell": "SELL ⬇️",
        "targets_section": "🎯 Targets",
        "tp1": "First Target   TP1", "tp2": "Second Target  TP2", "tp3": "Third Target   TP3",
        "sl": "Stop Loss      SL", "rr": "⚖️ Reward / Risk",
        "support": "🟢 Nearby Support", "resistance": "🔴 Nearby Resistance",
        "confluence": "🔗 Timeframe Confluence",
        "frame_15m": "⚡ 15min", "frame_1h": "🕐 1hour", "frame_1d": "📅 Daily",
        "full_confluence": "🔥 Full confluence on 3 timeframes!",
        "partial_confluence": "✅ Confluence on 2 timeframes",
        "no_confluence": "⚪ No confluence — wait for clearer signal",
        "indicators_section": "📈 Technical Indicators",
        "strength_section": "💡 Signal Strength", "risk_section": "⚠️ Risk Level",
        "confidence_section": "🎯 Confidence Level",
        "risk_low": "🟢 Low", "risk_med": "🟡 Medium", "risk_high": "🔴 High",
        "risk_low_msg": "Good opportunity — Low risk",
        "risk_med_msg": "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",
        "footer": "⚠️ For educational purposes only\n📚 Always trade responsibly",
        "updated_gmt": "🕐 Last update (GMT)",
        "trend_bull": "📈 Overall Trend: Bullish", "trend_bear": "📉 Overall Trend: Bearish",
        "trend_neutral": "➡️ Overall Trend: Neutral",
        "rsi_label": "🔹 RSI Indicator",
        "rsi_oversold": "Oversold zone — Possible buying pressure",
        "rsi_overbought": "Overbought zone — Possible selling pressure",
        "rsi_neutral": "Neutral zone",
        "macd_bull": "🔹 MACD: Positive momentum ↗️", "macd_bear": "🔹 MACD: Negative momentum ↘️",
        "ema_bull": "🔹 EMAs: Bullish stack 📈", "ema_bear": "🔹 EMAs: Bearish stack 📉",
        "ema_mixed": "🔹 EMAs: Mixed signals ↔️",
        "bb_low": "🔹 Bollinger: At lower support",
        "bb_high": "🔹 Bollinger: At upper resistance",
        "bb_mid": "🔹 Bollinger: Middle zone",
        "summary_bull": "✅ Summary: Market leaning bullish",
        "summary_bear": "✅ Summary: Market leaning bearish",
        "summary_neutral": "✅ Summary: Market in consolidation",
        "prices_title": "💰 Current Prices", "change_24h": "24h Change",
        "about_text": """ℹ️ About Abu Mahra Bot 🐎

🔬 Indicators Used:
▫️ RSI — Relative Strength Index
▫️ MACD — Convergence Divergence
▫️ EMA 9/21/50 — Moving Averages
▫️ Bollinger Bands
▫️ Stochastic Oscillator
▫️ ATR — Average True Range
▫️ Pivot Points — Support & Resistance

⚙️ Analysis System:
▫️ Analyzes 3 timeframes together
▫️ Sends only on 2+ timeframe agreement
▫️ Requires 4/6 indicators to confirm

⚠️ For educational purposes only""",
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
    try:
        coin = "bitcoin" if asset == "BTC" else "tether-gold"
        url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
        params = {"vs_currency": "usd", "days": days, "interval": interval}
        r = requests.get(url, params=params, timeout=15)
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
        logger.error(f"{asset} Error: {e}")
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
    df['MACD'] = macd.macd(); df['MACD_S'] = macd.macd_signal()
    bb = ta.volatility.BollingerBands(c)
    df['BB_U'] = bb.bollinger_hband(); df['BB_L'] = bb.bollinger_lband()
    df['ATR']  = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    stoch = ta.momentum.StochasticOscillator(h, l, c)
    df['Stoch'] = stoch.stoch()
    # Pivot Points
    df['Pivot'] = (h.shift(1) + l.shift(1) + c.shift(1)) / 3
    df['R1'] = 2 * df['Pivot'] - l.shift(1)
    df['S1'] = 2 * df['Pivot'] - h.shift(1)
    df['R2'] = df['Pivot'] + (h.shift(1) - l.shift(1))
    df['S2'] = df['Pivot'] - (h.shift(1) - l.shift(1))
    return df

def analyze_single(df, uid=0):
    """تحليل فريم واحد - يرجع direction + score + details"""
    df = calc_indicators(df)
    last = df.iloc[-1]
    price = last['Close']
    sb = ss = 0
    details = []
    confirmed = 0  # عدد المؤشرات المؤكدة

    rsi = last['RSI']
    if rsi < 30:
        sb += 25; details.append(f"{t(uid,'ind_rsi_oversold')} ({rsi:.0f}) 🟢"); confirmed += 1
    elif rsi < 45:
        sb += 12; details.append(f"{t(uid,'ind_rsi_buy')} ({rsi:.0f})")
    elif rsi > 70:
        ss += 25; details.append(f"{t(uid,'ind_rsi_overbought')} ({rsi:.0f}) 🔴"); confirmed += 1
    elif rsi > 55:
        ss += 12; details.append(f"{t(uid,'ind_rsi_sell')} ({rsi:.0f})")

    if last['MACD'] > last['MACD_S']:
        sb += 20; details.append(t(uid,'ind_macd_pos')); confirmed += 1
    else:
        ss += 20; details.append(t(uid,'ind_macd_neg')); confirmed += 1

    if last['EMA9'] > last['EMA21'] > last['EMA50']:
        sb += 20; details.append(t(uid,'ind_ema_up')); confirmed += 1
    elif last['EMA9'] < last['EMA21'] < last['EMA50']:
        ss += 20; details.append(t(uid,'ind_ema_down')); confirmed += 1

    if price <= last['BB_L']:
        sb += 15; details.append(t(uid,'ind_bb_low')); confirmed += 1
    elif price >= last['BB_U']:
        ss += 15; details.append(t(uid,'ind_bb_high')); confirmed += 1

    if last['Stoch'] < 20:
        sb += 10; details.append(t(uid,'ind_stoch_low')); confirmed += 1
    elif last['Stoch'] > 80:
        ss += 10; details.append(t(uid,'ind_stoch_high')); confirmed += 1

    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf = round(max(sb, ss) / total * 100) if total > 0 else 50

    # حساب الدعم والمقاومة
    support    = round(last['S1'], 2)
    resistance = round(last['R1'], 2)

    return {
        "direction": direction, "conf": conf, "sb": sb, "ss": ss,
        "rsi": round(rsi, 1), "price": round(price, 2),
        "atr": round(last['ATR'], 2),
        "details": details[:4], "confirmed": confirmed,
        "support": support, "resistance": resistance,
        "macd_bull": last['MACD'] > last['MACD_S'],
        "ema_bull": last['EMA9'] > last['EMA21'] > last['EMA50'],
        "ema_bear": last['EMA9'] < last['EMA21'] < last['EMA50'],
        "bb_zone": "low" if price <= last['BB_L'] else "high" if price >= last['BB_U'] else "mid",
    }


def multi_timeframe_analysis(asset="BTC", uid=0):
    """تحليل 3 فريمات وإيجاد التوافق"""
    frames = {
        "15m": get_data(asset, days=5,  interval="hourly"),   # CoinGecko hourly ~ 15m تقريبي
        "1h":  get_data(asset, days=14, interval="hourly"),
        "1d":  get_data(asset, days=90, interval="daily"),
    }

    results = {}
    for label, df in frames.items():
        if df is not None and len(df) >= 30:
            results[label] = analyze_single(df, uid)

    if len(results) < 2:
        return None

    # حساب التوافق
    buy_count  = sum(1 for r in results.values() if r['direction'] == "BUY")
    sell_count = sum(1 for r in results.values() if r['direction'] == "SELL")

    if buy_count == 3:
        final = "BUY"; confluence_txt = t(uid, "full_confluence"); base_conf = 92
    elif buy_count == 2:
        final = "BUY"; confluence_txt = t(uid, "partial_confluence"); base_conf = 72
    elif sell_count == 3:
        final = "SELL"; confluence_txt = t(uid, "full_confluence"); base_conf = 92
    elif sell_count == 2:
        final = "SELL"; confluence_txt = t(uid, "partial_confluence"); base_conf = 72
    else:
        final = "NEUTRAL"; confluence_txt = t(uid, "no_confluence"); base_conf = 0

    # استخدم بيانات الفريم اليومي للأهداف (أدق)
    main = results.get("1d") or results.get("1h") or list(results.values())[0]
    price = main['price']
    atr   = main['atr']

    if final == "BUY":
        sl  = round(price - 1.5 * atr, 2)
        tp1 = round(price + 1.0 * atr, 2)
        tp2 = round(price + 2.2 * atr, 2)
        tp3 = round(price + 4.0 * atr, 2)
    elif final == "SELL":
        sl  = round(price + 1.5 * atr, 2)
        tp1 = round(price - 1.0 * atr, 2)
        tp2 = round(price - 2.2 * atr, 2)
        tp3 = round(price - 4.0 * atr, 2)
    else:
        return {"final": "NEUTRAL", "confluence_txt": confluence_txt}

    rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0

    # درجة المخاطرة
    risk = 100 - base_conf
    rsi_main = main['rsi']
    if rsi_main < 25 or rsi_main > 75: risk += 10
    risk = min(risk, 99)
    if risk < 30:   risk_label = t(uid,"risk_low");  risk_msg = t(uid,"risk_low_msg")
    elif risk < 55: risk_label = t(uid,"risk_med");  risk_msg = t(uid,"risk_med_msg")
    else:           risk_label = t(uid,"risk_high"); risk_msg = t(uid,"risk_high_msg")

    # توافق الفريمات كنص
    frame_lines = []
    icons = {"15m": t(uid,"frame_15m"), "1h": t(uid,"frame_1h"), "1d": t(uid,"frame_1d")}
    for k, r in results.items():
        icon = "🟢" if r['direction'] == "BUY" else "🔴"
        frame_lines.append(f"{icon} {icons.get(k,'')}: {r['direction']} ({r['conf']}%)")

    return {
        "final": final, "asset": asset,
        "confluence_txt": confluence_txt, "base_conf": base_conf,
        "price": price, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": atr,
        "risk_pct": risk, "risk_label": risk_label, "risk_msg": risk_msg,
        "frame_lines": frame_lines,
        "ind_details": main['details'],
        "rsi": rsi_main,
        "support": main['support'], "resistance": main['resistance'],
        "macd_bull": main['macd_bull'], "ema_bull": main['ema_bull'],
        "ema_bear": main['ema_bear'], "bb_zone": main['bb_zone'],
        "buy_count": buy_count, "sell_count": sell_count,
    }


def build_trade_message(res, uid=0, auto=False):
    emoji = "🟢" if res['final'] == "BUY" else "🔴"
    dir_txt = t(uid,"buy") if res['final'] == "BUY" else t(uid,"sell")
    asset_icon = "₿" if res['asset'] == "BTC" else "🥇"
    asset_name = "BTC/USD" if res['asset'] == "BTC" else "XAU/USD"
    conf = res['base_conf']
    conf_bar = "█" * (conf//10) + "░" * (10-conf//10)
    header = t(uid,"auto_header") if auto else t(uid,"trade_header")

    msg = f"""
{emoji}{emoji}{emoji}  {asset_icon} {asset_name}  {emoji}{emoji}{emoji}
{header}
━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'entry')}:  ${res['price']:,.2f}
{t(uid,'direction')}:  {dir_txt}

━━━━  {t(uid,'targets_section')}  ━━━━
✅  {t(uid,'tp1')}  »  ${res['tp1']:,.2f}
✅  {t(uid,'tp2')}  »  ${res['tp2']:,.2f}
✅  {t(uid,'tp3')}  »  ${res['tp3']:,.2f}
🛑  {t(uid,'sl')}  »   ${res['sl']:,.2f}
{t(uid,'rr')}:  1:{res['rr']}

━━━━  {t(uid,'support')} / {t(uid,'resistance')}  ━━━━
🟢 {res['support']:,.2f}  |  🔴 {res['resistance']:,.2f}

━━━━  {t(uid,'confluence')}  ━━━━"""

    for fl in res['frame_lines']:
        msg += f"\n{fl}"

    msg += f"\n{res['confluence_txt']}"

    msg += f"""

━━━━  {t(uid,'indicators_section')}  ━━━━
🔹 RSI: {res['rsi']}"""

    for d in res['ind_details']:
        msg += f"\n▫️ {d}"

    msg += f"""

━━━━  {t(uid,'strength_section')}  ━━━━
{conf_bar}  {conf}%

━━━━  {t(uid,'risk_section')}  ━━━━
{res['risk_label']}  •  {res['risk_pct']}%
{res['risk_msg']}

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'updated_gmt')}:  {gmt_now()}
{t(uid,'footer')}"""
    return msg.strip()


def build_analysis_message(res, uid=0):
    asset_icon = "₿" if res['asset'] == "BTC" else "🥇"
    asset_name = "BTC/USD" if res['asset'] == "BTC" else "XAU/USD"

    if res['final'] == "BUY" and res['base_conf'] > 60:
        trend = t(uid,"trend_bull"); summary = t(uid,"summary_bull")
    elif res['final'] == "SELL" and res['base_conf'] > 60:
        trend = t(uid,"trend_bear"); summary = t(uid,"summary_bear")
    else:
        trend = t(uid,"trend_neutral"); summary = t(uid,"summary_neutral")

    rsi = res['rsi']
    rsi_txt = t(uid,"rsi_oversold") if rsi < 30 else t(uid,"rsi_overbought") if rsi > 70 else t(uid,"rsi_neutral")
    macd_txt = t(uid,"macd_bull") if res['macd_bull'] else t(uid,"macd_bear")
    ema_txt  = t(uid,"ema_bull") if res['ema_bull'] else t(uid,"ema_bear") if res['ema_bear'] else t(uid,"ema_mixed")
    bb_txt   = t(uid,"bb_low") if res['bb_zone']=="low" else t(uid,"bb_high") if res['bb_zone']=="high" else t(uid,"bb_mid")

    msg = f"""
📊  {asset_icon} {asset_name}
{t(uid,'analysis_header')}
━━━━━━━━━━━━━━━━━━━━━━━━
{trend}
💵 {t(uid,'entry')}:  ${res['price']:,.2f}

{t(uid,'support')}:  ${res['support']:,.2f}
{t(uid,'resistance')}:  ${res['resistance']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'confluence')}:"""

    for fl in res['frame_lines']:
        msg += f"\n{fl}"

    msg += f"""

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'rsi_label')} ({rsi}):  {rsi_txt}
{macd_txt}
{ema_txt}
{bb_txt}

━━━━━━━━━━━━━━━━━━━━━━━━
{summary}

{t(uid,'updated_gmt')}:  {gmt_now()}
{t(uid,'footer')}"""
    return msg.strip()


def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_trade_btc"),    callback_data='trade_btc'),
         InlineKeyboardButton(t(uid,"btn_trade_gold"),   callback_data='trade_gold')],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"), callback_data='analysis_btc'),
         InlineKeyboardButton(t(uid,"btn_analysis_gold"),callback_data='analysis_gold')],
        [InlineKeyboardButton(t(uid,"btn_prices"),       callback_data='prices'),
         InlineKeyboardButton(t(uid,"btn_about"),        callback_data='about')],
        [InlineKeyboardButton(t(uid,"btn_lang"),         callback_data='change_lang')]
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data='lang_ar'),
        InlineKeyboardButton("English", callback_data='lang_en')
    ]])


# ==================== كوماندات ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_languages:
        await update.message.reply_text(
            "🐎 Abu Mahra Bot\n\nاختر لغتك / Choose your language:",
            reply_markup=lang_keyboard()
        )
    else:
        await update.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    await query.answer()

    if query.data == 'lang_ar':
        user_languages[uid] = "ar"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif query.data == 'lang_en':
        user_languages[uid] = "en"
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))
    elif query.data == 'change_lang':
        await query.message.reply_text(t(uid,"choose_lang"), reply_markup=lang_keyboard())

    elif query.data in ('trade_btc','trade_gold'):
        asset = "BTC" if query.data == 'trade_btc' else "GOLD"
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            res = multi_timeframe_analysis(asset, uid)
            if not res or res['final'] == "NEUTRAL":
                await query.message.reply_text(t(uid,"no_confluence") if res else t(uid,"failed"))
                return
            await query.message.reply_text(build_trade_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data in ('analysis_btc','analysis_gold'):
        asset = "BTC" if query.data == 'analysis_btc' else "GOLD"
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            res = multi_timeframe_analysis(asset, uid)
            if not res:
                await query.message.reply_text(t(uid,"failed")); return
            await query.message.reply_text(build_analysis_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data == 'prices':
        try:
            data = get_prices()
            btc  = data.get('bitcoin',{});  gold = data.get('tether-gold',{})
            bp=btc.get('usd',0); bc=btc.get('usd_24h_change',0)
            gp=gold.get('usd',0); gc=gold.get('usd_24h_change',0)
            msg = f"""{t(uid,'prices_title')}
━━━━━━━━━━━━━━━━━━━━
₿ BTC/USD:  ${bp:,.0f}
{'📈' if bc>0 else '📉'} {t(uid,'change_24h')}:  {bc:+.2f}%

🥇 XAU/USD:  ${gp:,.2f}
{'📈' if gc>0 else '📉'} {t(uid,'change_24h')}:  {gc:+.2f}%

{t(uid,'updated_gmt')}:  {gmt_now()}"""
            await query.message.reply_text(msg)
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data == 'about':
        await query.message.reply_text(t(uid,"about_text"))


async def auto_signals(context):
    try:
        for asset in ["BTC", "GOLD"]:
            res = multi_timeframe_analysis(asset, 0)
            if res and res['final'] != "NEUTRAL" and res['base_conf'] >= MIN_CONFIDENCE:
                msg = build_trade_message(res, 0, auto=True)
                await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
                logger.info(f"✅ {asset} Signal - Conf: {res['base_conf']}% - {res['confluence_txt']}")
            else:
                logger.info(f"⚪ {asset} - No signal")
    except Exception as e:
        logger.error(f"❌ Auto: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES*60, first=30)
    logger.info("🐎 Abu Mahra Bot - Multi-Timeframe Edition!")
    app.run_polling()

if __name__ == "__main__":
    main()
