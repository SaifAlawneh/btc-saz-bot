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
MIN_CONFIDENCE = 65

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_languages = {}

TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "lang_btn_ar": "العربية",
        "lang_btn_en": "English",

        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة! 🐎

━━━━━━━━━━━━━━━━━━━━
متخصص في تحليل أسواق:
₿ البيتكوين  BTC/USD
🥇 الذهب  XAU/USD

✨ مميزاتي:
▫️ صفقات محددة بـ 3 أهداف
▫️ تحليل مبسط لاتجاه السوق
▫️ درجة المخاطرة بنسبة مئوية
▫️ إشارات تلقائية عند وجود فرصة
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط""",

        "btn_trade_btc":   "₿ صفقة BTC",
        "btn_trade_gold":  "🥇 صفقة ذهب",
        "btn_analysis_btc":  "📊 تحليل BTC",
        "btn_analysis_gold": "📊 تحليل ذهب",
        "btn_prices":      "💰 الأسعار",
        "btn_about":       "ℹ️ عن البوت",
        "btn_lang":        "🌐 تغيير اللغة",

        "loading_trade":    "⏳ جاري إعداد الصفقة...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices":   "⏳ جاري جلب الأسعار...",
        "failed":  "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error":   "❌ خطأ: ",

        "trade_header":    "🐎 صفقة أبو مهرة",
        "auto_header":     "🔔 إشارة تلقائية - أبو مهرة",
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

        "indicators_section": "📈 المؤشرات الفنية",
        "strength_section":   "💡 قوة الإشارة",
        "risk_section":       "⚠️ درجة المخاطرة",

        "risk_low":      "🟢 منخفضة",
        "risk_med":      "🟡 متوسطة",
        "risk_high":     "🔴 عالية",
        "risk_low_msg":  "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg":  "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",

        "footer": "⚠️ للأغراض التعليمية فقط\n📚 تداول بمسؤولية دائماً",
        "updated_gmt": "🕐 آخر تحديث (GMT)",

        # تحليل مبسط
        "trend_bull":   "📈 الاتجاه العام: صاعد",
        "trend_bear":   "📉 الاتجاه العام: هابط",
        "trend_neutral":"➡️ الاتجاه العام: محايد",
        "rsi_label":    "🔹 مؤشر RSI",
        "rsi_oversold": "منطقة تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought":"منطقة تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral":  "منطقة محايدة",
        "macd_bull":    "🔹 MACD: زخم صاعد إيجابي ↗️",
        "macd_bear":    "🔹 MACD: زخم هابط سلبي ↘️",
        "ema_bull":     "🔹 المتوسطات: مرتبة صعوداً 📈",
        "ema_bear":     "🔹 المتوسطات: مرتبة هبوطاً 📉",
        "ema_mixed":    "🔹 المتوسطات: إشارات مختلطة ↔️",
        "bb_low":       "🔹 بولنجر: السعر عند الدعم السفلي",
        "bb_high":      "🔹 بولنجر: السعر عند المقاومة العلوية",
        "bb_mid":       "🔹 بولنجر: السعر في المنتصف",
        "summary_bull": "✅ الخلاصة: السوق يميل للصعود حالياً",
        "summary_bear": "✅ الخلاصة: السوق يميل للهبوط حالياً",
        "summary_neutral": "✅ الخلاصة: السوق في منطقة تردد",

        "prices_title": "💰 الأسعار الحالية",
        "change_24h":   "التغيير 24h",

        "about_text": """ℹ️ عن بوت أبو مهرة 🐎

🔬 المؤشرات المستخدمة:
▫️ RSI — مؤشر القوة النسبية
▫️ MACD — تقارب وتباعد المتوسطات
▫️ EMA 9/21/50 — المتوسطات المتحركة
▫️ Bollinger Bands — نطاقات بولنجر
▫️ Stochastic — مذبذب ستوكاستيك
▫️ ATR — متوسط المدى الحقيقي

⚙️ كيف يعمل؟
يحلل السوق كل ساعة ويرسل صفقة فقط عندما تكون قوة الإشارة فوق 65%

⚠️ للأغراض التعليمية فقط""",

        "ind_rsi_oversold":   "RSI تشبع بيعي",
        "ind_rsi_buy":        "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي",
        "ind_rsi_sell":       "RSI منطقة بيع",
        "ind_macd_pos":       "MACD إيجابي ↗️",
        "ind_macd_neg":       "MACD سلبي ↘️",
        "ind_ema_up":         "EMAs مرتبة صعوداً 📈",
        "ind_ema_down":       "EMAs مرتبة هبوطاً 📉",
        "ind_bb_low":         "بولنجر: عند الدعم السفلي 🟢",
        "ind_bb_high":        "بولنجر: عند المقاومة العلوية 🔴",
        "ind_stoch_low":      "Stochastic تشبع بيعي",
        "ind_stoch_high":     "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "lang_btn_ar": "العربية",
        "lang_btn_en": "English",

        "welcome": """🐎 Welcome to Abu Mahra Bot! 🐎

━━━━━━━━━━━━━━━━━━━━
Specializing in market analysis:
₿ Bitcoin  BTC/USD
🥇 Gold  XAU/USD

✨ Features:
▫️ Trade signals with 3 targets
▫️ Simplified market trend analysis
▫️ Risk percentage per signal
▫️ Auto signals on clear opportunities
━━━━━━━━━━━━━━━━━━━━
⚠️ For educational purposes only""",

        "btn_trade_btc":     "₿ BTC Trade",
        "btn_trade_gold":    "🥇 Gold Trade",
        "btn_analysis_btc":  "📊 BTC Analysis",
        "btn_analysis_gold": "📊 Gold Analysis",
        "btn_prices":        "💰 Prices",
        "btn_about":         "ℹ️ About",
        "btn_lang":          "🌐 Change Language",

        "loading_trade":    "⏳ Preparing trade signal...",
        "loading_analysis": "⏳ Analyzing market...",
        "loading_prices":   "⏳ Fetching prices...",
        "failed":  "❌ Failed to fetch data, try again in a minute",
        "error":   "❌ Error: ",

        "trade_header":    "🐎 Abu Mahra Trade Signal",
        "auto_header":     "🔔 Auto Signal - Abu Mahra",
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

        "indicators_section": "📈 Technical Indicators",
        "strength_section":   "💡 Signal Strength",
        "risk_section":       "⚠️ Risk Level",

        "risk_low":      "🟢 Low",
        "risk_med":      "🟡 Medium",
        "risk_high":     "🔴 High",
        "risk_low_msg":  "Good opportunity — Low risk",
        "risk_med_msg":  "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",

        "footer": "⚠️ For educational purposes only\n📚 Always trade responsibly",
        "updated_gmt": "🕐 Last update (GMT)",

        "trend_bull":    "📈 Overall Trend: Bullish",
        "trend_bear":    "📉 Overall Trend: Bearish",
        "trend_neutral": "➡️ Overall Trend: Neutral",
        "rsi_label":     "🔹 RSI Indicator",
        "rsi_oversold":  "Oversold zone — Possible buying pressure",
        "rsi_overbought":"Overbought zone — Possible selling pressure",
        "rsi_neutral":   "Neutral zone",
        "macd_bull":     "🔹 MACD: Positive bullish momentum ↗️",
        "macd_bear":     "🔹 MACD: Negative bearish momentum ↘️",
        "ema_bull":      "🔹 EMAs: Bullish stack 📈",
        "ema_bear":      "🔹 EMAs: Bearish stack 📉",
        "ema_mixed":     "🔹 EMAs: Mixed signals ↔️",
        "bb_low":        "🔹 Bollinger: Price at lower support",
        "bb_high":       "🔹 Bollinger: Price at upper resistance",
        "bb_mid":        "🔹 Bollinger: Price in middle zone",
        "summary_bull":  "✅ Summary: Market leaning bullish",
        "summary_bear":  "✅ Summary: Market leaning bearish",
        "summary_neutral":"✅ Summary: Market in consolidation",

        "prices_title": "💰 Current Prices",
        "change_24h":   "24h Change",

        "about_text": """ℹ️ About Abu Mahra Bot 🐎

🔬 Indicators Used:
▫️ RSI — Relative Strength Index
▫️ MACD — Moving Average Convergence Divergence
▫️ EMA 9/21/50 — Exponential Moving Averages
▫️ Bollinger Bands
▫️ Stochastic Oscillator
▫️ ATR — Average True Range

⚙️ How it works?
Analyzes the market every hour and sends a signal only when strength is above 65%

⚠️ For educational purposes only""",

        "ind_rsi_oversold":   "RSI Oversold",
        "ind_rsi_buy":        "RSI Buy Zone",
        "ind_rsi_overbought": "RSI Overbought",
        "ind_rsi_sell":       "RSI Sell Zone",
        "ind_macd_pos":       "MACD Positive ↗️",
        "ind_macd_neg":       "MACD Negative ↘️",
        "ind_ema_up":         "EMAs Bullish Stack 📈",
        "ind_ema_down":       "EMAs Bearish Stack 📉",
        "ind_bb_low":         "Bollinger: At Lower Support 🟢",
        "ind_bb_high":        "Bollinger: At Upper Resistance 🔴",
        "ind_stoch_low":      "Stochastic Oversold",
        "ind_stoch_high":     "Stochastic Overbought",
    }
}

def t(uid, key):
    lang = user_languages.get(uid, "ar")
    return TEXTS[lang].get(key, key)

def get_lang(uid):
    return user_languages.get(uid, "ar")

def gmt_now():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M")

# ==================== البيانات ====================
def get_btc_data():
    try:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params = {"vs_currency": "usd", "days": 30, "interval": "hourly"}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        return build_df(data['prices'], data['total_volumes'])
    except Exception as e:
        logger.error(f"BTC Error: {e}")
        return None

def get_gold_data():
    try:
        url = "https://api.coingecko.com/api/v3/coins/tether-gold/market_chart"
        params = {"vs_currency": "usd", "days": 30, "interval": "hourly"}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        return build_df(data['prices'], data['total_volumes'])
    except Exception as e:
        logger.error(f"Gold Error: {e}")
        return None

def build_df(prices, volumes):
    df = pd.DataFrame(prices, columns=['timestamp', 'Close'])
    df['Volume'] = [v[1] for v in volumes]
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp')
    df['High'] = df['Close'].rolling(3).max()
    df['Low']  = df['Close'].rolling(3).min()
    df['Open'] = df['Close'].shift(1)
    return df.dropna()

def get_prices():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether-gold&vs_currencies=usd&include_24hr_change=true",
            timeout=10
        )
        return r.json()
    except:
        return None

# ==================== التحليل ====================
def calculate_indicators(df):
    close = df['Close']
    high  = df['High']
    low   = df['Low']
    df['EMA9']   = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df['EMA21']  = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    df['EMA50']  = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    df['RSI']    = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd = ta.trend.MACD(close)
    df['MACD']        = macd.macd()
    df['MACD_Signal'] = macd.macd_signal()
    bb = ta.volatility.BollingerBands(close)
    df['BB_Upper'] = bb.bollinger_hband()
    df['BB_Lower'] = bb.bollinger_lband()
    df['ATR']      = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    stoch = ta.momentum.StochasticOscillator(high, low, close)
    df['Stoch_K'] = stoch.stoch()
    return df

def get_risk(conf, direction, rsi, uid):
    risk = 100 - conf
    if rsi < 25 or rsi > 75: risk += 15
    if direction == "BUY"  and rsi > 65: risk += 10
    if direction == "SELL" and rsi < 35: risk += 10
    risk = min(risk, 99)
    if risk < 30:   return risk, t(uid,"risk_low"),  t(uid,"risk_low_msg")
    elif risk < 55: return risk, t(uid,"risk_med"),  t(uid,"risk_med_msg")
    else:           return risk, t(uid,"risk_high"), t(uid,"risk_high_msg")

def analyze(df, asset="BTC", uid=0):
    df = calculate_indicators(df)
    last = df.iloc[-1]
    price = last['Close']
    sb = ss = 0
    ind_details = []

    rsi = last['RSI']
    if rsi < 30:   sb += 25; ind_details.append(f"{t(uid,'ind_rsi_oversold')} ({rsi:.0f}) 🟢")
    elif rsi < 45: sb += 12; ind_details.append(f"{t(uid,'ind_rsi_buy')} ({rsi:.0f})")
    elif rsi > 70: ss += 25; ind_details.append(f"{t(uid,'ind_rsi_overbought')} ({rsi:.0f}) 🔴")
    elif rsi > 55: ss += 12; ind_details.append(f"{t(uid,'ind_rsi_sell')} ({rsi:.0f})")

    if last['MACD'] > last['MACD_Signal']: sb += 20; ind_details.append(t(uid,'ind_macd_pos'))
    else:                                   ss += 20; ind_details.append(t(uid,'ind_macd_neg'))

    if last['EMA9'] > last['EMA21'] > last['EMA50']:   sb += 20; ind_details.append(t(uid,'ind_ema_up'))
    elif last['EMA9'] < last['EMA21'] < last['EMA50']: ss += 20; ind_details.append(t(uid,'ind_ema_down'))

    if price <= last['BB_Lower']:   sb += 15; ind_details.append(t(uid,'ind_bb_low'))
    elif price >= last['BB_Upper']: ss += 15; ind_details.append(t(uid,'ind_bb_high'))

    if last['Stoch_K'] < 20:   sb += 10; ind_details.append(t(uid,'ind_stoch_low'))
    elif last['Stoch_K'] > 80: ss += 10; ind_details.append(t(uid,'ind_stoch_high'))

    direction = "BUY" if sb > ss else "SELL"
    total = sb + ss
    conf = round(max(sb, ss) / total * 100) if total > 0 else 50
    atr = last['ATR']

    if direction == "BUY":
        sl=round(price-1.5*atr,2); tp1=round(price+1.0*atr,2); tp2=round(price+2.2*atr,2); tp3=round(price+4.0*atr,2)
    else:
        sl=round(price+1.5*atr,2); tp1=round(price-1.0*atr,2); tp2=round(price-2.2*atr,2); tp3=round(price-4.0*atr,2)

    rr = round(abs(tp2-price)/abs(sl-price),2) if abs(sl-price)>0 else 0
    risk_pct, risk_label, risk_msg = get_risk(conf, direction, rsi, uid)

    return {
        "asset": asset, "direction": direction, "conf": conf,
        "price": round(price,2), "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": round(atr,2),
        "ind_details": ind_details[:4],
        "sb": sb, "ss": ss,
        "risk_pct": risk_pct, "risk_label": risk_label, "risk_msg": risk_msg,
        "rsi": round(rsi,1),
        "macd_bull": last['MACD'] > last['MACD_Signal'],
        "ema_bull": last['EMA9'] > last['EMA21'] > last['EMA50'],
        "ema_bear": last['EMA9'] < last['EMA21'] < last['EMA50'],
        "bb_zone": "low" if price <= last['BB_Lower'] else "high" if price >= last['BB_Upper'] else "mid",
    }


def build_trade_message(res, uid=0, auto=False):
    is_btc = res['asset'] == "BTC"
    emoji  = "🟢" if res['direction'] == "BUY" else "🔴"
    dir_txt = t(uid,"buy") if res['direction'] == "BUY" else t(uid,"sell")
    asset_icon = "₿" if is_btc else "🥇"
    asset_name = "BTC/USD" if is_btc else "XAU/USD"
    conf = res['conf']
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
🛑  {t(uid,'sl')}  »  ${res['sl']:,.2f}

{t(uid,'rr')}:  1:{res['rr']}

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
    is_btc = res['asset'] == "BTC"
    asset_icon = "₿" if is_btc else "🥇"
    asset_name = "BTC/USD" if is_btc else "XAU/USD"
    conf = res['conf']

    # تحديد الاتجاه العام
    if res['direction'] == "BUY" and conf > 60:
        trend = t(uid,"trend_bull")
        summary = t(uid,"summary_bull")
    elif res['direction'] == "SELL" and conf > 60:
        trend = t(uid,"trend_bear")
        summary = t(uid,"summary_bear")
    else:
        trend = t(uid,"trend_neutral")
        summary = t(uid,"summary_neutral")

    rsi = res['rsi']
    if rsi < 30:   rsi_txt = t(uid,"rsi_oversold")
    elif rsi > 70: rsi_txt = t(uid,"rsi_overbought")
    else:          rsi_txt = t(uid,"rsi_neutral")

    macd_txt = t(uid,"macd_bull") if res['macd_bull'] else t(uid,"macd_bear")

    if res['ema_bull']:    ema_txt = t(uid,"ema_bull")
    elif res['ema_bear']:  ema_txt = t(uid,"ema_bear")
    else:                  ema_txt = t(uid,"ema_mixed")

    if res['bb_zone'] == "low":    bb_txt = t(uid,"bb_low")
    elif res['bb_zone'] == "high": bb_txt = t(uid,"bb_high")
    else:                          bb_txt = t(uid,"bb_mid")

    msg = f"""
📊  {asset_icon} {asset_name}
{t(uid,'analysis_header')}
━━━━━━━━━━━━━━━━━━━━━━━━
{trend}
💵 {t(uid,'entry')}:  ${res['price']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'rsi_label')} ({rsi}):
▫️ {rsi_txt}

{macd_txt}
{ema_txt}
{bb_txt}

━━━━━━━━━━━━━━━━━━━━━━━━
{summary}

━━━━━━━━━━━━━━━━━━━━━━━━
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

    elif query.data in ('trade_btc', 'trade_gold'):
        asset = "BTC" if query.data == 'trade_btc' else "GOLD"
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            df = get_btc_data() if asset == "BTC" else get_gold_data()
            if df is None or len(df) < 55:
                await query.message.reply_text(t(uid,"failed")); return
            res = analyze(df, asset, uid)
            await query.message.reply_text(build_trade_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data in ('analysis_btc', 'analysis_gold'):
        asset = "BTC" if query.data == 'analysis_btc' else "GOLD"
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            df = get_btc_data() if asset == "BTC" else get_gold_data()
            if df is None or len(df) < 55:
                await query.message.reply_text(t(uid,"failed")); return
            res = analyze(df, asset, uid)
            await query.message.reply_text(build_analysis_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data == 'prices':
        await query.message.reply_text(t(uid,"loading_prices"))
        try:
            data = get_prices()
            btc  = data.get('bitcoin', {})
            gold = data.get('tether-gold', {})
            btc_p=btc.get('usd',0);   btc_c=btc.get('usd_24h_change',0)
            gold_p=gold.get('usd',0); gold_c=gold.get('usd_24h_change',0)
            msg = f"""{t(uid,'prices_title')}
━━━━━━━━━━━━━━━━━━━━
₿ BTC/USD:  ${btc_p:,.0f}
{'📈' if btc_c>0 else '📉'} {t(uid,'change_24h')}:  {btc_c:+.2f}%

🥇 XAU/USD:  ${gold_p:,.2f}
{'📈' if gold_c>0 else '📉'} {t(uid,'change_24h')}:  {gold_c:+.2f}%

{t(uid,'updated_gmt')}:  {gmt_now()}"""
            await query.message.reply_text(msg)
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif query.data == 'about':
        await query.message.reply_text(t(uid,"about_text"))


async def auto_signals(context):
    try:
        for asset, get_data in [("BTC", get_btc_data), ("GOLD", get_gold_data)]:
            df = get_data()
            if df is not None and len(df) >= 55:
                res = analyze(df, asset, 0)
                if res['conf'] >= MIN_CONFIDENCE:
                    msg = build_trade_message(res, 0, auto=True)
                    await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
                    logger.info(f"✅ {asset} Signal - {res['conf']}%")
    except Exception as e:
        logger.error(f"❌ Auto: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES*60, first=30)
    logger.info("🐎 Abu Mahra Bot يعمل!")
    app.run_polling()

if __name__ == "__main__":
    main()
