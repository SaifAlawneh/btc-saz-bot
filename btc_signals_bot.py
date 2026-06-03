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
MIN_CONFIDENCE = 65  # لا يرسل إلا لما تكون الإشارة فوق 65%

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def get_btc_data(days=30, interval="hourly"):
    try:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params = {"vs_currency": "usd", "days": days, "interval": interval}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        prices  = data['prices']
        volumes = data['total_volumes']

        df = pd.DataFrame(prices, columns=['timestamp', 'Close'])
        df['Volume'] = [v[1] for v in volumes]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')

        df['High'] = df['Close'].rolling(3).max()
        df['Low']  = df['Close'].rolling(3).min()
        df['Open'] = df['Close'].shift(1)
        df = df.dropna()
        return df
    except Exception as e:
        logger.error(f"خطأ CoinGecko: {e}")
        return None


def get_btc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true",
            timeout=10
        )
        return r.json()['bitcoin']
    except:
        return None


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
    df['MACD_Hist']   = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close)
    df['BB_Upper'] = bb.bollinger_hband()
    df['BB_Lower'] = bb.bollinger_lband()
    df['ATR']      = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

    stoch = ta.momentum.StochasticOscillator(high, low, close)
    df['Stoch_K'] = stoch.stoch()

    return df


def get_risk_level(conf, direction, rsi):
    """حساب درجة المخاطرة"""
    risk = 100 - conf
    if rsi < 25 or rsi > 75:
        risk += 15
    if direction == "BUY" and rsi > 65:
        risk += 10
    if direction == "SELL" and rsi < 35:
        risk += 10
    risk = min(risk, 99)

    if risk < 30:
        return risk, "🟢 منخفضة", "مخاطرة منخفضة - فرصة جيدة"
    elif risk < 55:
        return risk, "🟡 متوسطة", "مخاطرة متوسطة - تداول بحذر"
    else:
        return risk, "🔴 عالية", "مخاطرة عالية - حجم صغير فقط"


def analyze(df):
    df = calculate_indicators(df)
    last = df.iloc[-1]
    price = last['Close']
    score_buy = score_sell = 0
    details = []

    rsi = last['RSI']
    if rsi < 30:   score_buy  += 25; details.append(f"RSI تشبع بيعي ({rsi:.0f}) 🟢")
    elif rsi < 45: score_buy  += 12; details.append(f"RSI منطقة شراء ({rsi:.0f})")
    elif rsi > 70: score_sell += 25; details.append(f"RSI تشبع شرائي ({rsi:.0f}) 🔴")
    elif rsi > 55: score_sell += 12; details.append(f"RSI منطقة بيع ({rsi:.0f})")

    if last['MACD'] > last['MACD_Signal']: score_buy  += 20; details.append("MACD إيجابي ↗️")
    else:                                   score_sell += 20; details.append("MACD سلبي ↘️")

    if last['EMA9'] > last['EMA21'] > last['EMA50']:   score_buy  += 20; details.append("EMAs مرتبة صعوداً 📈")
    elif last['EMA9'] < last['EMA21'] < last['EMA50']: score_sell += 20; details.append("EMAs مرتبة هبوطاً 📉")

    if price <= last['BB_Lower']:   score_buy  += 15; details.append("عند الحد السفلي لبولنجر 🟢")
    elif price >= last['BB_Upper']: score_sell += 15; details.append("عند الحد العلوي لبولنجر 🔴")

    if last['Stoch_K'] < 20:   score_buy  += 10; details.append("Stochastic تشبع بيعي")
    elif last['Stoch_K'] > 80: score_sell += 10; details.append("Stochastic تشبع شرائي")

    direction = "BUY" if score_buy > score_sell else "SELL"
    total = score_buy + score_sell
    conf = round(max(score_buy, score_sell) / total * 100) if total > 0 else 50

    atr = last['ATR']
    if direction == "BUY":
        sl  = round(price - 1.5 * atr, 0)
        tp1 = round(price + 1.0 * atr, 0)
        tp2 = round(price + 2.2 * atr, 0)
        tp3 = round(price + 4.0 * atr, 0)
    else:
        sl  = round(price + 1.5 * atr, 0)
        tp1 = round(price - 1.0 * atr, 0)
        tp2 = round(price - 2.2 * atr, 0)
        tp3 = round(price - 4.0 * atr, 0)

    rr = round(abs(tp2 - price) / abs(sl - price), 2) if abs(sl - price) > 0 else 0
    risk_pct, risk_label, risk_msg = get_risk_level(conf, direction, rsi)

    return {
        "direction": direction, "conf": conf, "price": round(price, 0),
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl, "rr": rr,
        "atr": round(atr, 0), "details": details[:4],
        "score_buy": score_buy, "score_sell": score_sell,
        "risk_pct": risk_pct, "risk_label": risk_label, "risk_msg": risk_msg,
        "rsi": round(rsi, 1)
    }


def build_message(res, auto=False):
    emoji = "🟢" if res['direction'] == "BUY" else "🔴"
    dir_ar = "شراء  BUY ⬆️" if res['direction'] == "BUY" else "بيع  SELL ⬇️"
    conf = res['conf']
    conf_bar = "█" * (conf // 10) + "░" * (10 - conf // 10)
    now = datetime.now().strftime("%d/%m/%Y  %H:%M")
    header = "🔔 إشارة تلقائية جديدة!" if auto else "📊 نتيجة التحليل"

    msg = f"""
{emoji}{emoji}{emoji}  BTC/USD  •  إشارة بيتكوين  {emoji}{emoji}{emoji}
━━━━━━━━━━━━━━━━━━━━━━━━
{header}
⏰ {now}

💰 سعر الدخول:  ${res['price']:,.0f}
📊 الاتجاه:  {dir_ar}

━━━━━━  🎯 الأهداف  ━━━━━━
✅  TP1  »  ${res['tp1']:,.0f}
✅  TP2  »  ${res['tp2']:,.0f}
✅  TP3  »  ${res['tp3']:,.0f}
🛑  SL    »  ${res['sl']:,.0f}

⚖️ نسبة العائد/المخاطرة:  1:{res['rr']}

━━━━━━  📈 التحليل الفني  ━━━━━━
🔹 RSI:  {res['rsi']}"""

    for d in res['details']:
        msg += f"\n▫️ {d}"

    msg += f"""

━━━━━━  🎯 قوة الإشارة  ━━━━━━
{conf_bar}  {conf}%

━━━━━━  ⚠️ المخاطرة  ━━━━━━
{res['risk_label']}  •  {res['risk_pct']}%
{res['risk_msg']}

━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط
📚 تداول بمسؤولية دائماً
"""
    return msg.strip()


# ==================== كوماندات ====================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 تحليل فوري", callback_data='analyze'),
         InlineKeyboardButton("💰 سعر BTC", callback_data='price')],
        [InlineKeyboardButton("ℹ️ عن البوت", callback_data='about')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = """🤖 أهلاً وسهلاً! أنا بوت إشارات البيتكوين 🪙

━━━━━━━━━━━━━━━━━━━━
أنا بوت ذكي متخصص في تحليل سوق البيتكوين باستخدام أحدث المؤشرات الفنية 📊

🔍 ماذا أفعل؟
▫️ أحلل السوق باستمرار
▫️ أرسل إشارات فقط عند وجود فرصة واضحة
▫️ أحدد 3 أهداف لكل صفقة
▫️ أحسب درجة المخاطرة بدقة

📌 الأوامر المتاحة:
/analyze — تحليل فوري الآن
/price — سعر BTC الحالي
/about — معلومات عن البوت
━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط"""

    await update.message.reply_text(msg, reply_markup=reply_markup)


async def about(update, context: ContextTypes.DEFAULT_TYPE):
    msg = """ℹ️ عن البوت

🤖 الاسم: BTC Signals SazBot
📊 التخصص: تحليل سوق البيتكوين

🔬 المؤشرات المستخدمة:
▫️ RSI — مؤشر القوة النسبية
▫️ MACD — تقارب وتباعد المتوسطات
▫️ EMA 9/21/50 — المتوسطات المتحركة
▫️ Bollinger Bands — نطاقات بولنجر
▫️ Stochastic — مذبذب ستوكاستيك
▫️ ATR — متوسط المدى الحقيقي

⚙️ كيف يعمل؟
البوت يحلل السوق كل ساعة ويرسل إشارة فقط عندما تكون قوة الإشارة فوق 65%

⚠️ تنبيه مهم:
هذا البوت للأغراض التعليمية فقط. لا تتداول بأموال لا تستطيع خسارتها."""
    await update.message.reply_text(msg)


async def analyze_now(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري تحليل السوق...")
    try:
        df = get_btc_data()
        if df is None or len(df) < 55:
            await update.message.reply_text("❌ فشل جلب البيانات، حاول بعد دقيقة")
            return
        res = analyze(df)
        await update.message.reply_text(build_message(res))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")


async def price(update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = get_btc_price()
        if not data:
            await update.message.reply_text("❌ فشل جلب السعر")
            return
        p = data['usd']
        change = data['usd_24h_change']
        arrow = "📈" if change > 0 else "📉"
        msg = f"""💰 سعر البيتكوين الآن

₿ BTC/USD:  ${p:,.0f}
{arrow} التغيير 24h:  {change:+.2f}%
🕐 آخر تحديث:  {datetime.now().strftime('%H:%M')}"""
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def button_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'analyze':
        await query.message.reply_text("⏳ جاري تحليل السوق...")
        try:
            df = get_btc_data()
            if df is None or len(df) < 55:
                await query.message.reply_text("❌ فشل جلب البيانات")
                return
            res = analyze(df)
            await query.message.reply_text(build_message(res))
        except Exception as e:
            await query.message.reply_text(f"❌ خطأ: {str(e)}")
    elif query.data == 'price':
        data = get_btc_price()
        if data:
            p = data['usd']
            change = data['usd_24h_change']
            arrow = "📈" if change > 0 else "📉"
            await query.message.reply_text(f"₿ BTC/USD: ${p:,.0f}\n{arrow} {change:+.2f}%")
    elif query.data == 'about':
        await about(update, context)


async def auto_signals(context):
    try:
        df = get_btc_data()
        if df is None or len(df) < 55:
            return
        res = analyze(df)
        if res['conf'] >= MIN_CONFIDENCE:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=build_message(res, auto=True))
            logger.info(f"✅ إشارة تلقائية أُرسلت - قوة: {res['conf']}%")
        else:
            logger.info(f"⚪ لا توجد فرصة واضحة - قوة: {res['conf']}%")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("analyze", analyze_now))
    app.add_handler(CommandHandler("price",   price))
    app.add_handler(CommandHandler("about",   about))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES * 60, first=30)
    logger.info("₿ BTC Bot يعمل!")
    app.run_polling()


if __name__ == "__main__":
    main()
