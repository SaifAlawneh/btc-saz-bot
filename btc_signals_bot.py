import os
import logging
import requests
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import ta

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
INTERVAL_MINUTES = 60
MIN_CONFIDENCE = 70

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
user_languages = {}

# ==================== ردود تفاعلية ====================
GREETINGS_AR = ["مرحبا","مرحبً","هاي","هلا","اهلا","أهلا","السلام","صباح","مساء","كيف","شلونك","وين","شو","ايش","ماذا","hello","hi","hey","good"]
GREETINGS_EN = ["hello","hi","hey","good morning","good evening","how are you","what","where"]

REPLIES_AR = [
    "هلا وغلا! 🐎 أنا بوت أبو مهرة، كيف أقدر أساعدك؟\nاستخدم الأزرار أدناه 👇",
    "أهلاً بك! 🤖 جاهز أحللّك السوق متى تبي\nاختر من القائمة 👇",
    "وعليكم السلام! 🐎 كيف أخدمك اليوم؟",
    "هلا! 😊 اضغط على أي زر للبدء 👇",
    "يسعد مساك/صباحك! 🌟 تبي صفقة ولا تحليل؟",
]

REPLIES_EN = [
    "Hello! 🐎 I'm Abu Mahra Bot, how can I help?\nUse the buttons below 👇",
    "Hi there! 🤖 Ready to analyze the market anytime\nChoose from the menu 👇",
    "Welcome! 😊 Press any button to get started 👇",
    "Hey! 🌟 Want a trade signal or market analysis?",
]

CONFUSED_AR = [
    "ما فهمت كثير 😅 بس أنا هنا للمساعدة!\nاستخدم الأزرار 👇",
    "🤔 ممكن توضح أكثر؟ أو استخدم الأزرار أدناه",
    "أنا بوت تداول 🐎 ما أعرف أجاوب على هيك أسئلة\nبس أقدر أساعدك في BTC والذهب 😄",
]

CONFUSED_EN = [
    "Didn't quite get that 😅 Use the buttons below 👇",
    "🤔 I'm a trading bot! Use the menu for signals & analysis",
    "I'm Abu Mahra Bot 🐎 I specialize in BTC & Gold trading signals!",
]

import random
def get_reply(uid, text):
    text_lower = text.lower()
    lang = user_languages.get(uid, "ar")
    greetings = GREETINGS_AR + GREETINGS_EN
    if any(g in text_lower for g in greetings):
        return random.choice(REPLIES_AR if lang == "ar" else REPLIES_EN)
    return random.choice(CONFUSED_AR if lang == "ar" else CONFUSED_EN)


TEXTS = {
    "ar": {
        "choose_lang": "🐎 بوت أبو مهرة\n\nاختر لغتك:",
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة! 🐎

━━━━━━━━━━━━━━━━━━━━
متخصص في تحليل أسواق:
₿ البيتكوين  BTC/USD
🥇 الذهب  XAU/USD

✨ مميزاتي:
▫️ صفقات قصيرة ومتوسطة وطويلة
▫️ تحديد الرافعة المالية الأنسب
▫️ تحليل 3 فريمات زمنية
▫️ مستويات دعم ومقاومة دقيقة
▫️ درجة الثقة والمخاطرة
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط""",

        "btn_btc": "₿ BTC", "btn_gold": "🥇 ذهب",
        "btn_scalp": "⚡ قصيرة", "btn_swing": "📊 متوسطة", "btn_position": "📅 طويلة",
        "btn_analysis_btc": "📈 تحليل BTC", "btn_analysis_gold": "📈 تحليل ذهب",
        "btn_prices": "💰 الأسعار", "btn_about": "ℹ️ عن البوت", "btn_lang": "🌐 اللغة",
        "btn_back": "🔙 رجوع",

        "choose_asset_trade": "اختر الأصل للصفقة:",
        "choose_trade_type":  "اختر نوع الصفقة:",
        "loading_trade": "⏳ جاري تحليل 3 فريمات...",
        "loading_analysis": "⏳ جاري التحليل...",
        "loading_prices": "⏳ جاري جلب الأسعار...",
        "failed": "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error": "❌ خطأ: ",
        "no_signal": "⚪ لا توجد فرصة واضحة الآن\nانتظر إشارة أقوى 🕐",

        "trade_header_scalp":    "⚡ صفقة قصيرة - أبو مهرة",
        "trade_header_swing":    "📊 صفقة متوسطة - أبو مهرة",
        "trade_header_position": "📅 صفقة طويلة - أبو مهرة",
        "auto_header":           "🔔 إشارة تلقائية - أبو مهرة",
        "analysis_header":       "📊 تحليل السوق - أبو مهرة",

        "trade_type_scalp":    "⚡ قصيرة (Scalp)",
        "trade_type_swing":    "📊 متوسطة (Swing)",
        "trade_type_position": "📅 طويلة (Position)",

        "entry": "💰 سعر الدخول", "direction": "📌 نوع الصفقة",
        "buy": "شراء  BUY ⬆️", "sell": "بيع  SELL ⬇️",
        "targets_section": "🎯 الأهداف",
        "tp1": "الهدف الأول   TP1",
        "tp2": "الهدف الثاني  TP2",
        "tp3": "الهدف الثالث  TP3",
        "sl": "وقف الخسارة  SL",
        "rr": "⚖️ العائد / المخاطرة",
        "leverage": "🔧 الرافعة المالية المقترحة",
        "timeframe": "⏱️ الفريم الزمني",
        "hold_time": "⏳ مدة الإمساك المتوقعة",
        "support": "🟢 دعم", "resistance": "🔴 مقاومة",
        "confluence": "🔗 توافق الفريمات",
        "frame_15m": "⚡ 15د", "frame_1h": "🕐 ساعة", "frame_1d": "📅 يومي",
        "full_confluence": "🔥 توافق كامل على 3 فريمات!",
        "partial_confluence": "✅ توافق على فريمين",
        "no_confluence": "⚪ لا توافق — انتظر فرصة أوضح",
        "indicators_section": "📈 المؤشرات",
        "strength_section": "💡 قوة الإشارة",
        "risk_section": "⚠️ المخاطرة",
        "risk_low": "🟢 منخفضة", "risk_med": "🟡 متوسطة", "risk_high": "🔴 عالية",
        "risk_low_msg": "فرصة جيدة — مخاطرة منخفضة",
        "risk_med_msg": "تداول بحذر — مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط — مخاطرة عالية",
        "footer": "⚠️ للأغراض التعليمية فقط\n📚 تداول بمسؤولية دائماً",
        "updated_gmt": "🕐 آخر تحديث (GMT)",
        "trend_bull": "📈 الاتجاه: صاعد", "trend_bear": "📉 الاتجاه: هابط",
        "trend_neutral": "➡️ الاتجاه: محايد",
        "rsi_label": "🔹 RSI",
        "rsi_oversold": "تشبع بيعي — ضغط شرائي محتمل",
        "rsi_overbought": "تشبع شرائي — ضغط بيعي محتمل",
        "rsi_neutral": "منطقة محايدة",
        "macd_bull": "🔹 MACD: زخم صاعد ↗️",
        "macd_bear": "🔹 MACD: زخم هابط ↘️",
        "ema_bull": "🔹 EMAs: مرتبة صعوداً 📈",
        "ema_bear": "🔹 EMAs: مرتبة هبوطاً 📉",
        "ema_mixed": "🔹 EMAs: إشارات مختلطة ↔️",
        "bb_low": "🔹 بولنجر: عند الدعم السفلي",
        "bb_high": "🔹 بولنجر: عند المقاومة العلوية",
        "bb_mid": "🔹 بولنجر: منتصف النطاق",
        "summary_bull": "✅ الخلاصة: السوق يميل للصعود",
        "summary_bear": "✅ الخلاصة: السوق يميل للهبوط",
        "summary_neutral": "✅ الخلاصة: السوق في منطقة تردد",
        "prices_title": "💰 الأسعار الحالية", "change_24h": "التغيير 24h",
        "about_text": """ℹ️ عن بوت أبو مهرة 🐎

🔬 المؤشرات: RSI, MACD, EMA, Bollinger, Stochastic, ATR, Pivot Points

📊 أنواع الصفقات:
⚡ قصيرة (Scalp) — دقائق لساعات — رافعة 10x-20x
📊 متوسطة (Swing) — أيام لأسبوع — رافعة 5x-10x
📅 طويلة (Position) — أسابيع لأشهر — رافعة 2x-5x

⚙️ النظام: تحليل 3 فريمات معاً، إشارة فقط عند توافق فريمين+

⚠️ للأغراض التعليمية فقط""",
        "ind_rsi_oversold": "RSI تشبع بيعي",
        "ind_rsi_buy": "RSI منطقة شراء",
        "ind_rsi_overbought": "RSI تشبع شرائي",
        "ind_rsi_sell": "RSI منطقة بيع",
        "ind_macd_pos": "MACD إيجابي ↗️", "ind_macd_neg": "MACD سلبي ↘️",
        "ind_ema_up": "EMAs صاعدة 📈", "ind_ema_down": "EMAs هابطة 📉",
        "ind_bb_low": "بولنجر: دعم سفلي 🟢", "ind_bb_high": "بولنجر: مقاومة عليا 🔴",
        "ind_stoch_low": "Stochastic تشبع بيعي", "ind_stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "choose_lang": "🐎 Abu Mahra Bot\n\nChoose your language:",
        "welcome": """🐎 Welcome to Abu Mahra Bot! 🐎

━━━━━━━━━━━━━━━━━━━━
Specializing in:
₿ Bitcoin  BTC/USD
🥇 Gold  XAU/USD

✨ Features:
▫️ Scalp, Swing & Position trades
▫️ Recommended leverage per trade
▫️ 3 timeframe confluence analysis
▫️ Precise support & resistance
▫️ Confidence & risk scoring
━━━━━━━━━━━━━━━━━━━━
⚠️ For educational purposes only""",

        "btn_btc": "₿ BTC", "btn_gold": "🥇 Gold",
        "btn_scalp": "⚡ Scalp", "btn_swing": "📊 Swing", "btn_position": "📅 Position",
        "btn_analysis_btc": "📈 BTC Analysis", "btn_analysis_gold": "📈 Gold Analysis",
        "btn_prices": "💰 Prices", "btn_about": "ℹ️ About", "btn_lang": "🌐 Language",
        "btn_back": "🔙 Back",

        "choose_asset_trade": "Choose asset for trade:",
        "choose_trade_type":  "Choose trade type:",
        "loading_trade": "⏳ Analyzing 3 timeframes...",
        "loading_analysis": "⏳ Analyzing market...",
        "loading_prices": "⏳ Fetching prices...",
        "failed": "❌ Failed to fetch data, try again in a minute",
        "error": "❌ Error: ",
        "no_signal": "⚪ No clear opportunity right now\nWaiting for stronger signal 🕐",

        "trade_header_scalp":    "⚡ Scalp Trade - Abu Mahra",
        "trade_header_swing":    "📊 Swing Trade - Abu Mahra",
        "trade_header_position": "📅 Position Trade - Abu Mahra",
        "auto_header":           "🔔 Auto Signal - Abu Mahra",
        "analysis_header":       "📊 Market Analysis - Abu Mahra",

        "trade_type_scalp":    "⚡ Scalp",
        "trade_type_swing":    "📊 Swing",
        "trade_type_position": "📅 Position",

        "entry": "💰 Entry Price", "direction": "📌 Trade Type",
        "buy": "BUY ⬆️", "sell": "SELL ⬇️",
        "targets_section": "🎯 Targets",
        "tp1": "First Target   TP1",
        "tp2": "Second Target  TP2",
        "tp3": "Third Target   TP3",
        "sl": "Stop Loss      SL",
        "rr": "⚖️ Reward / Risk",
        "leverage": "🔧 Suggested Leverage",
        "timeframe": "⏱️ Timeframe",
        "hold_time": "⏳ Expected Hold Time",
        "support": "🟢 Support", "resistance": "🔴 Resistance",
        "confluence": "🔗 Timeframe Confluence",
        "frame_15m": "⚡ 15m", "frame_1h": "🕐 1h", "frame_1d": "📅 Daily",
        "full_confluence": "🔥 Full confluence on 3 timeframes!",
        "partial_confluence": "✅ Confluence on 2 timeframes",
        "no_confluence": "⚪ No confluence — wait for clearer signal",
        "indicators_section": "📈 Indicators",
        "strength_section": "💡 Signal Strength",
        "risk_section": "⚠️ Risk Level",
        "risk_low": "🟢 Low", "risk_med": "🟡 Medium", "risk_high": "🔴 High",
        "risk_low_msg": "Good opportunity — Low risk",
        "risk_med_msg": "Trade carefully — Medium risk",
        "risk_high_msg": "Small size only — High risk",
        "footer": "⚠️ For educational purposes only\n📚 Always trade responsibly",
        "updated_gmt": "🕐 Last update (GMT)",
        "trend_bull": "📈 Trend: Bullish", "trend_bear": "📉 Trend: Bearish",
        "trend_neutral": "➡️ Trend: Neutral",
        "rsi_label": "🔹 RSI",
        "rsi_oversold": "Oversold — Possible buying pressure",
        "rsi_overbought": "Overbought — Possible selling pressure",
        "rsi_neutral": "Neutral zone",
        "macd_bull": "🔹 MACD: Positive momentum ↗️",
        "macd_bear": "🔹 MACD: Negative momentum ↘️",
        "ema_bull": "🔹 EMAs: Bullish stack 📈",
        "ema_bear": "🔹 EMAs: Bearish stack 📉",
        "ema_mixed": "🔹 EMAs: Mixed signals ↔️",
        "bb_low": "🔹 Bollinger: At lower support",
        "bb_high": "🔹 Bollinger: At upper resistance",
        "bb_mid": "🔹 Bollinger: Middle zone",
        "summary_bull": "✅ Summary: Market leaning bullish",
        "summary_bear": "✅ Summary: Market leaning bearish",
        "summary_neutral": "✅ Summary: Market in consolidation",
        "prices_title": "💰 Current Prices", "change_24h": "24h Change",
        "about_text": """ℹ️ About Abu Mahra Bot 🐎

🔬 Indicators: RSI, MACD, EMA, Bollinger, Stochastic, ATR, Pivot Points

📊 Trade Types:
⚡ Scalp — Minutes to hours — Leverage 10x-20x
📊 Swing — Days to a week — Leverage 5x-10x
📅 Position — Weeks to months — Leverage 2x-5x

⚙️ System: 3 timeframe analysis, signals only on 2+ agreement

⚠️ For educational purposes only""",
        "ind_rsi_oversold": "RSI Oversold", "ind_rsi_buy": "RSI Buy Zone",
        "ind_rsi_overbought": "RSI Overbought", "ind_rsi_sell": "RSI Sell Zone",
        "ind_macd_pos": "MACD Positive ↗️", "ind_macd_neg": "MACD Negative ↘️",
        "ind_ema_up": "EMAs Bullish 📈", "ind_ema_down": "EMAs Bearish 📉",
        "ind_bb_low": "Bollinger: Lower Support 🟢", "ind_bb_high": "Bollinger: Upper Resistance 🔴",
        "ind_stoch_low": "Stochastic Oversold", "ind_stoch_high": "Stochastic Overbought",
    }
}

# إعدادات أنواع الصفقات
TRADE_CONFIGS = {
    "scalp": {
        "atr_sl": 0.8, "atr_tp1": 0.6, "atr_tp2": 1.2, "atr_tp3": 2.0,
        "leverage_ar": "10x — 20x (لا تتجاوز 15x للمبتدئين)",
        "leverage_en": "10x — 20x (Max 15x for beginners)",
        "timeframe_ar": "15 دقيقة — ساعة",
        "timeframe_en": "15 minutes — 1 hour",
        "hold_ar": "دقائق حتى ساعات",
        "hold_en": "Minutes to a few hours",
        "header_key": "trade_header_scalp",
        "type_key": "trade_type_scalp",
    },
    "swing": {
        "atr_sl": 1.5, "atr_tp1": 1.2, "atr_tp2": 2.5, "atr_tp3": 4.5,
        "leverage_ar": "5x — 10x (مناسب للأغلبية)",
        "leverage_en": "5x — 10x (Suitable for most traders)",
        "timeframe_ar": "4 ساعات — يومي",
        "timeframe_en": "4 hours — Daily",
        "hold_ar": "أيام حتى أسبوع",
        "hold_en": "Days to a week",
        "header_key": "trade_header_swing",
        "type_key": "trade_type_swing",
    },
    "position": {
        "atr_sl": 2.5, "atr_tp1": 2.0, "atr_tp2": 4.0, "atr_tp3": 7.0,
        "leverage_ar": "2x — 5x (أكثر أماناً)",
        "leverage_en": "2x — 5x (Safer approach)",
        "timeframe_ar": "أسبوعي — شهري",
        "timeframe_en": "Weekly — Monthly",
        "hold_ar": "أسابيع حتى أشهر",
        "hold_en": "Weeks to months",
        "header_key": "trade_header_position",
        "type_key": "trade_type_position",
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
        logger.error(f"{asset} Error: {e}"); return None

def get_prices():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether-gold&vs_currencies=usd&include_24hr_change=true",
            timeout=10)
        return r.json()
    except: return None


# ==================== التحليل ====================
def calc_indicators(df):
    c=df['Close']; h=df['High']; l=df['Low']
    df['EMA9']  = ta.trend.EMAIndicator(c,window=9).ema_indicator()
    df['EMA21'] = ta.trend.EMAIndicator(c,window=21).ema_indicator()
    df['EMA50'] = ta.trend.EMAIndicator(c,window=50).ema_indicator()
    df['RSI']   = ta.momentum.RSIIndicator(c,window=14).rsi()
    macd=ta.trend.MACD(c); df['MACD']=macd.macd(); df['MACD_S']=macd.macd_signal()
    bb=ta.volatility.BollingerBands(c); df['BB_U']=bb.bollinger_hband(); df['BB_L']=bb.bollinger_lband()
    df['ATR']=ta.volatility.AverageTrueRange(h,l,c,window=14).average_true_range()
    stoch=ta.momentum.StochasticOscillator(h,l,c); df['Stoch']=stoch.stoch()
    df['Pivot']=(h.shift(1)+l.shift(1)+c.shift(1))/3
    df['R1']=2*df['Pivot']-l.shift(1); df['S1']=2*df['Pivot']-h.shift(1)
    df['R2']=df['Pivot']+(h.shift(1)-l.shift(1)); df['S2']=df['Pivot']-(h.shift(1)-l.shift(1))
    return df

def analyze_frame(df, uid=0):
    df=calc_indicators(df); last=df.iloc[-1]; price=last['Close']
    sb=ss=0; details=[]
    rsi=last['RSI']
    if rsi<30:   sb+=25; details.append(f"{t(uid,'ind_rsi_oversold')} ({rsi:.0f}) 🟢")
    elif rsi<45: sb+=12; details.append(f"{t(uid,'ind_rsi_buy')} ({rsi:.0f})")
    elif rsi>70: ss+=25; details.append(f"{t(uid,'ind_rsi_overbought')} ({rsi:.0f}) 🔴")
    elif rsi>55: ss+=12; details.append(f"{t(uid,'ind_rsi_sell')} ({rsi:.0f})")
    if last['MACD']>last['MACD_S']: sb+=20; details.append(t(uid,'ind_macd_pos'))
    else: ss+=20; details.append(t(uid,'ind_macd_neg'))
    if last['EMA9']>last['EMA21']>last['EMA50']: sb+=20; details.append(t(uid,'ind_ema_up'))
    elif last['EMA9']<last['EMA21']<last['EMA50']: ss+=20; details.append(t(uid,'ind_ema_down'))
    if price<=last['BB_L']: sb+=15; details.append(t(uid,'ind_bb_low'))
    elif price>=last['BB_U']: ss+=15; details.append(t(uid,'ind_bb_high'))
    if last['Stoch']<20: sb+=10; details.append(t(uid,'ind_stoch_low'))
    elif last['Stoch']>80: ss+=10; details.append(t(uid,'ind_stoch_high'))
    direction="BUY" if sb>ss else "SELL"
    total=sb+ss; conf=round(max(sb,ss)/total*100) if total>0 else 50
    return {
        "direction":direction,"conf":conf,"sb":sb,"ss":ss,
        "rsi":round(rsi,1),"price":round(price,2),"atr":round(last['ATR'],2),
        "details":details[:4],"support":round(last['S1'],2),"resistance":round(last['R1'],2),
        "macd_bull":last['MACD']>last['MACD_S'],
        "ema_bull":last['EMA9']>last['EMA21']>last['EMA50'],
        "ema_bear":last['EMA9']<last['EMA21']<last['EMA50'],
        "bb_zone":"low" if price<=last['BB_L'] else "high" if price>=last['BB_U'] else "mid",
    }

def multi_timeframe(asset="BTC", trade_type="swing", uid=0):
    frames = {
        "15m": get_data(asset,days=5,interval="hourly"),
        "1h":  get_data(asset,days=14,interval="hourly"),
        "1d":  get_data(asset,days=90,interval="daily"),
    }
    results={}
    for label,df in frames.items():
        if df is not None and len(df)>=30:
            results[label]=analyze_frame(df,uid)
    if len(results)<2: return None

    buy_count=sum(1 for r in results.values() if r['direction']=="BUY")
    sell_count=sum(1 for r in results.values() if r['direction']=="SELL")

    if buy_count==3:   final="BUY";  conf_txt=t(uid,"full_confluence");    base_conf=92
    elif buy_count==2: final="BUY";  conf_txt=t(uid,"partial_confluence"); base_conf=74
    elif sell_count==3: final="SELL"; conf_txt=t(uid,"full_confluence");    base_conf=92
    elif sell_count==2: final="SELL"; conf_txt=t(uid,"partial_confluence"); base_conf=74
    else: return {"final":"NEUTRAL","confluence_txt":t(uid,"no_confluence")}

    main = results.get("1d") or results.get("1h") or list(results.values())[0]
    price=main['price']; atr=main['atr']
    cfg=TRADE_CONFIGS[trade_type]

    if final=="BUY":
        sl=round(price-cfg['atr_sl']*atr,2)
        tp1=round(price+cfg['atr_tp1']*atr,2)
        tp2=round(price+cfg['atr_tp2']*atr,2)
        tp3=round(price+cfg['atr_tp3']*atr,2)
    else:
        sl=round(price+cfg['atr_sl']*atr,2)
        tp1=round(price-cfg['atr_tp1']*atr,2)
        tp2=round(price-cfg['atr_tp2']*atr,2)
        tp3=round(price-cfg['atr_tp3']*atr,2)

    rr=round(abs(tp2-price)/abs(sl-price),2) if abs(sl-price)>0 else 0
    risk=100-base_conf
    if main['rsi']<25 or main['rsi']>75: risk+=10
    risk=min(risk,99)
    if risk<30: rl=t(uid,"risk_low"); rm=t(uid,"risk_low_msg")
    elif risk<55: rl=t(uid,"risk_med"); rm=t(uid,"risk_med_msg")
    else: rl=t(uid,"risk_high"); rm=t(uid,"risk_high_msg")

    lang=user_languages.get(uid,"ar")
    frame_lines=[]
    icons={"15m":t(uid,"frame_15m"),"1h":t(uid,"frame_1h"),"1d":t(uid,"frame_1d")}
    for k,r in results.items():
        icon="🟢" if r['direction']=="BUY" else "🔴"
        frame_lines.append(f"{icon} {icons.get(k,'')}: {r['direction']} ({r['conf']}%)")

    return {
        "final":final,"asset":asset,"trade_type":trade_type,
        "confluence_txt":conf_txt,"base_conf":base_conf,
        "price":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"rr":rr,"atr":atr,
        "risk_pct":risk,"risk_label":rl,"risk_msg":rm,
        "frame_lines":frame_lines,
        "ind_details":main['details'],
        "rsi":main['rsi'],
        "support":main['support'],"resistance":main['resistance'],
        "macd_bull":main['macd_bull'],"ema_bull":main['ema_bull'],
        "ema_bear":main['ema_bear'],"bb_zone":main['bb_zone'],
        "leverage": cfg['leverage_ar'] if lang=="ar" else cfg['leverage_en'],
        "timeframe_txt": cfg['timeframe_ar'] if lang=="ar" else cfg['timeframe_en'],
        "hold_txt": cfg['hold_ar'] if lang=="ar" else cfg['hold_en'],
        "cfg": cfg,
    }


def build_trade_msg(res, uid=0, auto=False):
    emoji="🟢" if res['final']=="BUY" else "🔴"
    dir_txt=t(uid,"buy") if res['final']=="BUY" else t(uid,"sell")
    ai="₿" if res['asset']=="BTC" else "🥇"
    an="BTC/USD" if res['asset']=="BTC" else "XAU/USD"
    conf=res['base_conf']
    bar="█"*(conf//10)+"░"*(10-conf//10)
    header=t(uid,"auto_header") if auto else t(uid,res['cfg']['header_key'])
    type_txt=t(uid,res['cfg']['type_key'])

    msg=f"""
{emoji}{emoji}{emoji}  {ai} {an}  {emoji}{emoji}{emoji}
{header}
━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'direction')}:  {dir_txt}
🏷️ {type_txt}
{t(uid,'entry')}:  ${res['price']:,.2f}

━━━━  {t(uid,'targets_section')}  ━━━━
✅  {t(uid,'tp1')}  »  ${res['tp1']:,.2f}
✅  {t(uid,'tp2')}  »  ${res['tp2']:,.2f}
✅  {t(uid,'tp3')}  »  ${res['tp3']:,.2f}
🛑  {t(uid,'sl')}  »   ${res['sl']:,.2f}
{t(uid,'rr')}:  1:{res['rr']}

━━━━  {t(uid,'leverage')}  ━━━━
{res['leverage']}
⏱️ {res['timeframe_txt']}
⏳ {res['hold_txt']}

━━━━  {t(uid,'support')} / {t(uid,'resistance')}  ━━━━
🟢 ${res['support']:,.2f}  |  🔴 ${res['resistance']:,.2f}

━━━━  {t(uid,'confluence')}  ━━━━"""
    for fl in res['frame_lines']:
        msg+=f"\n{fl}"
    msg+=f"\n{res['confluence_txt']}"
    msg+=f"""

━━━━  {t(uid,'indicators_section')}  ━━━━
🔹 RSI: {res['rsi']}"""
    for d in res['ind_details']:
        msg+=f"\n▫️ {d}"
    msg+=f"""

━━━━  {t(uid,'strength_section')}  ━━━━
{bar}  {conf}%

━━━━  {t(uid,'risk_section')}  ━━━━
{res['risk_label']}  •  {res['risk_pct']}%
{res['risk_msg']}

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'updated_gmt')}:  {gmt_now()}
{t(uid,'footer')}"""
    return msg.strip()


def build_analysis_msg(res, uid=0):
    ai="₿" if res['asset']=="BTC" else "🥇"
    an="BTC/USD" if res['asset']=="BTC" else "XAU/USD"
    if res['final']=="BUY" and res['base_conf']>60:
        trend=t(uid,"trend_bull"); summary=t(uid,"summary_bull")
    elif res['final']=="SELL" and res['base_conf']>60:
        trend=t(uid,"trend_bear"); summary=t(uid,"summary_bear")
    else:
        trend=t(uid,"trend_neutral"); summary=t(uid,"summary_neutral")
    rsi=res['rsi']
    rsi_txt=t(uid,"rsi_oversold") if rsi<30 else t(uid,"rsi_overbought") if rsi>70 else t(uid,"rsi_neutral")
    macd_txt=t(uid,"macd_bull") if res['macd_bull'] else t(uid,"macd_bear")
    ema_txt=t(uid,"ema_bull") if res['ema_bull'] else t(uid,"ema_bear") if res['ema_bear'] else t(uid,"ema_mixed")
    bb_txt=t(uid,"bb_low") if res['bb_zone']=="low" else t(uid,"bb_high") if res['bb_zone']=="high" else t(uid,"bb_mid")

    msg=f"""
📊  {ai} {an}
{t(uid,'analysis_header')}
━━━━━━━━━━━━━━━━━━━━━━━━
{trend}
💵 {t(uid,'entry')}:  ${res['price']:,.2f}

{t(uid,'support')}:  ${res['support']:,.2f}
{t(uid,'resistance')}:  ${res['resistance']:,.2f}

━━━━  {t(uid,'confluence')}  ━━━━"""
    for fl in res['frame_lines']:
        msg+=f"\n{fl}"
    msg+=f"""

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'rsi_label')} ({rsi}):  {rsi_txt}
{macd_txt}
{ema_txt}
{bb_txt}

{summary}

{t(uid,'updated_gmt')}:  {gmt_now()}
{t(uid,'footer')}"""
    return msg.strip()


# ==================== لوحات المفاتيح ====================
def main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_btc"), callback_data='asset_BTC'),
         InlineKeyboardButton(t(uid,"btn_gold"), callback_data='asset_GOLD')],
        [InlineKeyboardButton(t(uid,"btn_analysis_btc"), callback_data='analysis_BTC'),
         InlineKeyboardButton(t(uid,"btn_analysis_gold"), callback_data='analysis_GOLD')],
        [InlineKeyboardButton(t(uid,"btn_prices"), callback_data='prices'),
         InlineKeyboardButton(t(uid,"btn_about"), callback_data='about')],
        [InlineKeyboardButton(t(uid,"btn_lang"), callback_data='change_lang')]
    ])

def trade_type_keyboard(uid, asset):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_scalp"),    callback_data=f'trade_{asset}_scalp'),
         InlineKeyboardButton(t(uid,"btn_swing"),    callback_data=f'trade_{asset}_swing'),
         InlineKeyboardButton(t(uid,"btn_position"), callback_data=f'trade_{asset}_position')],
        [InlineKeyboardButton(t(uid,"btn_back"), callback_data='back_main')]
    ])

def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("العربية", callback_data='lang_ar'),
        InlineKeyboardButton("English", callback_data='lang_en')
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
    """يرد على أي رسالة نصية"""
    uid  = update.effective_user.id
    text = update.message.text or ""
    reply = get_reply(uid, text)
    await update.message.reply_text(reply, reply_markup=main_keyboard(uid) if uid in user_languages else lang_keyboard())


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
    elif data == 'back_main':
        await query.message.reply_text(t(uid,"welcome"), reply_markup=main_keyboard(uid))

    elif data.startswith('asset_'):
        asset = data.split('_')[1]
        await query.message.reply_text(t(uid,"choose_trade_type"), reply_markup=trade_type_keyboard(uid, asset))

    elif data.startswith('trade_'):
        parts = data.split('_')
        asset = parts[1]; trade_type = parts[2]
        await query.message.reply_text(t(uid,"loading_trade"))
        try:
            res = multi_timeframe(asset, trade_type, uid)
            if not res or res['final'] == "NEUTRAL":
                await query.message.reply_text(t(uid,"no_signal")); return
            await query.message.reply_text(build_trade_msg(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data.startswith('analysis_'):
        asset = data.split('_')[1]
        await query.message.reply_text(t(uid,"loading_analysis"))
        try:
            res = multi_timeframe(asset, "swing", uid)
            if not res:
                await query.message.reply_text(t(uid,"failed")); return
            await query.message.reply_text(build_analysis_msg(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid,"error") + str(e))

    elif data == 'prices':
        try:
            d = get_prices()
            btc=d.get('bitcoin',{}); gold=d.get('tether-gold',{})
            bp=btc.get('usd',0); bc=btc.get('usd_24h_change',0)
            gp=gold.get('usd',0); gc=gold.get('usd_24h_change',0)
            msg=f"""{t(uid,'prices_title')}
━━━━━━━━━━━━━━━━━━━━
₿ BTC/USD:  ${bp:,.0f}
{'📈' if bc>0 else '📉'} {t(uid,'change_24h')}:  {bc:+.2f}%

🥇 XAU/USD:  ${gp:,.2f}
{'📈' if gc>0 else '📉'} {t(uid,'change_24h')}:  {gc:+.2f}%

{t(uid,'updated_gmt')}:  {gmt_now()}"""
            await query.message.reply_text(msg)
        except Exception as e:
            await query.message.reply_text(t(uid,"error")+str(e))

    elif data == 'about':
        await query.message.reply_text(t(uid,"about_text"))


async def auto_signals(context):
    try:
        for asset in ["BTC","GOLD"]:
            res = multi_timeframe(asset,"swing",0)
            if res and res['final']!="NEUTRAL" and res['base_conf']>=MIN_CONFIDENCE:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_trade_msg(res,0,auto=True))
                logger.info(f"✅ {asset} Auto Signal - {res['base_conf']}%")
    except Exception as e:
        logger.error(f"❌ Auto: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES*60, first=30)
    logger.info("🐎 Abu Mahra Bot - Full Edition!")
    app.run_polling()

if __name__ == "__main__":
    main()
