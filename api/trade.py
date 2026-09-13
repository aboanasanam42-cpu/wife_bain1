#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vercel Serverless Function: Binance Spot Trading Bot (BTC/USDT)
Designed for serverless execution on Vercel (invoked via HTTP request or Vercel Cron).
"""

import os
import json
from http.server import BaseHTTPRequestHandler
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import ccxt

POSITIONS_FILE = "/tmp/positions.json"
TRADE_TRIGGER_TOKEN = os.environ.get("TRADE_TRIGGER_TOKEN", "").strip()
LIVE_TRADING = os.environ.get("LIVE_TRADING", "false").strip().lower() in ("true", "1", "yes")

def require_trigger_token(handler):
    if not TRADE_TRIGGER_TOKEN:
        raise PermissionError("TRADE_TRIGGER_TOKEN is not configured")
    auth = handler.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else handler.headers.get("X-Trade-Token", "").strip()
    if token != TRADE_TRIGGER_TOKEN:
        raise PermissionError("Unauthorized trade trigger")

def create_market_order(exchange, side, symbol, amount):
    if not LIVE_TRADING:
        return {"id":"DRY-RUN", "side":side, "symbol":symbol, "amount":amount, "average":None, "filled":amount, "dry_run":True}
    if side == "buy":
        return exchange.create_market_buy_order(symbol, amount)
    return exchange.create_market_sell_order(symbol, amount)


def load_positions():
    """تحميل الصفقات المفتوحة من مجلد /tmp المتاح في Vercel Serverless"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def save_positions(positions):
    """حفظ الصفقات المفتوحة في /tmp"""
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_min_notional(market):
    """استخراج الحد الأدنى لقيمة الصفقة min_notional من بيانات السوق"""
    min_cost = 5.0
    try:
        if 'limits' in market and 'cost' in market['limits'] and market['limits']['cost']['min'] is not None:
            min_cost = float(market['limits']['cost']['min'])
        else:
            filters = market.get('info', {}).get('filters', [])
            for f in filters:
                if f.get('filterType') in ['NOTIONAL', 'MIN_NOTIONAL']:
                    if 'minNotional' in f:
                        min_cost = float(f['minNotional'])
                    elif 'notional' in f:
                        min_cost = float(f['notional'])
                    break
    except Exception:
        pass
    return min_cost


def sanitize_key(key: str) -> str:
    """تنظيف شامل لمفاتيح API من أي مسافات أو أسطر أو علامات اقتباس غير مقصودة"""
    if not key:
        return ""
    # إزالة أي علامات اقتباس محيطة
    cleaned = key.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()
    # إزالة أي مسافات أو محارف مخفية
    return ''.join(c for c in cleaned if c.isprintable() and not c.isspace())


def execute_trade_cycle():
    """تنفيذ دورة فحص ومتاجرة سريعة واحدة (Single Execution Loop)"""
    # 1. قراءة متغيرات البيئة المسجلة في Vercel وتنظيفها بعناية
    raw_api_key = os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_KEY") or ""
    raw_api_secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET") or ""

    api_key = sanitize_key(raw_api_key)
    api_secret = sanitize_key(raw_api_secret)

    symbol = os.environ.get("SYMBOL", "BTC/USDT").strip()
    target_order_usd = float(os.environ.get("TARGET_ORDER_USD", "5.5"))
    max_positions = int(os.environ.get("MAX_POSITIONS", "2"))
    take_profit_pct = float(os.environ.get("TAKE_PROFIT_PCT", "2.0"))
    stop_loss_pct = float(os.environ.get("STOP_LOSS_PCT", "1.0"))
    buy_cooldown_sec = int(os.environ.get("BUY_COOLDOWN_SEC", "180"))

    # إعدادات تتبع السعر اللحظي (Trailing Take Profit)
    trailing_stop_enabled = os.environ.get("TRAILING_STOP_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    trailing_activation_pct = float(os.environ.get("TRAILING_ACTIVATION_PCT", "1.0"))  # نسبة الربح المطلوبة لبدء التتبع اللحظي
    trailing_callback_pct = float(os.environ.get("TRAILING_CALLBACK_PCT", "0.35"))     # نسبة الارتداد من القمة لإغلاق الصفقة وجني الربح

    # معايير منع تجمد العملة واقتناص الحركة السريعة (Anti-Stagnation & Momentum)
    max_hold_time_sec = int(os.environ.get("MAX_HOLD_TIME_SEC", "7200"))               # أقصى مدة بقاء للصفقة الراكدة (ساعتان افتراضياً)
    stagnant_exit_pct = float(os.environ.get("STAGNANT_EXIT_PCT", "0.15"))             # نسبة الربح الأدنى إذا تجاوزت الصفقة وقت الركود
    max_spread_pct = float(os.environ.get("MAX_SPREAD_PCT", "0.15"))                   # أقصى فارق بين العرض والطلب لتجنب العملات المتجمدة
    min_volatility_pct = float(os.environ.get("MIN_VOLATILITY_PCT", "0.15"))           # أدنى نسبة تقلب في آخر 15 دقيقة لضمان حركة حية

    if not api_key or not api_secret:
        raise ValueError(
            "مفاتيح BINANCE_API_KEY و BINANCE_API_SECRET مفقودة أو غير معينة. "
            "يرجى ضبطها في Vercel Environment Variables والتأكد من إعادة النشر (Redeploy)."
        )

    # 2. تهيئة منصة بينانس للتداول الفوري (Spot) عبر مكتبة ccxt
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'adjustForTimeDifference': True
        }
    })

    # تحميل بيانات السوق
    markets = exchange.load_markets()
    if symbol not in markets:
        raise ValueError(f"Symbol {symbol} is not available on Binance Spot")
    market = markets[symbol]
    min_notional = get_min_notional(market)

    # 3. جلب السعر اللحظي ومراقبة الفرق السعري (Spread)
    ticker = exchange.fetch_ticker(symbol)
    current_price = float(ticker['last'])
    bid_price = float(ticker['bid']) if ticker.get('bid') else current_price
    ask_price = float(ticker['ask']) if ticker.get('ask') else current_price
    spread_pct = ((ask_price - bid_price) / current_price) * 100.0 if current_price > 0 else 0.0

    # 4. جلب رصيد المحفظة الحر من USDT و BTC
    balance = exchange.fetch_balance()
    free_usdt = float(balance['free'].get('USDT', 0.0))
    free_btc = float(balance['free'].get('BTC', 0.0))

    actions_taken = []
    positions = load_positions()
    now_ts = datetime.utcnow().timestamp()

    # إذا كان الملف فارغاً ولكن يوجد رصيد BTC في المحفظة، يمكن استنتاج سعر الشراء من آخر صفقة منفذة
    if not positions and free_btc * current_price >= min_notional:
        try:
            my_trades = exchange.fetch_my_trades(symbol, limit=5)
            buy_trades = [t for t in my_trades if t.get('side') == 'buy']
            if buy_trades:
                last_trade = buy_trades[-1]
                positions.append({
                    "id": str(last_trade.get('id', 'inferred')),
                    "symbol": symbol,
                    "amount": min(float(last_trade.get('amount', free_btc)), free_btc),
                    "entry_price": float(last_trade.get('price', current_price)),
                    "highest_price": float(last_trade.get('price', current_price)),
                    "cost": float(last_trade.get('cost', free_btc * current_price)),
                    "timestamp": datetime.utcnow().isoformat(),
                    "created_at_ts": now_ts,
                    "trailing_active": False,
                    "side": "buy"
                })
                save_positions(positions)
        except Exception:
            pass

    # 5. إدارة ومراقبة الصفقات المفتوحة: تتبع السعر اللحظي، جني الأرباح المتحرك، ومعيار فك تجمد العملة
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

        # تفعيل آلية التتبع اللحظي بمجرد تجاوز عتبة الربح المحددة
        if trailing_stop_enabled and peak_gain_pct >= trailing_activation_pct:
            trailing_active = True
            pos['trailing_active'] = True

        # أ) جني أرباح فوري عند الارتفاع السريع العنيف (Hard Take Profit)
        if pnl_pct >= take_profit_pct:
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = create_market_order(exchange, "sell", symbol, sell_amount)
                exec_price = float(order.get('average') or current_price)
                actions_taken.append({
                    "action": "TAKE_PROFIT_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "exit_price": exec_price,
                    "pnl_pct": f"{pnl_pct:+.2f}%",
                    "reason": f"هدف جني الأرباح السريع (+{pnl_pct:.2f}% >= +{take_profit_pct:.2f}%)"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "TAKE_PROFIT_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue

        # ب) جني الأرباح عبر التتبع اللحظي (Trailing Stop): ارتداد السعر عن القمة لحجز أقصى ربح
        elif trailing_active and drop_from_peak_pct >= trailing_callback_pct and pnl_pct >= 0.25:
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = create_market_order(exchange, "sell", symbol, sell_amount)
                exec_price = float(order.get('average') or current_price)
                realized_pnl = ((exec_price - entry_price) / entry_price) * 100.0
                actions_taken.append({
                    "action": "TRAILING_TAKE_PROFIT_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "highest_price": highest_price,
                    "exit_price": exec_price,
                    "drop_from_peak": f"-{drop_from_peak_pct:.2f}%",
                    "realized_pnl_pct": f"{realized_pnl:+.2f}%",
                    "reason": f"حجز الأرباح اللحظية: ارتداد {drop_from_peak_pct:.2f}% من أعلى قمة (${highest_price:,.2f})"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "TRAILING_TP_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue

        # ج) وقف الخسارة الصارم (Stop Loss)
        elif pnl_pct <= -stop_loss_pct:
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = create_market_order(exchange, "sell", symbol, sell_amount)
                exec_price = float(order.get('average') or current_price)
                actions_taken.append({
                    "action": "STOP_LOSS_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "exit_price": exec_price,
                    "pnl_pct": f"{pnl_pct:+.2f}%",
                    "reason": f"حد وقف الخسارة الصارم ({pnl_pct:.2f}% <= -{stop_loss_pct:.2f}%)"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "STOP_LOSS_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue

        # د) معيار عدم تجمد العملة (Anti-Stagnation Release): تحرير رأس المال إذا ركدت العملة طويلاً
        elif max_hold_time_sec > 0 and hold_duration_sec >= max_hold_time_sec and pnl_pct <= stagnant_exit_pct:
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = create_market_order(exchange, "sell", symbol, sell_amount)
                exec_price = float(order.get('average') or current_price)
                held_minutes = int(hold_duration_sec // 60)
                actions_taken.append({
                    "action": "ANTI_STAGNATION_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "exit_price": exec_price,
                    "pnl_pct": f"{pnl_pct:+.2f}%",
                    "held_minutes": held_minutes,
                    "reason": f"معيار منع تجمد العملة: بقاء الصفقة متجمدة لمدة {held_minutes} دقيقة دون زخم كافٍ؛ تم تسييلها لتحرير رأس المال"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "ANTI_STAGNATION_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue

        else:
            # تحديث بيانات المراقبة في الذاكرة
            pos['highest_price'] = highest_price
            pos['trailing_active'] = trailing_active
            pos['current_pnl_pct'] = round(pnl_pct, 2)
            pos['peak_gain_pct'] = round(peak_gain_pct, 2)
            remaining_positions.append(pos)

    positions = remaining_positions
    save_positions(positions)

    # 6. تحديث الرصيد بعد TP/SL
    balance = exchange.fetch_balance()
    free_usdt = float(balance['free'].get('USDT', 0.0))

    # 7. فحص فترة التهدئة لمنع الشراء المتكرر اللحظي
    last_buy_ts = 0.0
    for pos in positions:
        if pos.get("side", "buy") == "buy":
            try:
                last_buy_ts = max(last_buy_ts, float(pos.get("created_at_ts", 0.0)))
            except (TypeError, ValueError):
                pass

    cooldown_ok = (now_ts - last_buy_ts) >= buy_cooldown_sec

    # 8. فحص شروط فتح صفقة جديدة مع معايير عدم التجمد واقتناص الحركة السريعة
    if len(positions) < max_positions and cooldown_ok:
        effective_order_cost = max(target_order_usd, min_notional + 0.15)
        if free_usdt < effective_order_cost:
            actions_taken.append({
                "action": "HOLD",
                "reason": f"Insufficient USDT balance (Required: ${effective_order_cost:.2f}, Available: ${free_usdt:.2f})"
            })
        elif spread_pct > max_spread_pct:
            # معيار حماية: السبريد مرتفع مما يدل على ضعف السيولة أو تجمد دفتر الأوامر
            actions_taken.append({
                "action": "HOLD",
                "reason": f"Anti-Freeze: High spread ({spread_pct:.3f}% > {max_spread_pct:.3f}%). Orderbook lacks instant liquidity."
            })
        else:
            # فحص الزخم اللحظي والتقلب السريع عبر شموع 1m
            volatility_ok = True
            momentum_ok = True
            recent_volatility_pct = 0.0
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1m', limit=15)
                if ohlcv and len(ohlcv) >= 5:
                    highs = [c[2] for c in ohlcv]
                    lows = [c[3] for c in ohlcv]
                    closes = [c[4] for c in ohlcv]
                    min_l = min(lows)
                    max_h = max(highs)
                    recent_volatility_pct = ((max_h - min_l) / min_l) * 100.0 if min_l > 0 else 0.0

                    # 1) معيار الحركة الحية: التأكد من أن العملة ليست متجمدة دون حركة سعرية
                    if recent_volatility_pct < min_volatility_pct:
                        volatility_ok = False

                    # 2) معيار الحركة اللحظية المربحة: التأكد من الزخم الإيجابي اللحظي (فوق متوسط آخر 5 شموع)
                    sma_5 = sum(closes[-5:]) / 5.0
                    if current_price < (sma_5 * 0.9992):
                        momentum_ok = False
            except Exception:
                # في حال تعذر جلب الشموع لا نوقف البوت
                volatility_ok = True
                momentum_ok = True

            if not volatility_ok:
                actions_taken.append({
                    "action": "HOLD",
                    "reason": f"Anti-Stagnation: Low market movement ({recent_volatility_pct:.2f}% < {min_volatility_pct}% 15m range). Currency is stagnant; waiting for active momentum."
                })
            elif not momentum_ok:
                actions_taken.append({
                    "action": "HOLD",
                    "reason": "Momentum Filter: Short-term price is below recent fast average. Waiting for profitable upward momentum."
                })
            else:
                # تنفيذ الشراء اللحظي السريع
                raw_amount = effective_order_cost / ask_price
                buy_amount = float(exchange.amount_to_precision(symbol, raw_amount))
                estimated_cost = buy_amount * ask_price

                if estimated_cost < min_notional:
                    precision_step = market.get('precision', {}).get('amount', 8)
                    buy_amount += 10 ** (-precision_step)
                    buy_amount = float(exchange.amount_to_precision(symbol, buy_amount))

                try:
                    buy_order = create_market_order(exchange, "buy", symbol, buy_amount)
                    filled_price = float(buy_order.get('average', ask_price))
                    filled_qty = float(buy_order.get('filled', buy_amount))
                    total_cost = filled_price * filled_qty

                    new_pos = {
                        "id": buy_order.get('id'),
                        "symbol": symbol,
                        "amount": filled_qty,
                        "entry_price": filled_price,
                        "highest_price": filled_price,
                        "cost": total_cost,
                        "timestamp": datetime.utcnow().isoformat(),
                        "created_at_ts": now_ts,
                        "trailing_active": False,
                        "side": "buy"
                    }
                    positions.append(new_pos)
                    save_positions(positions)

                    actions_taken.append({
                        "action": "MARKET_BUY",
                        "order_id": buy_order.get('id'),
                        "amount": filled_qty,
                        "entry_price": filled_price,
                        "cost": total_cost,
                        "volatility_15m": f"{recent_volatility_pct:.2f}%",
                        "signal": "Momentum & Volatility Confirmed"
                    })
                except Exception as e:
                    actions_taken.append({"action": "BUY_FAILED", "error": str(e)})
    else:
        if not cooldown_ok:
            remaining_cd = int(buy_cooldown_sec - (now_ts - last_buy_ts))
            actions_taken.append({
                "action": "HOLD",
                "reason": f"Buy cooldown active ({max(0, remaining_cd)}s remaining)"
            })
        else:
            actions_taken.append({
                "action": "HOLD",
                "reason": f"Max concurrent positions reached ({len(positions)}/{max_positions})"
            })

    return {
        "status": "success",
        "live_trading": LIVE_TRADING,
        "symbol": symbol,
        "current_price": current_price,
        "usdt_balance": free_usdt,
        "btc_balance": free_btc,
        "min_notional": min_notional,
        "active_positions_count": len(positions),
        "active_positions": positions,
        "action_taken": actions_taken,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


class handler(BaseHTTPRequestHandler):
    """معالج Vercel Serverless Function القياسي بلغة Python"""

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def _handle_request(self):
        try:
            require_trigger_token(self)
            result = execute_trade_cycle()
            response_body = json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as e:
            err_msg = str(e)
            hint = None
            if "-2008" in err_msg or "Invalid Api-Key ID" in err_msg:
                hint = "خطأ -2008: مفتاح Binance API Key غير صحيح أو تم حذفه أو منتهي الصلاحية في حساب بينانس. يرجى إنشاء مفتاح API جديد من Binance وتحديثه في Vercel مع تفعيل صلاحية Spot Trading والتأكد من Unrestricted IP."

            error_data = {
                "status": "error",
                "error_type": type(e).__name__,
                "message": err_msg,
                "hint": hint,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            response_body = json.dumps(error_data, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response_body)
