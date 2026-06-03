import os
import logging
import requests
from datetime import datetime
import pandas as pd
import numpy as np
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import ta

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@btc_signals_saz")
INTERVAL_MINUTES = 60

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def get_btc_data(days=30, interval="hourly"):
    """جلب بيانات BTC من CoinGecko - مجاني وبدون حجب"""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        params = {"vs_currency": "usd", "days": days, "interval": interval}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        prices  = data['prices']
        volumes = data['total_volumes']

        df = pd.DataFrame(prices, columns=['timestamp', 'Close'])
        df['Volume'] = [v[1] for v in volumes]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')

        # حساب High/Low تقريبي
        df['High'] = df['Close'].rolling(3).max()
        df['Low']  = df['Close'].rolling(3).min()
        df['Open'] = df['Close'].shift(1)
        df = df.dropna()

        return df
    except Exception as e:
        logger.error(f"خطأ CoinGecko: {e}")
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

    if last['EMA9'] > last['EMA21'] > last['EMA50']: score_buy  += 20; details.append("EMAs صاعدة 📈")
    elif last['EMA9'] < last['EMA21'] < last['EMA50']: score_sell += 20; details.append("EMAs هابطة 📉")

    if price <= last['BB_Lower']: score_buy  += 15; details.append("عند Band السفلي 🟢")
    elif price >= last['BB_Upper']: score_sell += 15; details.append("عند Band العلوي 🔴")

    if last['Stoch_K'] < 20: score_buy  += 10; details.append("Stoch تشبع بيعي")
    elif last['Stoch_K'] > 80: score_sell += 10; details.append("Stoch تشبع شرائي")

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

    return {
        "direction": direction, "conf": conf, "price": round(price, 0),
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "rr": rr, "atr": round(atr, 0), "details": details[:3],
        "score_buy": score_buy, "score_sell": score_sell
    }


def build_message(res):
    emoji = "🟢" if res['direction'] == "BUY" else "🔴"
    dir_ar = "شراء BUY ⬆️" if res['direction'] == "BUY" else "بيع SELL ⬇️"
    conf = res['conf']
    conf_bar = "█" * (conf // 10) + "░" * (10 - conf // 10)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    msg = f"""{emoji}{emoji} إشارة بيتكوين | BTC/USD {emoji}{emoji}
━━━━━━━━━━━━━━━━━━━━━
📊 الاتجاه: {dir_ar}
💰 سعر الدخول: ${res['price']:,.0f}
🕐 التوقيت: {now}

━━━━ 🎯 الأهداف ━━━━
✅ TP1 (هدف أول):   ${res['tp1']:>10,.0f}
✅ TP2 (هدف ثاني):  ${res['tp2']:>10,.0f}
✅ TP3 (هدف ثالث):  ${res['tp3']:>10,.0f}
🛑 SL  (وقف خسارة): ${res['sl']:>10,.0f}
⚖️ Risk/Reward: 1:{res['rr']}

━━━━ 📊 التحليل ━━━━"""

    for d in res['details']:
        msg += f"\n• {d}"

    msg += f"""

━━━━ 💡 قوة الإشارة ━━━━
{conf_bar} {conf}%
📊 شراء: {res['score_buy']} | بيع: {res['score_sell']}
ATR: ${res['atr']:,.0f}

━━━━━━━━━━━━━━━━━━━━━
⚠️ للأغراض التعليمية فقط
تداول بمسؤولية 📚"""
    return msg.strip()


async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""₿ مرحباً في بوت إشارات البيتكوين!

📌 الأوامر:
/analyze - تحليل فوري
/status  - سعر BTC الحالي

🔔 إشارات تلقائية كل ساعة""")


async def analyze_now(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري التحليل...")
    try:
        df = get_btc_data(days=30, interval="hourly")
        if df is None or len(df) < 55:
            await update.message.reply_text("❌ فشل جلب البيانات، حاول مرة ثانية")
            return
        res = analyze(df)
        await update.message.reply_text(build_message(res))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")


async def status(update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true", timeout=10)
        data = r.json()['bitcoin']
        price = data['usd']
        change = data['usd_24h_change']
        arrow = "📈" if change > 0 else "📉"
        await update.message.reply_text(f"₿ BTC/USD الآن\n\n💰 السعر: ${price:,.0f}\n{arrow} التغيير 24h: {change:+.2f}%")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def auto_signals(context):
    try:
        df = get_btc_data(days=30, interval="hourly")
        if df is None or len(df) < 55:
            return
        res = analyze(df)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=build_message(res))
        logger.info("✅ إشارة تلقائية أُرسلت")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("analyze", analyze_now))
    app.add_handler(CommandHandler("status",  status))
    app.job_queue.run_repeating(auto_signals, interval=INTERVAL_MINUTES * 60, first=15)
    logger.info("₿ BTC Bot يعمل!")
    app.run_polling()


if __name__ == "__main__":
    main()
