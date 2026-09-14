#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance Spot 24/7 Cloud Trading Bot (BTC/USDT)
Optimized for 24/7 continuous worker deployment on Railway, Docker, or VPS.
"""

import os
import sys
import time
import json
import logging
import urllib.request
from datetime import datetime
import ccxt
from dotenv import load_dotenv

# Print current public IP safely (useful for Binance API IP whitelisting on Railway/VPS)
try:
    _ip_req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "Mozilla/5.0"})
    current_public_ip = urllib.request.urlopen(_ip_req, timeout=5).read().decode().strip()
    print(f"MY_CURRENT_IP: {current_public_ip}")
except Exception as _ip_err:
    print(f"Notice: Could not fetch public IP ({_ip_err})")

# تحميل متغيرات البيئة من ملف .env في حال وجوده محلياً
load_dotenv()

# ==========================================
# 1. إعدادات السجل والطباعة (Logging Setup)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BinanceSpotBot")

# ==========================================
# 2. قراءة المتغيرات البيئية والإعدادات
# ==========================================
def sanitize_key(key):
    if not key:
        return ""
    cleaned = key.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return "".join(c for c in cleaned if c.isprintable() and not c.isspace())

API_KEY = sanitize_key(os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_KEY") or "")
API_SECRET = sanitize_key(os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET") or "")

SYMBOL = os.environ.get("SYMBOL", "BTC/USDT").strip()
TARGET_ORDER_USD = float(os.environ.get("TARGET_ORDER_USD", "5.5").strip())
LIVE_TRADING = os.environ.get("LIVE_TRADING", "false").strip().lower() in ("true", "1", "yes")
MAX_POSITIONS = max(1, int(os.environ.get("MAX_POSITIONS", "1").strip()))
LOOP_INTERVAL_SEC = max(3, int(os.environ.get("LOOP_INTERVAL_SEC", "10").strip()))
BUY_COOLDOWN_SEC = max(0, int(os.environ.get("BUY_COOLDOWN_SEC", "30").strip()))

# إعدادات الشراء عند الارتداد من القاع (Dip & Rebound)
BUY_DIP_MIN_PCT = max(0.0, float(os.environ.get("BUY_DIP_MIN_PCT", "0.25").strip()))
BUY_REBOUND_CONFIRM_PCT = max(0.0, float(os.environ.get("BUY_REBOUND_CONFIRM_PCT", "0.08").strip()))
BUY_RSI_MAX = float(os.environ.get("BUY_RSI_MAX", "48").strip())
MIN_VOLATILITY_PCT = max(0.0, float(os.environ.get("MIN_VOLATILITY_PCT", "0.20").strip()))
MAX_SPREAD_PCT = max(0.0, float(os.environ.get("MAX_SPREAD_PCT", "0.15").strip()))

# إعدادات تتبع السعر اللحظي (Trailing High-Water Take Profit & Emergency Stop)
TRAILING_STOP_ENABLED = os.environ.get("TRAILING_STOP_ENABLED", "true").strip().lower() in ("true", "1", "yes")
TRAILING_ACTIVATION_PCT = max(0.0, float(os.environ.get("TRAILING_ACTIVATION_PCT", "0.15").strip()))
TRAILING_CALLBACK_PCT = max(0.0, float(os.environ.get("TRAILING_CALLBACK_PCT", "0.20").strip()))
STOP_LOSS_PCT = max(0.01, float(os.environ.get("STOP_LOSS_PCT", "0.40").strip()))

# معايير منع تجمد العملة والسيولة (Anti-Stagnation / Capital Release)
MAX_HOLD_TIME_SEC = max(0, int(os.environ.get("MAX_HOLD_TIME_SEC", "1200").strip()))
STAGNANT_EXIT_PCT = float(os.environ.get("STAGNANT_EXIT_PCT", "0.00").strip())

POSITIONS_FILE = "positions.json"


def check_api_keys():
    """التحقق الإجباري من وجود مفاتيح API في متغيرات البيئة"""
    if not API_KEY or not API_SECRET:
        logger.error("=" * 65)
        logger.error("خطأ أمني فادح: مفاتيح Binance API غير موجودة في متغيرات البيئة!")
        logger.error("يرجى ضبط المتغيرات التالية في منصة الاستضافة أو مستودع GitHub:")
        logger.error("  - BINANCE_API_KEY (أو BINANCE_KEY)")
        logger.error("  - BINANCE_API_SECRET (أو BINANCE_SECRET)")
        logger.error("=" * 65)
        sys.exit(1)


# ==========================================
# 3. إدارة حالة الصفقات في ملف مؤقت/الذاكرة
# ==========================================
def load_positions():
    """تحميل الصفقات المفتوحة من الملف لضمان عدم فقدانها عند إعادة تشغيل البوت سحابياً"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"تعذر قراءة ملف الصفقات {POSITIONS_FILE}: {e}. سيتم البدء بقائمة فارغة.")
    return []


def save_positions(positions):
    """حفظ الصفقات المفتوحة في الملف المحلي"""
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"خطأ أثناء حفظ الصفقات في الملف: {e}")


# ==========================================
# 4. تهيئة منصة بينانس عبر CCXT
# ==========================================
def init_exchange():
    """إنشاء اتصال مع Binance Spot مع خيارات الأمان والحدود الزمنية"""
    check_api_keys()
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',          # تفعيل السوق الفوري حصراً
            'adjustForTimeDifference': True  # مزامنة التوقيت مع خوادم بينانس تلقائياً
        }
    })
    return exchange


def get_min_notional(market):
    """
    استخراج الحد الأدنى لقيمة الصفقة (min_notional) من بيانات السوق بدقة
    في منصة بينانس الفوري الحد الأدنى المعتاد هو 5 USDT
    """
    min_cost = 5.0  # القيمة الافتراضية الآمنة لـ Binance Spot
    try:
        # فحص cost min من limits الموحدة في CCXT
        if 'limits' in market and 'cost' in market['limits'] and market['limits']['cost']['min'] is not None:
            min_cost = float(market['limits']['cost']['min'])
        else:
            # فحص فلاتر بينانس الخام (raw filters)
            filters = market.get('info', {}).get('filters', [])
            for f in filters:
                filter_type = f.get('filterType')
                if filter_type in ['NOTIONAL', 'MIN_NOTIONAL']:
                    if 'minNotional' in f:
                        min_cost = float(f['minNotional'])
                    elif 'notional' in f:
                        min_cost = float(f['notional'])
                    break
    except Exception as e:
        logger.warning(f"تعذر استخراج minNotional تلقائياً، سيتم اعتماد 5.0 USDT: {e}")

    return min_cost


def calculate_rsi(closes, period=14):
    """حساب مؤشر القوة النسبية RSI للمساعدة في تحديد ارتدادات الأسعار"""
    if len(closes) < period + 1:
        return 50.0  # قيمة محايدة
    
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    
    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


# ==========================================
# 5. الدورة الرئيسية للبوت (24/7 Cloud Loop)
# ==========================================
def main():
    logger.info("=" * 65)
    logger.info("بدء تشغيل بوت التداول الفوري السحابي (Binance Spot Bot)")
    logger.info(f"الزوج المعتمد: {SYMBOL} (Spot حصراً) | التداول الحقيقي: {LIVE_TRADING}")
    logger.info(f"أقصى عدد صفقات متزامنة: {MAX_POSITIONS} | قيمة الصفقة: {TARGET_ORDER_USD} USDT")
    logger.info(f"تتبع السعر اللحظي (Trailing Stop): تفعيل عند +{TRAILING_ACTIVATION_PCT}% | ارتداد للبيع: {TRAILING_CALLBACK_PCT}%")
    logger.info(f"معيار منع تجمد العملة (Anti-Stagnation): إغلاق بعد {MAX_HOLD_TIME_SEC // 60} دقيقة إذا كان العائد <= +{STAGNANT_EXIT_PCT}%")
    logger.info(f"هدف وقف الخسارة الصارم (Emergency SL): -{STOP_LOSS_PCT}%")
    logger.info("=" * 65)

    exchange = init_exchange()

    # تحميل الأسواق والتحقق من الزوج وحدود التداول
    try:
        markets = exchange.load_markets()
        if SYMBOL not in markets:
            logger.error(f"الرمز {SYMBOL} غير متاح في أسواق Binance Spot!")
            sys.exit(1)
        market = markets[SYMBOL]
        min_notional = get_min_notional(market)
        logger.info(f"تم فحص حدود الزوج بنجاح: الحد الأدنى لقيمة الصفقة (min_notional) هو: {min_notional} USDT")
    except Exception as e:
        logger.error(f"فشل أثناء تحميل بيانات الأسواق من Binance: {e}")
        sys.exit(1)

    positions = load_positions()
    logger.info(f"تم تحميل {len(positions)} صفقة نشطة سابقة من الذاكرة/الملف.")

    last_buy_timestamp = 0.0

    while True:
        try:
            now_ts = time.time()

            # 1. جلب السعر اللحظي ومراقبة الفرق السعري (Spread)
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = float(ticker['last'])
            bid_price = float(ticker['bid']) if ticker.get('bid') else current_price
            ask_price = float(ticker['ask']) if ticker.get('ask') else current_price
            spread_pct = ((ask_price - bid_price) / current_price) * 100.0 if current_price > 0 else 0.0

            # 2. جلب الأرصدة المتاحة
            balance = exchange.fetch_balance()
            free_usdt = float(balance['free'].get('USDT', 0.0))
            free_btc = float(balance['free'].get('BTC', 0.0))
            total_usdt_est = free_usdt + (free_btc * current_price)

            # طباعة لوحة المراقبة اللحظية
            logger.info("-" * 65)
            logger.info(f"[مراقبة لحظية] السعر: ${current_price:,.2f} | السبريد: {spread_pct:.3f}% | الرصيد: {free_usdt:.2f} USDT | {free_btc:.6f} BTC (~${total_usdt_est:.2f})")
            logger.info(f"الصفقات النشطة حالياً: {len(positions)} / {MAX_POSITIONS}")

            # ==========================================
            # 3. إدارة وتتبع الصفقات المفتوحة (Trailing & TP & SL & Anti-Stagnation)
            # ==========================================
            remaining_positions = []
            for i, pos in enumerate(positions, 1):
                entry_price = float(pos['entry_price'])
                amount = float(pos['amount'])
                created_at_ts = float(pos.get('created_at_ts', now_ts))
                highest_price = float(pos.get('highest_price', entry_price))
                trailing_active = bool(pos.get('trailing_active', False))

                # تحديث القمة اللحظية المحققة للصفقة (High-Water Mark)
                if current_price > highest_price:
                    highest_price = current_price
                    pos['highest_price'] = highest_price

                pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
                peak_gain_pct = ((highest_price - entry_price) / entry_price) * 100.0
                drop_from_peak_pct = ((highest_price - current_price) / highest_price) * 100.0 if highest_price > 0 else 0.0
                hold_duration_sec = now_ts - created_at_ts
                hold_mins = int(hold_duration_sec // 60)

                # تفعيل التتبع اللحظي بمجرد الوصول لهدف البداية
                if TRAILING_STOP_ENABLED and peak_gain_pct >= TRAILING_ACTIVATION_PCT:
                    if not trailing_active:
                        logger.info(f"🎯 تفعيل تتبع الأرباح اللحظي (Trailing Active) للصفقة #{i}! القمة الحالية: ${highest_price:,.2f} (+{peak_gain_pct:.2f}%)")
                    trailing_active = True
                    pos['trailing_active'] = True

                trail_status = f" | [Trailing نشط - ارتداد: {drop_from_peak_pct:.2f}%]" if trailing_active else ""
                logger.info(f"  └─ صفقة #{i} | دخول: ${entry_price:,.2f} | قمة: ${highest_price:,.2f} | العائد: {pnl_pct:+.2f}% | مدة: {hold_mins}د{trail_status}")

                # أ) جني الأرباح عبر التتبع اللحظي (Trailing Take Profit) عند ارتداد السعر عن أعلى قمة
                if trailing_active and drop_from_peak_pct >= TRAILING_CALLBACK_PCT:
                    logger.info(f"📈 ارتداد السعر بمقدار {drop_from_peak_pct:.2f}% من أعلى قمة (${highest_price:,.2f}) للصفقة #{i}! جارٍ حجز الأرباح اللحظية فوراً بالبيع...")
                    try:
                        sell_amount = float(exchange.amount_to_precision(SYMBOL, amount))
                        executed_price = current_price
                        order_id = f"sim_tp_{int(now_ts)}"
                        if LIVE_TRADING:
                            sell_order = exchange.create_market_sell_order(SYMBOL, sell_amount)
                            executed_price = float(sell_order.get('average', current_price))
                            order_id = sell_order.get('id')
                        actual_pnl = ((executed_price - entry_price) / entry_price) * 100.0
                        logger.info(f"🏆 تم تنفيذ أمر حجز الأرباح (Trailing Exit) بنجاح! القمة: ${highest_price:,.2f} | البيع: ${executed_price:,.2f} | الربح الصافي: {actual_pnl:+.2f}%")
                        continue
                    except Exception as err:
                        logger.error(f"❌ فشل تنفيذ Trailing Take Profit: {err}")
                        remaining_positions.append(pos)
                        continue

                # ج) وقف الخسارة الصارم (Stop Loss)
                elif pnl_pct <= -STOP_LOSS_PCT:
                    logger.warning(f"⚠️ هبوط السعر إلى حد وقف الخسارة ({pnl_pct:.2f}% <= -{STOP_LOSS_PCT}%) للصفقة #{i}! جارٍ إيقاف النزيف بالبيع الفوري...")
                    try:
                        sell_amount = float(exchange.amount_to_precision(SYMBOL, amount))
                        executed_price = current_price
                        order_id = f"sim_sl_{int(now_ts)}"
                        if LIVE_TRADING:
                            sell_order = exchange.create_market_sell_order(SYMBOL, sell_amount)
                            executed_price = float(sell_order.get('average', current_price))
                            order_id = sell_order.get('id')
                        actual_loss = ((executed_price - entry_price) / entry_price) * 100.0
                        logger.info(f"🛑 تم تنفيذ أمر وقف الخسارة بنجاح. رقم الطلب: {order_id} | سعر التنفيذ: ${executed_price:,.2f} | نسبة الخسارة: {actual_loss:.2f}%")
                        continue
                    except Exception as err:
                        logger.error(f"❌ فشل تنفيذ أمر وقف الخسارة: {err}")
                        remaining_positions.append(pos)
                        continue

                # د) معيار عدم تجمد العملة (Anti-Stagnation Release)
                elif MAX_HOLD_TIME_SEC > 0 and hold_duration_sec >= MAX_HOLD_TIME_SEC and (pnl_pct <= STAGNANT_EXIT_PCT or pnl_pct < TRAILING_ACTIVATION_PCT):
                    logger.warning(f"⏳ معيار منع تجمد العملة: مضى {hold_mins} دقيقة والصفقة متجمدة (عائد {pnl_pct:+.2f}% ضمن نطاق الركود). جارٍ تسييل الصفقة لتحرير رأس المال...")
                    try:
                        sell_amount = float(exchange.amount_to_precision(SYMBOL, amount))
                        executed_price = current_price
                        order_id = f"sim_antifreeze_{int(now_ts)}"
                        if LIVE_TRADING:
                            sell_order = exchange.create_market_sell_order(SYMBOL, sell_amount)
                            executed_price = float(sell_order.get('average', current_price))
                            order_id = sell_order.get('id')
                        actual_pnl = ((executed_price - entry_price) / entry_price) * 100.0
                        logger.info(f"🔓 تم تسييل الصفقة المتجمدة بنجاح لتحرير السيولة! سعر التنفيذ: ${executed_price:,.2f} | النتيجة: {actual_pnl:+.2f}%")
                        continue
                    except Exception as err:
                        logger.error(f"❌ فشل تسييل الصفقة المتجمدة: {err}")
                        remaining_positions.append(pos)
                        continue

                else:
                    # تحديث بيانات المراقبة في الذاكرة
                    pos['highest_price'] = highest_price
                    pos['trailing_active'] = trailing_active
                    remaining_positions.append(pos)

            # تحديث قائمة الصفقات وحفظها
            if remaining_positions != positions:
                positions = remaining_positions
                save_positions(positions)

            # ==========================================
            # 4. فحص شروط فتح صفقة جديدة (Dip & Rebound Strategy)
            # ==========================================
            if len(positions) < MAX_POSITIONS:
                effective_order_cost = max(TARGET_ORDER_USD, min_notional + 0.20)
                time_since_last_buy = now_ts - last_buy_timestamp
                is_cooldown_passed = time_since_last_buy >= BUY_COOLDOWN_SEC

                if not is_cooldown_passed:
                    remaining_cooldown = int(BUY_COOLDOWN_SEC - time_since_last_buy)
                    logger.info(f"⏳ فترة التهدئة بين الصفقات نشطة (متبقي {remaining_cooldown} ثانية قبل السماح بشراء جديد).")
                elif free_usdt < effective_order_cost and LIVE_TRADING:
                    logger.info(f"ℹ️ رصيد USDT غير كافٍ لفتح صفقة جديدة (المطلوب: {effective_order_cost:.2f} USDT | المتاح: {free_usdt:.2f} USDT).")
                elif spread_pct > MAX_SPREAD_PCT:
                    logger.info(f"🛡️ حماية من التجمد: السبريد مرتفع ({spread_pct:.3f}% > {MAX_SPREAD_PCT:.3f}%). تجنب الدخول لضعف السيولة اللحظية.")
                else:
                    # فحص الهبوط النسبي والارتداد التأكيدي من القاع
                    try:
                        ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe='1m', limit=20)
                        if ohlcv and len(ohlcv) >= 10:
                            highs = [c[2] for c in ohlcv]
                            lows = [c[3] for c in ohlcv]
                            closes = [c[4] for c in ohlcv]

                            min_l = min(lows)
                            max_h = max(highs)
                            volatility_15m = ((max_h - min_l) / min_l) * 100.0 if min_l > 0 else 0.0
                            current_rsi = calculate_rsi(closes, period=14)

                            recent_high = max(highs[-15:])
                            recent_low = min(lows[-15:])
                            dip_pct = ((recent_high - recent_low) / recent_high) * 100.0 if recent_high > 0 else 0.0
                            rebound_pct = ((current_price - recent_low) / recent_low) * 100.0 if recent_low > 0 else 0.0

                            logger.info(f"📊 التحليل اللحظي: تقلب 15د: {volatility_15m:.2f}% | هبوط: {dip_pct:.2f}% | ارتداد: +{rebound_pct:.2f}% | RSI: {current_rsi:.1f}")

                            volatility_ok = (volatility_15m >= MIN_VOLATILITY_PCT)
                            dip_ok = (dip_pct >= BUY_DIP_MIN_PCT) or (BUY_DIP_MIN_PCT <= 0)
                            rebound_ok = (rebound_pct >= BUY_REBOUND_CONFIRM_PCT) or (BUY_REBOUND_CONFIRM_PCT <= 0)
                            rsi_ok = (current_rsi <= BUY_RSI_MAX)
                            not_at_peak = (current_price <= recent_high)

                            if not volatility_ok:
                                logger.info(f"😴 السوق هادئ/متجمد حالياً ({volatility_15m:.2f}% < {MIN_VOLATILITY_PCT}%). في انتظار حركة نشطة.")
                            elif not dip_ok:
                                logger.info(f"⏳ لم يتحقق شرط الهبوط النسبي ({dip_pct:.2f}% < {BUY_DIP_MIN_PCT}%).")
                            elif not rebound_ok:
                                logger.info(f"⏳ في انتظار تأكيد الارتداد من القاع ({rebound_pct:.2f}% < {BUY_REBOUND_CONFIRM_PCT}%).")
                            elif not rsi_ok:
                                logger.info(f"⏳ مؤشر RSI مرتفع نسبياً ({current_rsi:.1f} > {BUY_RSI_MAX}). تجنب الشراء عند قمم التشبع.")
                            elif not not_at_peak:
                                logger.info("⏳ السعر عند قمة الشموع الأخيرة، في انتظار تشكل قاع جديد.")
                            else:
                                raw_amount = effective_order_cost / ask_price
                                amount_str = exchange.amount_to_precision(SYMBOL, raw_amount)
                                buy_amount = float(amount_str)
                                estimated_cost = buy_amount * ask_price

                                if estimated_cost < min_notional:
                                    amount_step = market.get('precision', {}).get('amount', 8)
                                    min_qty_step = 10 ** (-amount_step)
                                    buy_amount += min_qty_step
                                    buy_amount = float(exchange.amount_to_precision(SYMBOL, buy_amount))

                                order_mode = "حقيقي (Live)" if LIVE_TRADING else "محاكاة (Simulation)"
                                logger.info(f"🚀 تأكيد الارتداد اللحظي! تنفيذ شراء {order_mode}: {buy_amount:.6f} BTC (~${effective_order_cost:.2f} USDT)...")

                                filled_price = ask_price
                                filled_qty = buy_amount
                                total_cost = filled_price * filled_qty
                                order_id = f"sim_buy_{int(now_ts)}"

                                if LIVE_TRADING:
                                    buy_order = exchange.create_market_buy_order(SYMBOL, buy_amount)
                                    filled_price = float(buy_order.get('average', ask_price))
                                    filled_qty = float(buy_order.get('filled', buy_amount))
                                    total_cost = filled_price * filled_qty
                                    order_id = buy_order.get('id')

                                logger.info(f"✅ تم تنفيذ الشراء بنجاح! رقم الطلب: {order_id} | سعر الدخول: ${filled_price:,.2f} | التكلفة: {total_cost:.2f} USDT")

                                new_position = {
                                    "id": order_id,
                                    "symbol": SYMBOL,
                                    "amount": filled_qty,
                                    "entry_price": filled_price,
                                    "highest_price": filled_price,
                                    "cost": total_cost,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "created_at_ts": now_ts,
                                    "trailing_active": False,
                                    "side": "buy"
                                }
                                positions.append(new_position)
                                save_positions(positions)
                                last_buy_timestamp = now_ts
                    except Exception as buy_err:
                        logger.error(f"❌ خطأ أثناء تقييم أو تنفيذ أمر الشراء: {buy_err}")
            else:
                logger.info(f"🔒 تم بلوغ الحد الأقصى للصفقات المتزامنة ({MAX_POSITIONS}/{MAX_POSITIONS}). في انتظار جني الأرباح أو تسييل عدم التجمد.")

        except ccxt.RateLimitExceeded as rle:
            logger.warning(f"⚠️ تم تجاوز معدل طلبات بينانس (Rate Limit Exceeded): {rle}. سيتم التوقف مؤقتاً لمدة 60 ثانية لحماية الحساب...")
            time.sleep(60)
        except (ccxt.NetworkError, ccxt.RequestTimeout) as ne:
            logger.warning(f"⚠️ خطأ مؤقت في الاتصال بالشبكة مع بينانس: {ne}. جارٍ الانتظار وإعادة المحاولة تلقائياً...")
            time.sleep(15)
        except ccxt.InsufficientFunds as ife:
            logger.error(f"❌ رصيد غير كافٍ لتنفيذ المعاملة: {ife}. سيتم الاستمرار في فحص الصفقات القائمة.")
            time.sleep(20)
        except ccxt.ExchangeError as ee:
            logger.error(f"❌ خطأ مسترجع من خادم Binance Spot: {ee}")
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info("🛑 تم إيقاف البوت يدوياً من قبل المستخدم. جارٍ الحفظ والخروج بأمان...")
            save_positions(positions)
            break
        except Exception as general_err:
            logger.error(f"⚠️ حدث خطأ غير متوقع: {general_err}", exc_info=True)
            time.sleep(10)

        # انتظار الفاصل الزمني المحدد قبل بدء الدورة التالية
        time.sleep(LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    main()
