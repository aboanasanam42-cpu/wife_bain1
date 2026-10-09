"""
Binance Spot 24/7 Scalping & Position Execution Engine
Handles precision formatting, dynamic balance fee-compensation, trailing stops,
risk protection, and persistent state management for Binance Spot.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SpotEngine")


def round_step(val: float, step: float) -> float:
    """Rounds down a value to the nearest step size to satisfy LOT_SIZE filters."""
    if step <= 0:
        return val
    d_val = Decimal(str(val))
    d_step = Decimal(str(step))
    units = (d_val / d_step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return float(units * d_step)


def round_tick(val: float, tick: float) -> float:
    """Rounds a price to the nearest tick size to satisfy PRICE_FILTER."""
    if tick <= 0:
        return val
    d_val = Decimal(str(val))
    d_tick = Decimal(str(tick))
    units = (d_val / d_tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(units * d_tick)


@dataclass
class SpotPosition:
    symbol: str
    entry_price: float
    qty: float
    entry_time: float
    highest_price: float
    trailing_active: bool = False
    trailing_stop_price: float = 0.0
    order_id: Optional[str] = None
    cost_usd: float = 0.0


@dataclass
class ClosedTrade:
    symbol: str
    entry_price: float
    exit_price: float
    qty: float
    entry_time: float
    exit_time: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str


class SpotScalperEngine:
    def __init__(
        self,
        symbol: str,
        target_order_usd: float = 11.0,
        trailing_enabled: bool = True,
        trailing_activation_pct: float = 0.35,
        trailing_callback_pct: float = 0.15,
        stop_loss_pct: float = 0.80,
        max_hold_time_sec: int = 1200,
        stagnant_exit_pct: float = 0.10,
        buy_cooldown_sec: int = 60,
        state_file: str = "spot_state.json",
    ):
        self.symbol = symbol
        self.target_order_usd = target_order_usd
        self.trailing_enabled = trailing_enabled
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_callback_pct = trailing_callback_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_time_sec = max_hold_time_sec
        self.stagnant_exit_pct = stagnant_exit_pct
        self.buy_cooldown_sec = buy_cooldown_sec
        self.state_file = state_file

        # Market filters from exchange
        self.price_precision: int = 2
        self.amount_precision: int = 5
        self.tick_size: float = 0.01
        self.step_size: float = 0.00001
        self.min_qty: float = 0.00001
        self.min_notional: float = 5.0

        # State tracking
        self.active_position: Optional[SpotPosition] = None
        self.last_sell_time: float = 0.0
        self.total_realized_pnl_usd: float = 0.0
        self.total_trades_count: int = 0
        self.winning_trades_count: int = 0
        self.losing_trades_count: int = 0
        self.recent_trades: List[ClosedTrade] = []
        self.start_time: float = time.time()

        self.load_state()

    def set_market_filters(
        self,
        price_precision: int,
        amount_precision: int,
        tick_size: float,
        step_size: float,
        min_qty: float,
        min_notional: float,
    ):
        """Configure precision and exchange limits fetched from Binance Spot."""
        self.price_precision = max(0, price_precision)
        self.amount_precision = max(0, amount_precision)
        self.tick_size = tick_size if tick_size > 0 else 10 ** (-self.price_precision)
        self.step_size = step_size if step_size > 0 else 10 ** (-self.amount_precision)
        self.min_qty = max(min_qty, self.step_size)
        self.min_notional = max(5.0, min_notional)
        logger.info(
            f"Configured Spot Filters for {self.symbol} -> TickSize: {self.tick_size}, "
            f"StepSize: {self.step_size}, MinQty: {self.min_qty}, MinNotional: {self.min_notional} USDT"
        )

    def format_price(self, price: float) -> float:
        rounded = round_tick(price, self.tick_size)
        return float(f"{rounded:.{self.price_precision}f}")

    def format_qty(self, qty: float) -> float:
        rounded = round_step(qty, self.step_size)
        return float(f"{rounded:.{self.amount_precision}f}")

    def calculate_buy_qty(self, current_price: float, available_quote_balance: float = 0.0) -> float:
        """
        Calculates optimal base asset quantity for a Spot BUY order.
        Ensures compliance with minNotional ($5-$10) and wallet balance.
        """
        if current_price <= 0:
            return 0.0

        spend_usd = max(self.target_order_usd, self.min_notional * 1.05)
        if available_quote_balance > 0 and available_quote_balance < spend_usd:
            spend_usd = available_quote_balance * 0.98  # Safety margin for quote balance

        if spend_usd < self.min_notional:
            logger.warning(
                f"Target spend ${spend_usd:.2f} is below Binance Spot minNotional ${self.min_notional:.2f}."
            )
            return 0.0

        raw_qty = spend_usd / current_price
        formatted_qty = self.format_qty(raw_qty)

        # Check notional value after rounding down
        if (formatted_qty * current_price) < self.min_notional:
            # Add one step size to satisfy minNotional
            formatted_qty = self.format_qty(formatted_qty + self.step_size)

        return formatted_qty

    def can_buy(self) -> Tuple[bool, str]:
        """Checks if bot is allowed to enter a new Spot position."""
        if self.active_position is not None:
            return False, "Already in an active Spot position."

        now = time.time()
        elapsed_since_sell = now - self.last_sell_time
        if elapsed_since_sell < self.buy_cooldown_sec:
            rem = int(self.buy_cooldown_sec - elapsed_since_sell)
            return False, f"Buy cooldown active ({rem}s remaining)."

        return True, "Ready to buy."

    def open_position(self, entry_price: float, qty: float, order_id: Optional[str] = None) -> SpotPosition:
        """Registers a newly filled Spot BUY order."""
        pos = SpotPosition(
            symbol=self.symbol,
            entry_price=entry_price,
            qty=qty,
            entry_time=time.time(),
            highest_price=entry_price,
            trailing_active=False,
            trailing_stop_price=0.0,
            order_id=order_id,
            cost_usd=round(entry_price * qty, 4),
        )
        self.active_position = pos
        logger.info(
            f"🚀 [SPOT BUY EXECUTED] Entered {self.symbol} at ${entry_price:,.2f} | "
            f"Qty: {qty} | Total Cost: ${pos.cost_usd:.2f} USDT"
        )
        self.save_state()
        return pos

    def update_position_and_check_exit(self, current_price: float) -> Tuple[bool, str, float]:
        """
        Monitors active Spot position:
        1. Tracks high-water mark (highest price seen).
        2. Activates and trails Trailing Take-Profit.
        3. Checks Hard Stop-Loss.
        4. Checks Max Hold Time stagnant exit.
        Returns: (should_exit, exit_reason, sell_qty)
        """
        if self.active_position is None:
            return False, "NO_POSITION", 0.0

        pos = self.active_position
        now = time.time()
        hold_time = now - pos.entry_time

        # Update high-water mark
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        # Calculate current and peak gains
        pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0
        peak_gain_pct = ((pos.highest_price - pos.entry_price) / pos.entry_price) * 100.0

        # 1. Trailing Stop Activation & Trailing
        if self.trailing_enabled and peak_gain_pct >= self.trailing_activation_pct:
            pos.trailing_active = True
            calculated_stop = pos.highest_price * (1.0 - (self.trailing_callback_pct / 100.0))
            if calculated_stop > pos.trailing_stop_price:
                pos.trailing_stop_price = self.format_price(calculated_stop)

            # Trigger exit if current price drops below trailing stop
            if current_price <= pos.trailing_stop_price:
                reason = f"TRAILING_TAKE_PROFIT (Peak: +{peak_gain_pct:.2f}%, Exit: +{pnl_pct:.2f}%)"
                return True, reason, pos.qty

        # 2. Hard Stop-Loss Protection
        if pnl_pct <= -self.stop_loss_pct:
            reason = f"HARD_STOP_LOSS (Current: {pnl_pct:.2f}%, Limit: -{self.stop_loss_pct:.2f}%)"
            return True, reason, pos.qty

        # 3. Stagnant / Max Hold Time Exit
        if hold_time >= self.max_hold_time_sec:
            if pnl_pct >= self.stagnant_exit_pct:
                reason = f"STAGNANT_PROFIT_EXIT (Hold: {int(hold_time)}s, PnL: +{pnl_pct:.2f}%)"
                return True, reason, pos.qty
            elif pnl_pct <= -0.15:
                reason = f"STAGNANT_TIMEOUT_EXIT (Hold: {int(hold_time)}s, PnL: {pnl_pct:.2f}%)"
                return True, reason, pos.qty

        return False, "HOLDING", 0.0

    def close_position(
        self, exit_price: float, filled_qty: float, exit_reason: str
    ) -> Optional[ClosedTrade]:
        """Registers a filled Spot SELL order, calculates realized PnL, and archives trade."""
        if self.active_position is None:
            return None

        pos = self.active_position
        now = time.time()

        # Deduct standard Spot taker fee ~0.075-0.1% from gross PnL
        revenue_usd = exit_price * filled_qty
        cost_usd = pos.entry_price * filled_qty
        gross_pnl = revenue_usd - cost_usd
        est_fees = (cost_usd + revenue_usd) * 0.00075  # 0.075% fee
        net_pnl = gross_pnl - est_fees
        pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100.0

        trade = ClosedTrade(
            symbol=pos.symbol,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            qty=filled_qty,
            entry_time=pos.entry_time,
            exit_time=now,
            pnl_usd=round(net_pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            exit_reason=exit_reason,
        )

        self.total_realized_pnl_usd += net_pnl
        self.total_trades_count += 1
        if net_pnl >= 0:
            self.winning_trades_count += 1
        else:
            self.losing_trades_count += 1

        self.recent_trades.insert(0, trade)
        if len(self.recent_trades) > 20:
            self.recent_trades = self.recent_trades[:20]

        logger.info(
            f"✅ [SPOT SELL EXECUTED] Closed {self.symbol} at ${exit_price:,.2f} | "
            f"Net PnL: {net_pnl:+.4f} USDT ({pnl_pct:+.2f}%) | Reason: {exit_reason}"
        )

        self.active_position = None
        self.last_sell_time = now
        self.save_state()
        return trade

    def get_status_summary(self, current_price: float = 0.0) -> Dict[str, Any]:
        """Provides status data for HTTP Dashboard and API."""
        pos_data = None
        if self.active_position:
            pos = self.active_position
            pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0 if current_price else 0.0
            pnl_usd = (current_price - pos.entry_price) * pos.qty if current_price else 0.0
            hold_sec = int(time.time() - pos.entry_time)

            pos_data = {
                "symbol": pos.symbol,
                "entry_price": pos.entry_price,
                "current_price": current_price,
                "highest_price": pos.highest_price,
                "qty": pos.qty,
                "cost_usd": pos.cost_usd,
                "trailing_active": pos.trailing_active,
                "trailing_stop_price": pos.trailing_stop_price,
                "unrealized_pnl_usd": round(pnl_usd, 4),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "hold_time_seconds": hold_sec,
            }

        win_rate = (
            round((self.winning_trades_count / self.total_trades_count) * 100.0, 1)
            if self.total_trades_count > 0
            else 0.0
        )

        return {
            "symbol": self.symbol,
            "has_active_position": self.active_position is not None,
            "position": pos_data,
            "total_realized_pnl_usd": round(self.total_realized_pnl_usd, 4),
            "total_trades": self.total_trades_count,
            "winning_trades": self.winning_trades_count,
            "losing_trades": self.losing_trades_count,
            "win_rate_pct": win_rate,
            "recent_trades": [asdict(t) for t in self.recent_trades[:5]],
            "uptime_seconds": int(time.time() - self.start_time),
        }

    def save_state(self):
        """Persists trade history and active position to state file."""
        try:
            state = {
                "total_realized_pnl_usd": self.total_realized_pnl_usd,
                "total_trades_count": self.total_trades_count,
                "winning_trades_count": self.winning_trades_count,
                "losing_trades_count": self.losing_trades_count,
                "last_sell_time": self.last_sell_time,
                "active_position": asdict(self.active_position) if self.active_position else None,
                "recent_trades": [asdict(t) for t in self.recent_trades],
                "saved_at": time.time(),
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")

    def load_state(self):
        """Loads state from disk if exists."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.total_realized_pnl_usd = state.get("total_realized_pnl_usd", 0.0)
            self.total_trades_count = state.get("total_trades_count", 0)
            self.winning_trades_count = state.get("winning_trades_count", 0)
            self.losing_trades_count = state.get("losing_trades_count", 0)
            self.last_sell_time = state.get("last_sell_time", 0.0)

            act_pos = state.get("active_position")
            if act_pos:
                self.active_position = SpotPosition(**act_pos)

            self.recent_trades = []
            for t in state.get("recent_trades", []):
                self.recent_trades.append(ClosedTrade(**t))

            logger.info(
                f"Restored state from {self.state_file} -> {self.total_trades_count} trades, "
                f"Realized PnL: {self.total_realized_pnl_usd:+.4f} USDT"
            )
        except Exception as e:
            logger.warning(f"Could not load state from {self.state_file}: {e}")
