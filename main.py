"""
Binance Spot 24/7 Scalper Trading Bot - Production Main Runner
Autonomous real-time spot trading with Dip & Rebound Entry, Trailing Stop-Loss,
zero-freeze error recovery, and embedded Railway health check dashboard.
"""

import html
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple

from config import Config, mask_key
import indicators
from spot_engine import SpotScalperEngine

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BinanceSpotScalper")

# Global status dictionary for Web Dashboard & Railway Healthchecks
BOT_STATUS: Dict[str, Any] = {
    "status": "INITIALIZING",
    "strategy": "Binance Spot Real-Time Scalper (Dip & Rebound + Trailing TP)",
    "symbol": Config.get_spot_symbol(),
    "raw_symbol": Config.get_binance_raw_symbol(),
    "live_trading": Config.LIVE_TRADING,
    "current_price": 0.0,
    "price_change_24h": 0.0,
    "rsi": 50.0,
    "dip_pct": 0.0,
    "rebound_pct": 0.0,
    "volatility_pct": 0.0,
    "spread_pct": 0.0,
    "entry_signals": {
        "dip_satisfied": False,
        "rebound_satisfied": False,
        "rsi_satisfied": False,
        "spread_satisfied": False,
        "can_buy": False,
        "reason": "Initializing...",
    },
    "has_position": False,
    "position": None,
    "total_realized_pnl_usd": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "win_rate_pct": 0.0,
    "recent_trades": [],
    "external_ip": "Detecting...",
    "error_diagnostic": None,
    "last_loop_time": None,
    "base_asset": Config.get_base_quote()[0],
    "quote_asset": Config.get_base_quote()[1],
    "wallet_balances": {"quote_free": 0.0, "base_free": 0.0},
}

shutdown_event = threading.Event()


def get_public_ip() -> str:
    """Detects outbound IP address to verify server region and for Binance API whitelisting."""
    providers = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://checkip.amazonaws.com",
    ]
    for url in providers:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return "UNKNOWN_IP"


class DashboardHealthHandler(BaseHTTPRequestHandler):
    """
    Non-blocking HTTP daemon server providing:
    - /health (Railway healthcheck endpoint returning 200 OK)
    - /api/status (JSON feed for monitoring)
    - / (Modern responsive HTML dashboard in Arabic and English)
    """

    def log_message(self, format, *args):
        # Suppress spammy request logs
        return

    def do_GET(self):
        if self.path in ("/health", "/ping"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            payload = {
                "status": "healthy",
                "bot": BOT_STATUS["status"],
                "live_trading": BOT_STATUS["live_trading"],
                "symbol": BOT_STATUS["symbol"],
                "current_price": BOT_STATUS["current_price"],
                "realized_pnl_usd": BOT_STATUS["total_realized_pnl_usd"],
                "trades": BOT_STATUS["total_trades"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(BOT_STATUS, default=str).encode("utf-8"))
            return

        # Render HTML Dashboard
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html_page = self.render_html_dashboard()
        self.wfile.write(html_page.encode("utf-8"))

    def render_html_dashboard(self) -> str:
        s = BOT_STATUS
        mode_badge = (
            '<span class="badge live">🟢 تداول حقيقي (LIVE SPOT)</span>'
            if s["live_trading"]
            else '<span class="badge sim">🟡 محاكاة (DRY RUN / SIMULATION)</span>'
        )

        diag_box = ""
        if s.get("error_diagnostic"):
            diag_box = f"""
            <div class="alert alert-error">
                <strong>⚠️ تنبيه فني:</strong> {html.escape(str(s['error_diagnostic']))}
            </div>
            """

        pos = s.get("position")
        if pos:
            pnl_cls = "text-green" if pos.get("unrealized_pnl_pct", 0) >= 0 else "text-red"
            trailing_badge = (
                '<span class="tag tag-active">مفعل (Trailing Active)</span>'
                if pos.get("trailing_active")
                else '<span class="tag tag-waiting">قيد الانتظار</span>'
            )
            position_card = f"""
            <div class="card active-pos-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="color:var(--yellow); font-size:1.1rem;">⚡ صفقة فورية نشطة ({pos.get('symbol')})</h3>
                    <div>{trailing_badge}</div>
                </div>
                <div class="grid-stats" style="margin-top:14px; margin-bottom:0;">
                    <div>
                        <div class="card-label">سعر الدخول (Entry Price)</div>
                        <div class="card-value font-mono">${pos.get('entry_price', 0):,.2f}</div>
                    </div>
                    <div>
                        <div class="card-label">الربح غير المحقق (Unrealized PnL)</div>
                        <div class="card-value font-mono {pnl_cls}">{pos.get('unrealized_pnl_pct', 0):+.2f}% (${pos.get('unrealized_pnl_usd', 0):+.4f})</div>
                    </div>
                    <div>
                        <div class="card-label">أعلى سعر تم بلوغه (Peak High)</div>
                        <div class="card-value font-mono text-blue">${pos.get('highest_price', 0):,.2f}</div>
                    </div>
                    <div>
                        <div class="card-label">وقف الربح المتحرك (Trailing Stop)</div>
                        <div class="card-value font-mono text-yellow">${pos.get('trailing_stop_price', 0):,.2f}</div>
                    </div>
                </div>
                <div style="margin-top:12px; font-size:0.85rem; color:var(--muted);">
                    الكمية: <strong>{pos.get('qty')} {s.get('base_asset')}</strong> | القيمة: <strong>${pos.get('cost_usd', 0):,.2f} USDT</strong> | مدة الاحتفاظ: <strong>{pos.get('hold_time_seconds', 0)} ثانية</strong>
                </div>
            </div>
            """
        else:
            sig = s.get("entry_signals", {})
            position_card = f"""
            <div class="card" style="border-left: 4px solid var(--blue);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <h3 style="font-size:1rem; color:var(--text);">🎯 حالة رادار الدخول الفوري اللحظي (Entry Signals)</h3>
                    <span style="font-size:0.8rem; color:var(--muted);">{sig.get('reason', 'Searching')}</span>
                </div>
                <div style="display:flex; gap:12px; flex-wrap:wrap; font-size:0.85rem;">
                    <span class="signal-tag {'tag-ok' if sig.get('dip_satisfied') else 'tag-wait'}">
                        الهبوط: {s.get('dip_pct', 0):.2f}% (الهدف: ≥{Config.BUY_DIP_MIN_PCT}%)
                    </span>
                    <span class="signal-tag {'tag-ok' if sig.get('rebound_satisfied') else 'tag-wait'}">
                        الارتداد: {s.get('rebound_pct', 0):.2f}% (الهدف: ≥{Config.BUY_REBOUND_CONFIRM_PCT}%)
                    </span>
                    <span class="signal-tag {'tag-ok' if sig.get('rsi_satisfied') else 'tag-wait'}">
                        مؤشر RSI: {s.get('rsi', 0):.1f} (الهدف: ≤{Config.BUY_RSI_MAX})
                    </span>
                    <span class="signal-tag {'tag-ok' if sig.get('spread_satisfied') else 'tag-wait'}">
                        الفارق: {s.get('spread_pct', 0):.3f}%
                    </span>
                </div>
            </div>
            """

        trades_rows = ""
        for t in s.get("recent_trades", []):
            pnl_val = t.get("pnl_usd", 0.0)
            pnl_cls = "text-green" if pnl_val >= 0 else "text-red"
            trades_rows += f"""
            <tr>
                <td class="font-mono">${t.get('entry_price', 0):,.2f}</td>
                <td class="font-mono">${t.get('exit_price', 0):,.2f}</td>
                <td class="font-mono">{t.get('qty')}</td>
                <td class="font-mono font-bold {pnl_cls}">{t.get('pnl_pct', 0):+.2f}% (${pnl_val:+.4f})</td>
                <td style="font-size:0.8rem; color:var(--muted);">{html.escape(t.get('exit_reason', ''))}</td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>بينانس سبوت - بوت التداول الفوري اللحظي 24/7</title>
    <meta http-equiv="refresh" content="4">
    <style>
        :root {{
            --bg: #0b0e14;
            --surface: #141923;
            --border: #232c3d;
            --text: #f0f3f8;
            --muted: #8b99ad;
            --green: #0ecb81;
            --red: #f6465d;
            --yellow: #f0b90b;
            --blue: #2979ff;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        body {{ background: var(--bg); color: var(--text); padding: 18px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }}
        .title-group h1 {{ font-size: 1.4rem; display: flex; align-items: center; gap: 8px; }}
        .badge {{ font-size: 0.8rem; padding: 4px 10px; border-radius: 999px; font-weight: 700; }}
        .badge.live {{ background: rgba(14, 203, 129, 0.15); color: var(--green); border: 1px solid var(--green); }}
        .badge.sim {{ background: rgba(240, 185, 11, 0.15); color: var(--yellow); border: 1px solid var(--yellow); }}
        .grid-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-bottom: 20px; }}
        .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
        .active-pos-card {{ border: 1px solid var(--yellow); background: rgba(240, 185, 11, 0.04); }}
        .card-label {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 5px; }}
        .card-value {{ font-size: 1.5rem; font-weight: 700; }}
        .text-green {{ color: var(--green); }}
        .text-red {{ color: var(--red); }}
        .text-yellow {{ color: var(--yellow); }}
        .text-blue {{ color: var(--blue); }}
        .font-mono {{ font-family: 'SFMono-Regular', Consolas, monospace; direction: ltr; display: inline-block; }}
        .alert {{ padding: 12px 16px; border-radius: 8px; margin-bottom: 18px; font-size: 0.9rem; }}
        .alert-error {{ background: rgba(246, 70, 93, 0.15); border: 1px solid var(--red); color: #ff8b99; }}
        .signal-tag {{ padding: 5px 10px; border-radius: 6px; font-size: 0.82rem; }}
        .signal-tag.tag-ok {{ background: rgba(14, 203, 129, 0.18); color: var(--green); border: 1px solid var(--green); }}
        .signal-tag.tag-wait {{ background: rgba(139, 153, 173, 0.12); color: var(--muted); border: 1px solid var(--border); }}
        .tag {{ padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }}
        .tag.tag-active {{ background: rgba(14, 203, 129, 0.2); color: var(--green); }}
        .tag.tag-waiting {{ background: rgba(139, 153, 173, 0.15); color: var(--muted); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 10px 12px; text-align: right; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
        th {{ color: var(--muted); font-size: 0.75rem; font-weight: 600; }}
        footer {{ margin-top: 25px; text-align: center; color: var(--muted); font-size: 0.8rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-group">
                <h1>⚡ بوت التداول الفوري اللحظي (Binance Spot Scalper)</h1>
                <p style="color: var(--muted); font-size: 0.85rem; margin-top: 3px;">تداول العقود الفورية لحظياً دون تجميد أو توقف 24/7 على Railway</p>
            </div>
            <div>{mode_badge}</div>
        </header>

        {diag_box}

        <div class="grid-stats">
            <div class="card">
                <div class="card-label">سعر السوق الفوري ({s.get('symbol')})</div>
                <div class="card-value font-mono text-yellow">${s.get('current_price', 0.0):,.2f}</div>
                <div style="font-size: 0.78rem; margin-top: 4px; color: var(--muted);">تغير 24 ساعة: {s.get('price_change_24h', 0.0):+.2f}%</div>
            </div>
            <div class="card">
                <div class="card-label">صافي الربح المحقق (Realized PnL)</div>
                <div class="card-value font-mono text-green">{s.get('total_realized_pnl_usd', 0.0):+.4f} USDT</div>
                <div style="font-size: 0.78rem; margin-top: 4px; color: var(--muted);">عدد الصفقات: {s.get('total_trades', 0)} (نسبة النجاح: {s.get('win_rate_pct', 0.0)}%)</div>
            </div>
            <div class="card">
                <div class="card-label">حجم الصفقة المستهدف (Order Size)</div>
                <div class="card-value font-mono text-blue">${Config.TARGET_ORDER_USD:,.2f} USDT</div>
                <div style="font-size: 0.78rem; margin-top: 4px; color: var(--muted);">تحديث كل {Config.LOOP_INTERVAL_SEC} ثواني</div>
            </div>
            <div class="card">
                <div class="card-label">حالة المحرك (Engine Status)</div>
                <div class="card-value font-mono" style="font-size: 1.25rem;">{s.get('status')}</div>
                <div style="font-size: 0.78rem; margin-top: 4px; color: var(--muted);">IP السيرفر: {s.get('external_ip')}</div>
            </div>
        </div>

        <div style="margin-bottom: 20px;">
            {position_card}
        </div>

        <div class="card">
            <h3 style="font-size: 1rem; margin-bottom: 10px;">📜 سجل الصفقات المغلقة مؤخراً (Recent Executions)</h3>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>سعر الدخول</th>
                            <th>سعر الخروج</th>
                            <th>الكمية</th>
                            <th>صافي الربح</th>
                            <th>سبب الإغلاق</th>
                        </tr>
                    </thead>
                    <tbody>
                        {trades_rows or '<tr><td colspan="5" style="text-align: center; color: var(--muted);">لا توجد صفقات منفذة حتى الآن. الرادار يراقب الفرص اللحظية...</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>

        <footer>
            Binance Spot Engine v2.0 | المنفذ: <code>{Config.PORT}</code> | رابط الفحص: <code>/health</code> | متصل ومستقر على مدار الساعة 24/7
        </footer>
    </div>
</body>
</html>
"""


def start_health_server(port: int):
    """Starts the background HTTP daemon for Railway."""
    try:
        server = HTTPServer(("0.0.0.0", port), DashboardHealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"🌐 Web Dashboard & Railway health endpoint live on http://0.0.0.0:{port}")
    except Exception as e:
        logger.error(f"Failed to start HTTP server on port {port}: {e}")


class PublicBinanceFallback:
    """
    Fallback public API client used when CCXT is absent or during dry-run simulation.
    Fetches real-time Binance Spot tickers, orderbook depth, and klines directly via REST.
    """

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        raw = symbol.replace("/", "").replace("-", "").replace("_", "")
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={raw}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "last": float(data.get("lastPrice", 0.0)),
                "bid": float(data.get("bidPrice", 0.0)),
                "ask": float(data.get("askPrice", 0.0)),
                "percentage": float(data.get("priceChangePercent", 0.0)),
            }

    def fetch_ohlcv(self, symbol: str, timeframe="1m", limit=30) -> List[List[float]]:
        raw = symbol.replace("/", "").replace("-", "").replace("_", "")
        url = f"https://api.binance.com/api/v3/klines?symbol={raw}&interval={timeframe}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Format: [open_time, open, high, low, close, volume]
            return [[d[0], float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5])] for d in data]


def init_exchange():
    """Initializes CCXT Binance Spot instance with robust options."""
    try:
        import ccxt
    except ImportError:
        logger.warning("CCXT not installed locally. Using Binance REST Client for market data.")
        return PublicBinanceFallback()

    exchange_config = {
        "apiKey": Config.API_KEY,
        "secret": Config.API_SECRET,
        "enableRateLimit": True,
        "timeout": 10000,
        "options": {
            "defaultType": "spot",  # Strictly Binance Spot (api.binance.com)
            "adjustForTimeDifference": True,
            "recvWindow": 10000,
        },
    }

    if Config.BINANCE_PROXY:
        exchange_config["proxies"] = {
            "http": Config.BINANCE_PROXY,
            "https": Config.BINANCE_PROXY,
        }
        logger.info(f"Using outbound proxy for Binance API: {Config.BINANCE_PROXY}")

    exchange = ccxt.binance(exchange_config)

    if Config.TESTNET:
        exchange.set_sandbox_mode(True)
        logger.info("Connecting to Binance Spot Testnet.")

    return exchange


def configure_spot_filters(exchange, symbol: str, engine: SpotScalperEngine):
    """Queries exchange markets and sets precision, LOT_SIZE, and MIN_NOTIONAL limits."""
    if isinstance(exchange, PublicBinanceFallback):
        # Set standard defaults for BTC/USDT if in fallback mode
        engine.set_market_filters(2, 5, 0.01, 0.00001, 0.00001, 5.0)
        return

    logger.info(f"Fetching Binance Spot market filters for {symbol}...")
    markets = exchange.load_markets()

    target_market = None
    for s, m in markets.items():
        if s == symbol or m.get("id") == Config.get_binance_raw_symbol():
            target_market = m
            break

    if not target_market:
        available = [k for k in markets.keys() if "USDT" in k][:6]
        raise ValueError(f"Spot pair '{symbol}' not found on Binance! Examples: {available}")

    price_precision = target_market.get("precision", {}).get("price", 2)
    amount_precision = target_market.get("precision", {}).get("amount", 5)

    limits = target_market.get("limits", {})
    min_qty = limits.get("amount", {}).get("min", 0.00001)
    min_notional = limits.get("cost", {}).get("min", 5.0)

    tick_size = 0.0
    step_size = 0.0
    for f in target_market.get("info", {}).get("filters", []):
        f_type = f.get("filterType")
        if f_type == "PRICE_FILTER":
            tick_size = float(f.get("tickSize", 0.0))
        elif f_type == "LOT_SIZE":
            step_size = float(f.get("stepSize", 0.0))
            min_qty = max(min_qty, float(f.get("minQty", min_qty)))
        elif f_type == "NOTIONAL":
            min_notional = max(min_notional, float(f.get("minNotional", min_notional)))
        elif f_type == "MIN_NOTIONAL":
            min_notional = max(min_notional, float(f.get("minNotional", min_notional)))

    engine.set_market_filters(
        price_precision=int(price_precision) if price_precision is not None else 2,
        amount_precision=int(amount_precision) if amount_precision is not None else 5,
        tick_size=tick_size,
        step_size=step_size,
        min_qty=float(min_qty),
        min_notional=float(min_notional),
    )


def execute_spot_buy(exchange, symbol: str, qty: float, price: float) -> Tuple[bool, Optional[str]]:
    """Executes a real Spot BUY order on Binance."""
    try:
        order = exchange.create_market_buy_order(symbol, qty)
        order_id = str(order.get("id"))
        logger.info(f"Successfully placed Spot Market BUY: {symbol} Qty: {qty} (ID: {order_id})")
        return True, order_id
    except Exception as e:
        logger.error(f"Failed to execute Spot BUY: {e}")
        BOT_STATUS["error_diagnostic"] = f"Failed BUY order: {e}"
        return False, None


def execute_spot_sell(exchange, symbol: str, qty: float, price: float) -> Tuple[bool, float]:
    """
    Executes a real Spot SELL order on Binance.
    Queries actual wallet balance to prevent insufficient balance failures.
    """
    try:
        base, _ = Config.get_base_quote()
        # Query free balance to guarantee sufficient coins after fees
        balance = exchange.fetch_balance()
        free_base = float(balance.get(base, {}).get("free", 0.0))

        actual_qty = min(qty, free_base)
        # Apply step size
        actual_qty = float(f"{actual_qty:.5f}")

        if actual_qty <= 0:
            logger.error(f"Cannot sell: free balance of {base} is 0 or less than step size.")
            return False, 0.0

        order = exchange.create_market_sell_order(symbol, actual_qty)
        logger.info(f"Successfully placed Spot Market SELL: {symbol} Qty: {actual_qty}")
        return True, actual_qty
    except Exception as e:
        logger.error(f"Failed to execute Spot SELL: {e}")
        BOT_STATUS["error_diagnostic"] = f"Failed SELL order: {e}"
        return False, 0.0


def run_spot_bot():
    """Main continuous execution loop for the 24/7 Binance Spot Scalper."""
    logger.info("=" * 65)
    logger.info("🚀 Starting Binance Spot 24/7 Scalper Trading Bot")
    logger.info(f"Symbol: {Config.get_spot_symbol()} (Raw: {Config.get_binance_raw_symbol()})")
    logger.info(f"Execution Mode: {'🔴 LIVE TRADING (REAL FUNDS)' if Config.LIVE_TRADING else '🟡 SIMULATION (DRY RUN)'}")
    logger.info(f"Target Order Size: ${Config.TARGET_ORDER_USD:.2f} USDT")
    logger.info(f"Trailing TP: {Config.TRAILING_ACTIVATION_PCT}% activation, {Config.TRAILING_CALLBACK_PCT}% callback")
    logger.info(f"Hard Stop-Loss: -{Config.STOP_LOSS_PCT}% | Loop Interval: {Config.LOOP_INTERVAL_SEC}s")
    logger.info("=" * 65)

    # 1. Start HTTP server immediately
    start_health_server(Config.PORT)

    # 2. Detect external IP
    ext_ip = get_public_ip()
    BOT_STATUS["external_ip"] = ext_ip
    logger.info(f"Outbound Server IP: {ext_ip}")

    # 3. Instantiate Spot Scalper Engine
    engine = SpotScalperEngine(
        symbol=Config.get_spot_symbol(),
        target_order_usd=Config.TARGET_ORDER_USD,
        trailing_enabled=Config.TRAILING_STOP_ENABLED,
        trailing_activation_pct=Config.TRAILING_ACTIVATION_PCT,
        trailing_callback_pct=Config.TRAILING_CALLBACK_PCT,
        stop_loss_pct=Config.STOP_LOSS_PCT,
        max_hold_time_sec=Config.MAX_HOLD_TIME_SEC,
        stagnant_exit_pct=Config.STAGNANT_EXIT_PCT,
        buy_cooldown_sec=Config.BUY_COOLDOWN_SEC,
        state_file=Config.STATE_FILE,
    )

    symbol = Config.get_spot_symbol()
    exchange = None

    # 4. Connect to Exchange with auto-reconnect
    while not shutdown_event.is_set():
        try:
            exchange = init_exchange()
            configure_spot_filters(exchange, symbol, engine)
            BOT_STATUS["status"] = "RUNNING (24/7)"
            BOT_STATUS["error_diagnostic"] = None
            break
        except Exception as e:
            err_str = str(e)
            logger.error(f"Error connecting to Binance: {err_str}")
            BOT_STATUS["status"] = "RETRYING_CONNECTION"

            if "-2008" in err_str or "Invalid Api-Key" in err_str:
                diag = (
                    "Binance Spot API Key rejected (-2008). "
                    "1) Ensure BINANCE_API_KEY and BINANCE_API_SECRET in Railway Variables are correct. "
                    "2) Check 'Enable Reading' and 'Enable Spot & Margin Trading' in Binance API Management. "
                    f"3) If IP restriction is active, whitelist server IP: {ext_ip}"
                )
                BOT_STATUS["error_diagnostic"] = diag
            elif "451" in err_str:
                diag = "Binance Geo-restriction (451). Deploy your Railway service in EU West (Amsterdam) or set BINANCE_PROXY."
                BOT_STATUS["error_diagnostic"] = diag
            else:
                BOT_STATUS["error_diagnostic"] = err_str

            time.sleep(10)

    # 5. Continuous 24/7 Real-Time Loop
    logger.info("Entering 24/7 real-time Spot scalping loop...")
    while not shutdown_event.is_set():
        try:
            loop_start = time.time()

            # A. Fetch Real-time Market Data (Ticker & Orderbook)
            ticker = exchange.fetch_ticker(symbol)
            current_price = float(ticker.get("last") or 0.0)
            bid_price = float(ticker.get("bid") or current_price)
            ask_price = float(ticker.get("ask") or current_price)
            price_change = float(ticker.get("percentage") or 0.0)

            if current_price <= 0:
                time.sleep(Config.LOOP_INTERVAL_SEC)
                continue

            spread_pct = ((ask_price - bid_price) / current_price) * 100.0 if current_price else 0.0

            BOT_STATUS["current_price"] = current_price
            BOT_STATUS["price_change_24h"] = price_change
            BOT_STATUS["spread_pct"] = round(spread_pct, 4)
            BOT_STATUS["last_loop_time"] = datetime.now(timezone.utc).isoformat()

            # B. Fetch Recent Candles for Technical Indicators
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", limit=30)
                closes = [c[4] for c in ohlcv]
                highs = [c[2] for c in ohlcv]
                lows = [c[3] for c in ohlcv]

                rsi = indicators.calculate_rsi(closes, period=14)
                dip_pct, rebound_pct = indicators.calculate_dip_and_rebound(closes, current_price, lookback=15)
                volatility_pct = indicators.calculate_volatility_pct(highs, lows, current_price)

                BOT_STATUS["rsi"] = rsi
                BOT_STATUS["dip_pct"] = dip_pct
                BOT_STATUS["rebound_pct"] = rebound_pct
                BOT_STATUS["volatility_pct"] = volatility_pct
            except Exception as e:
                logger.debug(f"Could not calculate full indicators this cycle: {e}")
                rsi = 50.0
                dip_pct = 0.0
                rebound_pct = 0.0

            # C. Monitor Active Position (Exit Logic)
            if engine.active_position is not None:
                should_exit, exit_reason, sell_qty = engine.update_position_and_check_exit(current_price)
                if should_exit:
                    logger.info(f"⚡ EXIT SIGNAL TRIGGERED: {exit_reason} | Selling {sell_qty} {symbol}...")
                    if Config.LIVE_TRADING and not isinstance(exchange, PublicBinanceFallback):
                        success, actual_sold = execute_spot_sell(exchange, symbol, sell_qty, current_price)
                        if success:
                            engine.close_position(current_price, actual_sold, exit_reason)
                    else:
                        # Simulated Exit
                        engine.close_position(current_price, sell_qty, exit_reason)

            # D. Evaluate Entry Conditions (Buy Logic)
            else:
                can_buy, buy_check_msg = engine.can_buy()

                dip_satisfied = dip_pct >= Config.BUY_DIP_MIN_PCT
                rebound_satisfied = rebound_pct >= Config.BUY_REBOUND_CONFIRM_PCT
                rsi_satisfied = rsi <= Config.BUY_RSI_MAX
                spread_satisfied = spread_pct <= Config.MAX_SPREAD_PCT

                BOT_STATUS["entry_signals"] = {
                    "dip_satisfied": dip_satisfied,
                    "rebound_satisfied": rebound_satisfied,
                    "rsi_satisfied": rsi_satisfied,
                    "spread_satisfied": spread_satisfied,
                    "can_buy": can_buy,
                    "reason": buy_check_msg,
                }

                if can_buy and dip_satisfied and rebound_satisfied and rsi_satisfied and spread_satisfied:
                    logger.info(
                        f"🎯 ENTRY CONDITIONS CONFIRMED for {symbol}! "
                        f"Dip: {dip_pct:.2f}%, Rebound: {rebound_pct:.2f}%, RSI: {rsi:.1f}"
                    )
                    # Calculate quantity
                    buy_qty = engine.calculate_buy_qty(current_price)
                    if buy_qty > 0:
                        if Config.LIVE_TRADING and not isinstance(exchange, PublicBinanceFallback):
                            success, order_id = execute_spot_buy(exchange, symbol, buy_qty, current_price)
                            if success:
                                engine.open_position(current_price, buy_qty, order_id)
                        else:
                            # Simulated Buy
                            sim_order_id = f"SIM_{int(time.time())}"
                            engine.open_position(current_price, buy_qty, sim_order_id)

            # E. Update Dashboard Summary
            summary = engine.get_status_summary(current_price)
            BOT_STATUS.update(
                {
                    "has_position": summary["has_active_position"],
                    "position": summary["position"],
                    "total_realized_pnl_usd": summary["total_realized_pnl_usd"],
                    "total_trades": summary["total_trades"],
                    "winning_trades": summary["winning_trades"],
                    "losing_trades": summary["losing_trades"],
                    "win_rate_pct": summary["win_rate_pct"],
                    "recent_trades": summary["recent_trades"],
                }
            )

        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("Binance rate limit (429). Backing off for 30s...")
                time.sleep(30)
            else:
                logger.error(f"HTTP error in loop: {e}")
                time.sleep(Config.LOOP_INTERVAL_SEC)
        except Exception as e:
            logger.error(f"Unexpected error in trading loop: {e}")
            BOT_STATUS["error_diagnostic"] = str(e)
            time.sleep(Config.LOOP_INTERVAL_SEC)

        # Sleep remaining time to maintain consistent loop frequency
        elapsed = time.time() - loop_start
        sleep_time = max(0.5, Config.LOOP_INTERVAL_SEC - elapsed)
        time.sleep(sleep_time)

    logger.info("Bot execution loop exited cleanly.")


def handle_signals(signum, frame):
    logger.info(f"Received shutdown signal ({signum}). Gracefully closing...")
    shutdown_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signals)
    signal.signal(signal.SIGTERM, handle_signals)
    run_spot_bot()
