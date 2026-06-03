import os
import logging
import requests
from datetime import datetime
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

# حفظ لغة كل مستخدم
user_languages = {}

# ==================== النصوص ====================
TEXTS = {
    "ar": {
        "welcome": """🐎 أهلاً وسهلاً في بوت أبو مهرة! 🐎

━━━━━━━━━━━━━━━━━━━━
أنا بوت متخصص في تحليل أسواق:
₿ البيتكوين  BTC/USD
🥇 الذهب  XAU/USD

✨ مميزاتي:
▫️ أرسل إشارات فقط عند وجود فرصة واضحة
▫️ 3 أهداف لكل صفقة
▫️ درجة المخاطرة بنسبة مئوية دقيقة
▫️ تحليل بـ 5 مؤشرات فنية احترافية
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط""",

        "choose_lang": "اختر لغتك 🌐",
        "analyzing_btc": "⏳ جاري تحليل البيتكوين...",
        "analyzing_gold": "⏳ جاري تحليل الذهب...",
        "failed": "❌ فشل جلب البيانات، حاول بعد دقيقة",
        "error": "❌ خطأ: ",
        "auto_signal": "🔔 إشارة تلقائية جديدة!",
        "manual_signal": "📊 نتيجة التحليل",
        "entry": "💰 سعر الدخول",
        "direction": "📊 الاتجاه",
        "buy": "شراء  BUY ⬆️",
        "sell": "بيع  SELL ⬇️",
        "targets": "🎯 الأهداف",
        "tp1": "TP1  (هدف أول)",
        "tp2": "TP2  (هدف ثاني)",
        "tp3": "TP3  (هدف ثالث)",
        "sl": "SL    (وقف خسارة)",
        "rr": "⚖️ نسبة العائد/المخاطرة",
        "analysis": "📈 التحليل الفني",
        "signal_strength": "🎯 قوة الإشارة",
        "risk": "⚠️ المخاطرة",
        "risk_low": "🟢 منخفضة",
        "risk_med": "🟡 متوسطة",
        "risk_high": "🔴 عالية",
        "risk_low_msg": "فرصة جيدة - مخاطرة منخفضة",
        "risk_med_msg": "تداول بحذر - مخاطرة متوسطة",
        "risk_high_msg": "حجم صغير فقط - مخاطرة عالية",
        "footer": "⚠️ للأغراض التعليمية فقط\n📚 تداول بمسؤولية دائماً",
        "prices_title": "💰 الأسعار الآن",
        "change_24h": "التغيير 24h",
        "last_update": "آخر تحديث",
        "about_text": """ℹ️ عن بوت أبو مهرة 🐎

🔬 المؤشرات المستخدمة:
▫️ RSI — مؤشر القوة النسبية
▫️ MACD — تقارب وتباعد المتوسطات
▫️ EMA 9/21/50 — المتوسطات المتحركة
▫️ Bollinger Bands — نطاقات بولنجر
▫️ Stochastic — مذبذب ستوكاستيك
▫️ ATR — متوسط المدى الحقيقي

⚙️ كيف يعمل؟
يحلل السوق كل ساعة ويرسل إشارة فقط عندما تكون قوة الإشارة فوق 65%

⚠️ للأغراض التعليمية فقط""",
        "btn_btc": "₿ تحليل BTC",
        "btn_gold": "🥇 تحليل ذهب",
        "btn_prices": "💰 الأسعار",
        "btn_about": "ℹ️ عن البوت",
        "btn_lang": "🌐 تغيير اللغة",
        "rsi_oversold": "RSI تشبع بيعي",
        "rsi_buy": "RSI منطقة شراء",
        "rsi_overbought": "RSI تشبع شرائي",
        "rsi_sell": "RSI منطقة بيع",
        "macd_pos": "MACD إيجابي ↗️",
        "macd_neg": "MACD سلبي ↘️",
        "ema_up": "EMAs مرتبة صعوداً 📈",
        "ema_down": "EMAs مرتبة هبوطاً 📉",
        "bb_low": "عند الحد السفلي لبولنجر 🟢",
        "bb_high": "عند الحد العلوي لبولنجر 🔴",
        "stoch_low": "Stochastic تشبع بيعي",
        "stoch_high": "Stochastic تشبع شرائي",
    },
    "en": {
        "welcome": """🐎 Welcome to Abu Mahra Bot! 🐎

━━━━━━━━━━━━━━━━━━━━
I specialize in analyzing:
₿ Bitcoin  BTC/USD
🥇 Gold  XAU/USD

✨ Features:
▫️ Signals only when opportunity is clear
▫️ 3 targets per trade
▫️ Risk percentage for each signal
▫️ 5 professional technical indicators
━━━━━━━━━━━━━━━━━━━━
⚠️ For educational purposes only""",

        "choose_lang": "Choose your language 🌐",
        "analyzing_btc": "⏳ Analyzing Bitcoin...",
        "analyzing_gold": "⏳ Analyzing Gold...",
        "failed": "❌ Failed to fetch data, try again in a minute",
        "error": "❌ Error: ",
        "auto_signal": "🔔 New Auto Signal!",
        "manual_signal": "📊 Analysis Result",
        "entry": "💰 Entry Price",
        "direction": "📊 Direction",
        "buy": "BUY ⬆️",
        "sell": "SELL ⬇️",
        "targets": "🎯 Targets",
        "tp1": "TP1  (First Target)",
        "tp2": "TP2  (Second Target)",
        "tp3": "TP3  (Third Target)",
        "sl": "SL    (Stop Loss)",
        "rr": "⚖️ Risk/Reward Ratio",
        "analysis": "📈 Technical Analysis",
        "signal_strength": "🎯 Signal Strength",
        "risk": "⚠️ Risk Level",
        "risk_low": "🟢 Low",
        "risk_med": "🟡 Medium",
        "risk_high": "🔴 High",
        "risk_low_msg": "Good opportunity - Low risk",
        "risk_med_msg": "Trade carefully - Medium risk",
        "risk_high_msg": "Small size only - High risk",
        "footer": "⚠️ For educational purposes only\n📚 Always trade responsibly",
        "prices_title": "💰 Current Prices",
        "change_24h": "24h Change",
        "last_update": "Last update",
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
        "btn_btc": "₿ Analyze BTC",
        "btn_gold": "🥇 Analyze Gold",
        "btn_prices": "💰 Prices",
        "btn_about": "ℹ️ About",
        "btn_lang": "🌐 Change Language",
        "rsi_oversold": "RSI Oversold",
        "rsi_buy": "RSI Buy Zone",
        "rsi_overbought": "RSI Overbought",
        "rsi_sell": "RSI Sell Zone",
        "macd_pos": "MACD Positive ↗️",
        "macd_neg": "MACD Negative ↘️",
        "ema_up": "EMAs Bullish Stack 📈",
        "ema_down": "EMAs Bearish Stack 📉",
        "bb_low": "At Lower Bollinger Band 🟢",
        "bb_high": "At Upper Bollinger Band 🔴",
        "stoch_low": "Stochastic Oversold",
        "stoch_high": "Stochastic Overbought",
    }
}

def t(user_id, key):
    lang = user_languages.get(user_id, "ar")
    return TEXTS[lang].get(key, key)


def get_lang(user_id):
    return user_languages.get(user_id, "ar")


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


def get_risk_level(conf, direction, rsi, uid):
    risk = 100 - conf
    if rsi < 25 or rsi > 75: risk += 15
    if direction == "BUY" and rsi > 65: risk += 10
    if direction == "SELL" and rsi < 35: risk += 10
    risk = min(risk, 99)
    if risk < 30:   return risk, t(uid, "risk_low"),  t(uid, "risk_low_msg")
    elif risk < 55: return risk, t(uid, "risk_med"),  t(uid, "risk_med_msg")
    else:           return risk, t(uid, "risk_high"), t(uid, "risk_high_msg")


def analyze(df, asset="BTC", uid=0):
    df = calculate_indicators(df)
    last = df.iloc[-1]
    price = last['Close']
    score_buy = score_sell = 0
    details = []

    rsi = last['RSI']
    if rsi < 30:   score_buy  += 25; details.append(f"{t(uid,'rsi_oversold')} ({rsi:.0f}) 🟢")
    elif rsi < 45: score_buy  += 12; details.append(f"{t(uid,'rsi_buy')} ({rsi:.0f})")
    elif rsi > 70: score_sell += 25; details.append(f"{t(uid,'rsi_overbought')} ({rsi:.0f}) 🔴")
    elif rsi > 55: score_sell += 12; details.append(f"{t(uid,'rsi_sell')} ({rsi:.0f})")

    if last['MACD'] > last['MACD_Signal']: score_buy  += 20; details.append(t(uid, 'macd_pos'))
    else:                                   score_sell += 20; details.append(t(uid, 'macd_neg'))

    if last['EMA9'] > last['EMA21'] > last['EMA50']:   score_buy  += 20; details.append(t(uid, 'ema_up'))
    elif last['EMA9'] < last['EMA21'] < last['EMA50']: score_sell += 20; details.append(t(uid, 'ema_down'))

    if price <= last['BB_Lower']:   score_buy  += 15; details.append(t(uid, 'bb_low'))
    elif price >= last['BB_Upper']: score_sell += 15; details.append(t(uid, 'bb_high'))

    if last['Stoch_K'] < 20:   score_buy  += 10; details.append(t(uid, 'stoch_low'))
    elif last['Stoch_K'] > 80: score_sell += 10; details.append(t(uid, 'stoch_high'))

    direction = "BUY" if score_buy > score_sell else "SELL"
    total = score_buy + score_sell
    conf = round(max(score_buy, score_sell) / total * 100) if total > 0 else 50

    atr = last['ATR']
    if direction == "BUY":
        sl=round(price-1.5*atr,2); tp1=round(price+1.0*atr,2); tp2=round(price+2.2*atr,2); tp3=round(price+4.0*atr,2)
    else:
        sl=round(price+1.5*atr,2); tp1=round(price-1.0*atr,2); tp2=round(price-2.2*atr,2); tp3=round(price-4.0*atr,2)

    rr = round(abs(tp2-price)/abs(sl-price),2) if abs(sl-price)>0 else 0
    risk_pct, risk_label, risk_msg = get_risk_level(conf, direction, rsi, uid)

    return {
        "asset": asset, "direction": direction, "conf": conf,
        "price": round(price,2), "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl": sl, "rr": rr, "atr": round(atr,2), "details": details[:4],
        "score_buy": score_buy, "score_sell": score_sell,
        "risk_pct": risk_pct, "risk_label": risk_label, "risk_msg": risk_msg,
        "rsi": round(rsi,1)
    }


def build_message(res, uid=0, auto=False):
    is_btc  = res['asset'] == "BTC"
    emoji   = "🟢" if res['direction'] == "BUY" else "🔴"
    dir_txt = t(uid, "buy") if res['direction'] == "BUY" else t(uid, "sell")
    asset_emoji = "₿" if is_btc else "🥇"
    asset_name  = "BTC/USD" if is_btc else "XAU/USD"
    conf    = res['conf']
    conf_bar = "█" * (conf // 10) + "░" * (10 - conf // 10)
    now     = datetime.now().strftime("%d/%m/%Y  %H:%M")
    header  = t(uid, "auto_signal") if auto else t(uid, "manual_signal")

    msg = f"""
{emoji}{emoji}{emoji}  {asset_emoji} {asset_name}  •  Abu Mahra Bot 🐎  {emoji}{emoji}{emoji}
━━━━━━━━━━━━━━━━━━━━━━━━
{header}
⏰ {now}

{t(uid,'entry')}:  ${res['price']:,.2f}
{t(uid,'direction')}:  {dir_txt}

━━━━━━  {t(uid,'targets')}  ━━━━━━
✅  {t(uid,'tp1')}  »  ${res['tp1']:,.2f}
✅  {t(uid,'tp2')}  »  ${res['tp2']:,.2f}
✅  {t(uid,'tp3')}  »  ${res['tp3']:,.2f}
🛑  {t(uid,'sl')}  »  ${res['sl']:,.2f}

{t(uid,'rr')}:  1:{res['rr']}

━━━━━━  {t(uid,'analysis')}  ━━━━━━
🔹 RSI:  {res['rsi']}"""

    for d in res['details']:
        msg += f"\n▫️ {d}"

    msg += f"""

━━━━━━  {t(uid,'signal_strength')}  ━━━━━━
{conf_bar}  {conf}%

━━━━━━  {t(uid,'risk')}  ━━━━━━
{res['risk_label']}  •  {res['risk_pct']}%
{res['risk_msg']}

━━━━━━━━━━━━━━━━━━━━━━━━
{t(uid,'footer')}
"""
    return msg.strip()


def main_keyboard(uid):
    lang = get_lang(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(uid,"btn_btc"), callback_data='analyze_btc'),
         InlineKeyboardButton(t(uid,"btn_gold"), callback_data='analyze_gold')],
        [InlineKeyboardButton(t(uid,"btn_prices"), callback_data='prices'),
         InlineKeyboardButton(t(uid,"btn_about"), callback_data='about')],
        [InlineKeyboardButton(t(uid,"btn_lang"), callback_data='change_lang')]
    ])


# ==================== كوماندات ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_languages:
        # اختيار اللغة أول مرة
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇸🇦 العربية", callback_data='lang_ar'),
             InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')]
        ])
        await update.message.reply_text("🐎 Abu Mahra Bot\n\nاختر لغتك / Choose your language:", reply_markup=keyboard)
    else:
        await update.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))


async def cmd_btc(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = await update.message.reply_text(t(uid, "analyzing_btc"))
    try:
        df = get_btc_data()
        if df is None or len(df) < 55:
            await msg.edit_text(t(uid, "failed"))
            return
        res = analyze(df, "BTC", uid)
        await msg.edit_text(build_message(res, uid))
    except Exception as e:
        await msg.edit_text(t(uid, "error") + str(e))


async def cmd_gold(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = await update.message.reply_text(t(uid, "analyzing_gold"))
    try:
        df = get_gold_data()
        if df is None or len(df) < 55:
            await msg.edit_text(t(uid, "failed"))
            return
        res = analyze(df, "GOLD", uid)
        await msg.edit_text(build_message(res, uid))
    except Exception as e:
        await msg.edit_text(t(uid, "error") + str(e))


async def cmd_prices(update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        data = get_prices()
        btc  = data.get('bitcoin', {})
        gold = data.get('tether-gold', {})
        btc_p=btc.get('usd',0); btc_c=btc.get('usd_24h_change',0)
        gold_p=gold.get('usd',0); gold_c=gold.get('usd_24h_change',0)
        msg = f"""{t(uid,'prices_title')}

₿ BTC/USD:  ${btc_p:,.0f}
{'📈' if btc_c>0 else '📉'} {t(uid,'change_24h')}:  {btc_c:+.2f}%

🥇 XAU/USD:  ${gold_p:,.2f}
{'📈' if gold_c>0 else '📉'} {t(uid,'change_24h')}:  {gold_c:+.2f}%

🕐 {t(uid,'last_update')}:  {datetime.now().strftime('%H:%M')}"""
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(t(uid, "error") + str(e))


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    if query.data == 'lang_ar':
        user_languages[uid] = "ar"
        await query.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))

    elif query.data == 'lang_en':
        user_languages[uid] = "en"
        await query.message.reply_text(t(uid, "welcome"), reply_markup=main_keyboard(uid))

    elif query.data == 'change_lang':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇸🇦 العربية", callback_data='lang_ar'),
             InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')]
        ])
        await query.message.reply_text(t(uid, "choose_lang"), reply_markup=keyboard)

    elif query.data == 'analyze_btc':
        await query.message.reply_text(t(uid, "analyzing_btc"))
        try:
            df = get_btc_data()
            if df is None or len(df) < 55:
                await query.message.reply_text(t(uid, "failed"))
                return
            res = analyze(df, "BTC", uid)
            await query.message.reply_text(build_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid, "error") + str(e))

    elif query.data == 'analyze_gold':
        await query.message.reply_text(t(uid, "analyzing_gold"))
        try:
            df = get_gold_data()
            if df is None or len(df) < 55:
                await query.message.reply_text(t(uid, "failed"))
                return
            res = analyze(df, "GOLD", uid)
            await query.message.reply_text(build_message(res, uid))
        except Exception as e:
            await query.message.reply_text(t(uid, "error") + str(e))

    elif query.data == 'prices':
        try:
            data = get_prices()
            btc  = data.get('bitcoin', {})
            gold = data.get('tether-gold', {})
            btc_p=btc.get('usd',0); btc_c=btc.get('usd_24h_change',0)
            gold_p=gold.get('usd',0); gold_c=gold.get('usd_24h_change',0)
            msg = f"""{t(uid,'prices_title')}

₿ BTC/USD:  ${btc_p:,.0f}
{'📈' if btc_c>0 else '📉'} {t(uid,'change_24h')}:  {btc_c:+.2f}%

🥇 XAU/USD:  ${gold_p:,.2f}
{'📈' if gold_c>0 else '📉'} {t(uid,'change_24h')}:  {gold_c:+.2f}%

🕐 {t(uid,'last_update')}:  {datetime.now().strftime('%H:%M')}"""
            await query.message.reply_text(msg)
        except Exception as e:
            await query.message.reply_text(t(uid, "error") + str(e))

    elif query.data == 'about':
        await query.message.reply_text(t(uid, "about_text"))


async def auto_signals(context):
    try:
        df_btc = get_btc_data()
        if df_btc is not None and len(df_btc) >= 55:
            res = analyze(df_btc, "BTC", 0)
            if res['conf'] >= MIN_CONFIDENCE:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_message(res, 0, auto=True))
                logger.info(f"✅ BTC Signal - Strength: {res['conf']}%")

        df_gold = get_gold_data()
        if df_gold is not None and len(df_gold) >= 55:
            res = analyze(df_gold, "GOLD", 0)
            if res['conf'] >= MIN_CONFIDENCE:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_message(res, 0, auto=True))
                logger.info(f"✅ Gold Signal - Strength: {res['conf']}%")

    except Exception as e:
        logger.error(f"❌ Auto Signal Error: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("btc",    cmd_btc))
    app.add_handler(CommandHandler("gold",   cmd_gold))
    app.add_handler(CommandHandler("prices", cmd_prices))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES * 60, first=30)
    logger.info("🐎 Abu Mahra Bot يعمل - BTC + Gold!")
    app.run_polling()


if __name__ == "__main__":
    main()
