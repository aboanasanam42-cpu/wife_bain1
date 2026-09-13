#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vercel Serverless Binance Spot trader: buy confirmed BTC/USDT dips and trail the high."""
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
CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()
LIVE_TRADING = os.environ.get("LIVE_TRADING", "false").strip().lower() in ("true", "1", "yes")


def require_trigger_token(handler):
    """Accept the manual trade token or Vercel Cron's CRON_SECRET."""
    auth = handler.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else handler.headers.get("X-Trade-Token", "").strip()
    if (TRADE_TRIGGER_TOKEN and token == TRADE_TRIGGER_TOKEN) or (CRON_SECRET and token == CRON_SECRET):
        return
    raise PermissionError("Unauthorized trade trigger")


def create_market_order(exchange, side, symbol, amount):
    if not LIVE_TRADING:
        return {"id": "DRY-RUN", "side": side, "symbol": symbol, "amount": amount,
                "average": None, "filled": amount, "dry_run": True}
    if side == "buy":
        return exchange.create_market_buy_order(symbol, amount)
    return exchange.create_market_sell_order(symbol, amount)


def load_positions():
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def save_positions(positions):
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_min_notional(market):
    min_cost = 5.0
    try:
        cost = market.get("limits", {}).get("cost", {}).get("min")
        if cost is not None:
            return float(cost)
        for f in market.get("info", {}).get("filters", []):
            if f.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL"):
                value = f.get("minNotional", f.get("notional"))
                if value is not None:
                    min_cost = float(value)
                    break
    except Exception:
        pass
    return min_cost


def sanitize_key(key):
    if not key:
        return ""
    cleaned = key.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return "".join(c for c in cleaned if c.isprintable() and not c.isspace())


def sell_position(exchange, symbol, pos, reason, current_price, actions):
    amount = float(pos["amount"])
    sell_amount = float(exchange.amount_to_precision(symbol, amount))
    if sell_amount <= 0:
        actions.append({"action": "SELL_SKIPPED", "reason": "Calculated sell amount is zero"})
        return False
    try:
        order = create_market_order(exchange, "sell", symbol, sell_amount)
        exec_price = float(order.get("average") or current_price)
        entry = float(pos["entry_price"])
        pnl = ((exec_price - entry) / entry) * 100.0 if entry else 0.0
        actions.append({
            "action": "MARKET_SELL",
            "order_id": order.get("id"),
            "amount": sell_amount,
            "entry_price": entry,
            "highest_price": float(pos.get("highest_price", entry)),
            "exit_price": exec_price,
            "pnl_pct": f"{pnl:+.3f}%",
            "reason": reason,
            "dry_run": bool(order.get("dry_run", False))
        })
        return True
    except Exception as exc:
        actions.append({"action": "SELL_FAILED", "error": str(exc), "reason": reason})
        return False


def execute_trade_cycle():
    raw_key = os.environ.get("BINANCE_API_KEY") or os.environ.get("BINANCE_KEY") or ""
    raw_secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET") or ""
    api_key, api_secret = sanitize_key(raw_key), sanitize_key(raw_secret)
    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY و BINANCE_API_SECRET مطلوبان في Vercel Environment Variables")

    symbol = os.environ.get("SYMBOL", "BTC/USDT").strip()
    target_order_usd = float(os.environ.get("TARGET_ORDER_USD", "5.5"))
    max_positions = max(1, int(os.environ.get("MAX_POSITIONS", "1")))
    buy_cooldown_sec = max(0, int(os.environ.get("BUY_COOLDOWN_SEC", "30")))

    # Entry: do not catch a falling knife. Buy only after a measurable dip AND rebound confirmation.
    buy_dip_min_pct = max(0.0, float(os.environ.get("BUY_DIP_MIN_PCT", "0.25")))
    buy_rebound_confirm_pct = max(0.0, float(os.environ.get("BUY_REBOUND_CONFIRM_PCT", "0.08")))
    buy_rsi_max = float(os.environ.get("BUY_RSI_MAX", "48"))
    min_volatility_pct = max(0.0, float(os.environ.get("MIN_VOLATILITY_PCT", "0.20")))
    max_spread_pct = max(0.0, float(os.environ.get("MAX_SPREAD_PCT", "0.15")))

    # Exit: trail the highest price after a small profit; emergency exit prevents capital lock-up.
    trailing_enabled = os.environ.get("TRAILING_STOP_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    trailing_activation_pct = max(0.0, float(os.environ.get("TRAILING_ACTIVATION_PCT", "0.15")))
    trailing_callback_pct = max(0.0, float(os.environ.get("TRAILING_CALLBACK_PCT", "0.20")))
    stop_loss_pct = max(0.01, float(os.environ.get("STOP_LOSS_PCT", "0.40")))
    max_hold_time_sec = max(0, int(os.environ.get("MAX_HOLD_TIME_SEC", "1200")))
    stagnant_exit_pct = float(os.environ.get("STAGNANT_EXIT_PCT", "0.00"))

    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot", "adjustForTimeDifference": True}
    })
    markets = exchange.load_markets()
    if symbol not in markets:
        raise ValueError(f"{symbol} is not available on Binance Spot")
    market = markets[symbol]
    min_notional = get_min_notional(market)

    ticker = exchange.fetch_ticker(symbol)
    current_price = float(ticker["last"])
    bid = float(ticker.get("bid") or current_price)
    ask = float(ticker.get("ask") or current_price)
    spread_pct = ((ask - bid) / current_price) * 100.0 if current_price else 0.0

    balance = exchange.fetch_balance()
    free_usdt = float(balance.get("free", {}).get("USDT", 0.0))
    free_btc = float(balance.get("free", {}).get("BTC", 0.0))
    positions = load_positions()
    now_ts = datetime.utcnow().timestamp()
    actions = []

    # Manage existing BTC first. This always has priority over opening another position.
    remaining = []
    for pos in positions:
        entry = float(pos["entry_price"])
        amount = float(pos["amount"])
        highest = max(float(pos.get("highest_price", entry)), current_price)
        pos["highest_price"] = highest
        pnl_pct = ((current_price - entry) / entry) * 100.0 if entry else 0.0
        peak_gain_pct = ((highest - entry) / entry) * 100.0 if entry else 0.0
        drop_from_peak_pct = ((highest - current_price) / highest) * 100.0 if highest else 0.0
        age = now_ts - float(pos.get("created_at_ts", now_ts))
        trailing_active = bool(pos.get("trailing_active", False))

        if trailing_enabled and peak_gain_pct >= trailing_activation_pct:
            trailing_active = True
        pos["trailing_active"] = trailing_active
        pos["current_pnl_pct"] = round(pnl_pct, 4)
        pos["peak_gain_pct"] = round(peak_gain_pct, 4)

        # No hard take-profit: let the high-water mark capture the move, then exit on reversal.
        exit_reason = None
        if trailing_active and drop_from_peak_pct >= trailing_callback_pct:
            exit_reason = f"Trailing reversal: -{drop_from_peak_pct:.3f}% from high ${highest:,.2f}"
        elif pnl_pct <= -stop_loss_pct:
            exit_reason = f"Emergency stop: {pnl_pct:.3f}%"
        elif max_hold_time_sec and age >= max_hold_time_sec and pnl_pct <= stagnant_exit_pct:
            exit_reason = f"Capital release after {int(age // 60)} minutes"

        if exit_reason and sell_position(exchange, symbol, pos, exit_reason, current_price, actions):
            continue
        remaining.append(pos)

    positions = remaining
    save_positions(positions)

    # Refresh balances after any sale.
    balance = exchange.fetch_balance()
    free_usdt = float(balance.get("free", {}).get("USDT", 0.0))
    free_btc = float(balance.get("free", {}).get("BTC", 0.0))

    # Find the most recent buy timestamp to prevent immediate re-entry after a sale.
    last_buy_ts = max((float(p.get("created_at_ts", 0.0)) for p in positions), default=0.0)
    cooldown_ok = (now_ts - last_buy_ts) >= buy_cooldown_sec

    if len(positions) < max_positions and cooldown_ok:
        order_cost = max(target_order_usd, min_notional + 0.10)
        if free_usdt < order_cost:
            actions.append({"action": "HOLD", "reason": f"USDT insufficient: need {order_cost:.2f}, have {free_usdt:.2f}"})
        elif spread_pct > max_spread_pct:
            actions.append({"action": "HOLD", "reason": f"Spread too high: {spread_pct:.3f}%"})
        else:
            # 1-minute microstructure: local high -> drop -> local low -> confirmed rebound.
            candles = exchange.fetch_ohlcv(symbol, timeframe="1m", limit=21)
            if len(candles) >= 15:
                highs = [float(c[2]) for c in candles]
                lows = [float(c[3]) for c in candles]
                closes = [float(c[4]) for c in candles]
                window_high = max(highs[:-2])
                window_low = min(lows[-4:])
                dip_pct = ((window_high - window_low) / window_high) * 100.0 if window_high else 0.0
                rebound_pct = ((current_price - window_low) / window_low) * 100.0 if window_low else 0.0
                volatility_pct = ((max(highs[-15:]) - min(lows[-15:])) / min(lows[-15:])) * 100.0 if min(lows[-15:]) else 0.0

                gains, losses = [], []
                for a, b in zip(closes[-15:-1], closes[-14:]):
                    d = b - a
                    gains.append(max(d, 0.0))
                    losses.append(max(-d, 0.0))
                avg_gain = sum(gains) / max(1, len(gains))
                avg_loss = sum(losses) / max(1, len(losses))
                rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
                rebound_confirmed = current_price > closes[-2] and rebound_pct >= buy_rebound_confirm_pct
                dip_confirmed = dip_pct >= buy_dip_min_pct

                if volatility_pct < min_volatility_pct:
                    actions.append({"action": "HOLD", "reason": f"Low volatility: {volatility_pct:.3f}%"})
                elif not dip_confirmed:
                    actions.append({"action": "HOLD", "reason": f"No dip yet: {dip_pct:.3f}% < {buy_dip_min_pct:.3f}%"})
                elif not rebound_confirmed:
                    actions.append({"action": "HOLD", "reason": f"Waiting for rebound: {rebound_pct:.3f}%"})
                elif rsi > buy_rsi_max:
                    actions.append({"action": "HOLD", "reason": f"Rebound already extended: RSI {rsi:.1f} > {buy_rsi_max:.1f}"})
                else:
                    raw_amount = order_cost / ask
                    buy_amount = float(exchange.amount_to_precision(symbol, raw_amount))
                    estimated_cost = buy_amount * ask
                    if estimated_cost < min_notional:
                        raise ValueError(f"Order amount {estimated_cost:.4f} is below Binance min notional {min_notional:.4f}")
                    try:
                        order = create_market_order(exchange, "buy", symbol, buy_amount)
                        filled = float(order.get("filled") or buy_amount)
                        entry_price = float(order.get("average") or ask)
                        positions.append({
                            "id": order.get("id"), "symbol": symbol, "amount": filled,
                            "entry_price": entry_price, "highest_price": entry_price,
                            "cost": entry_price * filled, "timestamp": datetime.utcnow().isoformat(),
                            "created_at_ts": now_ts, "trailing_active": False, "side": "buy"
                        })
                        save_positions(positions)
                        actions.append({
                            "action": "MARKET_BUY", "order_id": order.get("id"),
                            "entry_price": entry_price, "amount": filled,
                            "dip_pct": round(dip_pct, 3), "rebound_pct": round(rebound_pct, 3),
                            "rsi": round(rsi, 2), "volatility_15m": round(volatility_pct, 3),
                            "signal": "DIP + REBOUND CONFIRMED", "dry_run": bool(order.get("dry_run", False))
                        })
                    except Exception as exc:
                        actions.append({"action": "BUY_FAILED", "error": str(exc)})
            else:
                actions.append({"action": "HOLD", "reason": "Insufficient 1m candle history"})
    else:
        actions.append({"action": "HOLD", "reason": "Open position or buy cooldown active"})

    return {
        "status": "success", "live_trading": LIVE_TRADING, "symbol": symbol,
        "current_price": current_price, "usdt_balance": free_usdt, "btc_balance": free_btc,
        "min_notional": min_notional, "active_positions_count": len(positions),
        "active_positions": positions, "action_taken": actions,
        "strategy": "BUY_DIP_REBOUND + HIGH_WATER_TRAILING + EMERGENCY_EXIT",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Trade-Token")
        self.end_headers()

    def _handle_request(self):
        try:
            require_trigger_token(self)
            result = execute_trade_cycle()
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({
                "status": "error", "error_type": type(exc).__name__, "message": str(exc),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
