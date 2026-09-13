#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance Spot 24/7 Cloud Trading Bot (BTC/USDT)
Designed for continuous 24/7 execution on cloud platforms (e.g., Bot-Hosting.net, VPS, Docker).
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
import ccxt
from dotenv import load_dotenv

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
# دعم الاسمين BINANCE_API_KEY و BINANCE_KEY لمرونة كاملة
API_KEY = (os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_KEY") or "").strip()
API_SECRET = (os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET") or "").strip()

SYMBOL = os.environ.get("SYMBOL", "BTC/USDT").strip()
TARGET_ORDER_USD = float(os.environ.get("TARGET_ORDER_USD", "5.5"))  # القيمة المستهدفة
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "2"))            # الحد الأقصى للصفقات المتزامنة
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "1.5"))   # نسبة جني الأرباح +1.5%
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "1.0"))       # نسبة وقف الخسارة -1.0%
LOOP_INTERVAL_SEC = int(os.environ.get("LOOP_INTERVAL_SEC", "10"))  # وقت الانتظار بين الدورات بالثواني
BUY_COOLDOWN_SEC = int(os.environ.get("BUY_COOLDOWN_SEC", "180"))   # فاصل زمني بين عمليات الشراء لمنع التكرار اللحظي

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
    logger.info(f"الزوج المعتمد: {SYMBOL} (Spot حصراً)")
    logger.info(f"أقصى عدد صفقات متزامنة: {MAX_POSITIONS}")
    logger.info(f"هدف جني الأرباح (TP): +{TAKE_PROFIT_PCT}%")
    logger.info(f"هدف وقف الخسارة (SL): -{STOP_LOSS_PCT}%")
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
            # 1. جلب السعر اللحظي للزوج
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = float(ticker['last'])
            bid_price = float(ticker['bid']) if ticker.get('bid') else current_price
            ask_price = float(ticker['ask']) if ticker.get('ask') else current_price

            # 2. جلب الأرصدة المتاحة
            balance = exchange.fetch_balance()
            free_usdt = float(balance['free'].get('USDT', 0.0))
            free_btc = float(balance['free'].get('BTC', 0.0))
            total_usdt_est = free_usdt + (free_btc * current_price)

            # طباعة لوحة المراقبة (Console Logs)
            logger.info("-" * 65)
            logger.info(f"[مراقبة لحظية] السعر الفوري لـ {SYMBOL}: ${current_price:,.2f} | الرصيد: {free_usdt:.2f} USDT | {free_btc:.6f} BTC (~${total_usdt_est:.2f})")
            logger.info(f"الصفقات النشطة حالياً: {len(positions)} / {MAX_POSITIONS}")

            # ==========================================
            # 3. إدارة وتتبع الصفقات المفتوحة (TP & SL)
            # ==========================================
            remaining_positions = []
            for i, pos in enumerate(positions, 1):
                entry_price = float(pos['entry_price'])
                amount = float(pos['amount'])
                pnl_pct = ((current_price - entry_price) / entry_price) * 100.0

                logger.info(f"  └─ صفقة #{i} | سعر الدخول: ${entry_price:,.2f} | الكمية: {amount:.6f} BTC | الربح/الخسارة: {pnl_pct:+.2f}%")

                # التحقق من هدف جني الأرباح (Take-Profit)
                if pnl_pct >= TAKE_PROFIT_PCT:
                    logger.info(f"🎉 تحقق هدف جني الأرباح (+{pnl_pct:.2f}% >= +{TAKE_PROFIT_PCT}%) للصفقة #{i}! جارٍ تنفيذ البيع الفوري بالسوق...")
                    try:
                        # ضبط الكمية بحسب دقة المنصة (precision)
                        sell_amount_str = exchange.amount_to_precision(SYMBOL, amount)
                        sell_amount = float(sell_amount_str)
                        
                        sell_order = exchange.create_market_sell_order(SYMBOL, sell_amount)
                        executed_price = float(sell_order.get('average', current_price))
                        actual_pnl = ((executed_price - entry_price) / entry_price) * 100.0
                        logger.info(f"✅ تم تنفيذ أمر البيع لجني الأرباح بنجاح! رقم الطلب: {sell_order.get('id')} | سعر التنفيذ: ${executed_price:,.2f} | العائد المحقق: {actual_pnl:+.2f}%")
                        continue  # تم إغلاق الصفقة، لا نضيفها إلى remaining_positions
                    except Exception as err:
                        logger.error(f"❌ فشل تنفيذ أمر جني الأرباح: {err}")
                        remaining_positions.append(pos)
                        continue

                # التحقق من وقف الخسارة (Stop-Loss)
                elif pnl_pct <= -STOP_LOSS_PCT:
                    logger.warning(f"⚠️ هبوط السعر إلى حد وقف الخسارة ({pnl_pct:.2f}% <= -{STOP_LOSS_PCT}%) للصفقة #{i}! جارٍ إيقاف النزيف بالبيع الفوري...")
                    try:
                        sell_amount_str = exchange.amount_to_precision(SYMBOL, amount)
                        sell_amount = float(sell_amount_str)

                        sell_order = exchange.create_market_sell_order(SYMBOL, sell_amount)
                        executed_price = float(sell_order.get('average', current_price))
                        actual_loss = ((executed_price - entry_price) / entry_price) * 100.0
                        logger.info(f"🛑 تم تنفيذ أمر وقف الخسارة بنجاح. رقم الطلب: {sell_order.get('id')} | سعر التنفيذ: ${executed_price:,.2f} | نسبة الخسارة: {actual_loss:.2f}%")
                        continue  # تم إغلاق الصفقة
                    except Exception as err:
                        logger.error(f"❌ فشل تنفيذ أمر وقف الخسارة: {err}")
                        remaining_positions.append(pos)
                        continue

                else:
                    # الصفقة مستمرة
                    remaining_positions.append(pos)

            # تحديث قائمة الصفقات وحفظها
            if len(remaining_positions) != len(positions):
                positions = remaining_positions
                save_positions(positions)

            # ==========================================
            # 4. فحص شروط فتح صفقة جديدة (Buy Logic)
            # ==========================================
            if len(positions) < MAX_POSITIONS:
                # حساب حجم الصفقة بدقة مع فحص min_notional
                # إذا كانت القيمة المستهدفة 3 دولار وأقل من الحد الأدنى لبينانس (5 دولار)، نعتمد الحد الأدنى مع هامش أمان
                effective_order_cost = max(TARGET_ORDER_USD, min_notional + 0.15)
                
                time_since_last_buy = time.time() - last_buy_timestamp
                is_cooldown_passed = time_since_last_buy >= BUY_COOLDOWN_SEC

                if not is_cooldown_passed:
                    remaining_cooldown = int(BUY_COOLDOWN_SEC - time_since_last_buy)
                    logger.info(f"⏳ فترة التهدئة بين الصفقات نشطة (متبقي {remaining_cooldown} ثانية قبل السماح بشراء جديد).")
                elif free_usdt < effective_order_cost:
                    logger.info(f"ℹ️ رصيد USDT غير كافٍ لفتح صفقة جديدة (المطلوب: {effective_order_cost:.2f} USDT | المتاح: {free_usdt:.2f} USDT).")
                else:
                    # جلب شموع 1 دقيقة لحساب مؤشر فني بسيط يساعد على الشراء في الارتدادات
                    try:
                        ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe='1m', limit=20)
                        closes = [candle[4] for candle in ohlcv]
                        current_rsi = calculate_rsi(closes, period=14)
                        logger.info(f"📊 مؤشر RSI (1m): {current_rsi:.1f} | السعر الحالي: ${current_price:,.2f}")

                        # شرط الدخول: إذا كان المؤشر يشير لهدوء أو ارتداد من تشبع بيعي (RSI < 52)
                        # أو إذا كانت القائمة فارغة ومضى وقت كافٍ
                        should_enter = (current_rsi <= 52.0) or (len(positions) == 0 and is_cooldown_passed)

                        if should_enter:
                            # حساب كمية البيتكوين المطلوبة
                            raw_amount = effective_order_cost / ask_price
                            amount_str = exchange.amount_to_precision(SYMBOL, raw_amount)
                            buy_amount = float(amount_str)
                            estimated_cost = buy_amount * ask_price

                            # التحقق الصارم من أن القيمة النهائية لا تقل عن min_notional
                            if estimated_cost < min_notional:
                                # زيادة أصغر وحدة مسموحة لتجاوز الحد الأدنى
                                amount_step = market.get('precision', {}).get('amount', 8)
                                min_qty_step = 10 ** (-amount_step)
                                buy_amount += min_qty_step
                                buy_amount = float(exchange.amount_to_precision(SYMBOL, buy_amount))

                            logger.info(f"🚀 الشروط متحققة! إرسال أمر شراء فوري بالسوق (Market Buy): {buy_amount:.6f} BTC (~${effective_order_cost:.2f} USDT)...")

                            buy_order = exchange.create_market_buy_order(SYMBOL, buy_amount)
                            filled_price = float(buy_order.get('average', ask_price))
                            filled_qty = float(buy_order.get('filled', buy_amount))
                            total_cost = filled_price * filled_qty

                            logger.info(f"✅ تم تنفيذ الشراء الفوري بنجاح! رقم الطلب: {buy_order.get('id')} | سعر الدخول: ${filled_price:,.2f} | التكلفة: {total_cost:.2f} USDT")

                            new_position = {
                                "id": buy_order.get('id'),
                                "symbol": SYMBOL,
                                "amount": filled_qty,
                                "entry_price": filled_price,
                                "cost": total_cost,
                                "timestamp": datetime.utcnow().isoformat()
                            }
                            positions.append(new_position)
                            save_positions(positions)
                            last_buy_timestamp = time.time()

                    except Exception as buy_err:
                        logger.error(f"❌ خطأ أثناء تنفيذ أمر الشراء: {buy_err}")
            else:
                logger.info(f"🔒 تم بلوغ الحد الأقصى للصفقات المتزامنة ({MAX_POSITIONS}/{MAX_POSITIONS}). في انتظار جني الأرباح أو وقف الخسارة.")

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
