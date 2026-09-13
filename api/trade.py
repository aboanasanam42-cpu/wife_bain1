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
    take_profit_pct = float(os.environ.get("TAKE_PROFIT_PCT", "1.5"))
    stop_loss_pct = float(os.environ.get("STOP_LOSS_PCT", "1.0"))
    buy_cooldown_sec = int(os.environ.get("BUY_COOLDOWN_SEC", "180"))

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

    # 3. جلب السعر اللحظي (Ticker)
    ticker = exchange.fetch_ticker(symbol)
    current_price = float(ticker['last'])
    ask_price = float(ticker['ask']) if ticker.get('ask') else current_price

    # 4. جلب رصيد المحفظة الحر من USDT و BTC
    balance = exchange.fetch_balance()
    free_usdt = float(balance['free'].get('USDT', 0.0))
    free_btc = float(balance['free'].get('BTC', 0.0))

    actions_taken = []
    positions = load_positions()

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
                    "cost": float(last_trade.get('cost', free_btc * current_price)),
                    "timestamp": datetime.utcnow().isoformat(),
                    "created_at_ts": datetime.utcnow().timestamp(),
                    "side": "buy"
                })
                save_positions(positions)
        except Exception:
            pass

    # 5. فحص شروط جني الأرباح أو وقف الخسارة
    remaining_positions = []
    for i, pos in enumerate(positions, 1):
        entry_price = float(pos['entry_price'])
        amount = float(pos['amount'])
        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0

        if pnl_pct >= take_profit_pct:
            # جني الأرباح (Take Profit)
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = exchange.create_market_sell_order(symbol, sell_amount)
                exec_price = float(order.get('average', current_price))
                actions_taken.append({
                    "action": "TAKE_PROFIT_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "exit_price": exec_price,
                    "pnl_pct": f"{pnl_pct:+.2f}%"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "TAKE_PROFIT_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue

        elif pnl_pct <= -stop_loss_pct:
            # وقف الخسارة (Stop Loss)
            sell_amount = float(exchange.amount_to_precision(symbol, amount))
            try:
                order = exchange.create_market_sell_order(symbol, sell_amount)
                exec_price = float(order.get('average', current_price))
                actions_taken.append({
                    "action": "STOP_LOSS_SELL",
                    "order_id": order.get('id'),
                    "amount": sell_amount,
                    "entry_price": entry_price,
                    "exit_price": exec_price,
                    "pnl_pct": f"{pnl_pct:+.2f}%"
                })
                continue
            except Exception as e:
                actions_taken.append({"action": "STOP_LOSS_FAILED", "error": str(e)})
                remaining_positions.append(pos)
                continue
        else:
            remaining_positions.append(pos)

    positions = remaining_positions
    save_positions(positions)

    # 6. تحديث الرصيد بعد TP/SL؛ لا تعتمد على الرصيد الذي جُلب قبل البيع.
    balance = exchange.fetch_balance()
    free_usdt = float(balance['free'].get('USDT', 0.0))

    # 7. فحص شرط الشراء. في بيئة Serverless لا توجد ذاكرة مضمونة بين الطلبات،
    # لذلك نستخدم وقت آخر شراء المحفوظ في position نفسها كحماية إضافية.
    last_buy_ts = 0.0
    for pos in positions:
        if pos.get("side", "buy") == "buy":
            try:
                last_buy_ts = max(last_buy_ts, float(pos.get("created_at_ts", 0.0)))
            except (TypeError, ValueError):
                pass

    cooldown_ok = (datetime.utcnow().timestamp() - last_buy_ts) >= buy_cooldown_sec

    # 8. فحص شرط الشراء (إذا كان عدد الصفقات أقل من MAX_POSITIONS ويتوفر رصيد USDT كافٍ)
    if len(positions) < max_positions and cooldown_ok:
        effective_order_cost = max(target_order_usd, min_notional + 0.15)
        if free_usdt >= effective_order_cost:
            raw_amount = effective_order_cost / ask_price
            buy_amount = float(exchange.amount_to_precision(symbol, raw_amount))
            estimated_cost = buy_amount * ask_price

            if estimated_cost < min_notional:
                precision_step = market.get('precision', {}).get('amount', 8)
                buy_amount += 10 ** (-precision_step)
                buy_amount = float(exchange.amount_to_precision(symbol, buy_amount))

            try:
                buy_order = exchange.create_market_buy_order(symbol, buy_amount)
                filled_price = float(buy_order.get('average', ask_price))
                filled_qty = float(buy_order.get('filled', buy_amount))
                total_cost = filled_price * filled_qty

                new_pos = {
                    "id": buy_order.get('id'),
                    "symbol": symbol,
                    "amount": filled_qty,
                    "entry_price": filled_price,
                    "cost": total_cost,
                    "timestamp": datetime.utcnow().isoformat(),
                    "created_at_ts": datetime.utcnow().timestamp(),
                    "side": "buy"
                }
                positions.append(new_pos)
                save_positions(positions)

                actions_taken.append({
                    "action": "MARKET_BUY",
                    "order_id": buy_order.get('id'),
                    "amount": filled_qty,
                    "entry_price": filled_price,
                    "cost": total_cost
                })
            except Exception as e:
                actions_taken.append({"action": "BUY_FAILED", "error": str(e)})
        else:
            actions_taken.append({
                "action": "HOLD",
                "reason": f"Insufficient USDT balance (Required: ${effective_order_cost:.2f}, Available: ${free_usdt:.2f})"
            })
    else:
        if not cooldown_ok:
            remaining_cd = int(buy_cooldown_sec - (datetime.utcnow().timestamp() - last_buy_ts))
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
