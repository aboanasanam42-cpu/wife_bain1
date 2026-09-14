```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Vercel Serverless Binance Spot trader.

Buys confirmed BTC/USDT dips with rebound confirmation and manages
open positions using a high-water trailing exit and emergency stop.

API credentials and LIVE_TRADING must be supplied through environment
variables. Never store Binance credentials in this file.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

import ccxt

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


POSITIONS_FILE = "/tmp/positions.json"

TRADE_TRIGGER_TOKEN = os.environ.get(
    "TRADE_TRIGGER_TOKEN",
    "",
).strip()

CRON_SECRET = os.environ.get(
    "CRON_SECRET",
    "",
).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
        "on",
    }


# LIVE_TRADING is intentionally controlled by the environment.
# If LIVE_TRADING=true is configured in Vercel, real Binance orders
# can be submitted.
LIVE_TRADING = env_bool(
    "LIVE_TRADING",
    False,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> float:
    return utc_now().timestamp()


def safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        number = float(value)

        if number != number:
            return default

        return number

    except (TypeError, ValueError):
        return default


def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)

    except (TypeError, ValueError):
        return default


def sanitize_key(
    key: str | None,
) -> str:
    """Remove accidental quotes and whitespace from environment secrets."""

    if not key:
        return ""

    cleaned = key.strip()

    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in "\"'"
    ):
        cleaned = cleaned[1:-1].strip()

    return "".join(
        character
        for character in cleaned
        if character.isprintable()
        and not character.isspace()
    )


def require_trigger_token(
    handler: BaseHTTPRequestHandler,
) -> None:
    """Accept the manual trade token or Vercel Cron secret."""

    if not TRADE_TRIGGER_TOKEN and not CRON_SECRET:
        return

    authorization = handler.headers.get(
        "Authorization",
        "",
    ).strip()

    token = ""

    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        token = (
            handler.headers.get(
                "X-Trade-Token",
                "",
            ).strip()
            or handler.headers.get(
                "X-Trigger-Token",
                "",
            ).strip()
        )

    if not token and "?" in handler.path:
        try:
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(
                urlparse(handler.path).query
            )

            token = (
                query.get(
                    "token",
                    [""],
                )[0]
                or query.get(
                    "secret",
                    [""],
                )[0]
            ).strip()

        except Exception:
            token = ""

    valid = (
        (
            bool(TRADE_TRIGGER_TOKEN)
            and token == TRADE_TRIGGER_TOKEN
        )
        or (
            bool(CRON_SECRET)
            and token == CRON_SECRET
        )
    )

    if not valid:
        raise PermissionError(
            "Unauthorized trade trigger"
        )


def create_exchange(
    api_key: str,
    api_secret: str,
) -> ccxt.binance:

    exchange = ccxt.binance(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": 20_000,
            "options": {
                "defaultType": "spot",
                "adjustForTimeDifference": True,
            },
        }
    )

    return exchange


def create_market_order(
    exchange: ccxt.binance,
    side: str,
    symbol: str,
    amount: float,
) -> dict[str, Any]:

    if amount <= 0:
        raise ValueError(
            "Order amount must be greater than zero."
        )

    if not LIVE_TRADING:
        return {
            "id": "DRY-RUN",
            "side": side,
            "symbol": symbol,
            "amount": amount,
            "average": None,
            "filled": amount,
            "cost": None,
            "dry_run": True,
        }

    if side == "buy":
        return exchange.create_market_buy_order(
            symbol,
            amount,
        )

    if side == "sell":
        return exchange.create_market_sell_order(
            symbol,
            amount,
        )

    raise ValueError(
        f"Unsupported order side: {side}"
    )


def load_positions() -> list[dict[str, Any]]:

    try:
        if not os.path.exists(
            POSITIONS_FILE
        ):
            return []

        with open(
            POSITIONS_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(data, list):
            return []

        return [
            position
            for position in data
            if isinstance(position, dict)
        ]

    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
    ):
        return []


def save_positions(
    positions: list[dict[str, Any]],
) -> None:
    """Atomically save state inside Vercel writable /tmp."""

    directory = (
        os.path.dirname(POSITIONS_FILE)
        or "/tmp"
    )

    os.makedirs(
        directory,
        exist_ok=True,
    )

    fd, temporary_path = tempfile.mkstemp(
        prefix="positions-",
        suffix=".tmp",
        dir=directory,
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                positions,
                file,
                indent=2,
                ensure_ascii=False,
            )

            file.flush()
            os.fsync(file.fileno())

        os.replace(
            temporary_path,
            POSITIONS_FILE,
        )

    except Exception:

        try:
            os.unlink(
                temporary_path
            )
        except OSError:
            pass

        raise


def get_min_notional(
    market: dict[str, Any],
) -> float:
    """Read Binance minimum order cost."""

    candidates: list[float] = []

    try:

        cost = (
            market.get(
                "limits",
                {},
            )
            .get(
                "cost",
                {},
            )
            .get("min")
        )

        if cost is not None:
            candidates.append(
                float(cost)
            )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        pass

    try:

        filters = (
            market.get(
                "info",
                {},
            ).get(
                "filters",
                [],
            )
        )

        for item in filters:

            if item.get(
                "filterType"
            ) in {
                "NOTIONAL",
                "MIN_NOTIONAL",
            }:

                value = item.get(
                    "minNotional",
                    item.get(
                        "notional"
                    ),
                )

                if value is not None:
                    candidates.append(
                        float(value)
                    )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        pass

    positive = [
        value
        for value in candidates
        if value > 0
    ]

    return max(
        positive,
        default=5.0,
    )


def position_created_timestamp(
    position: dict[str, Any],
) -> float:

    value = position.get(
        "created_at_ts"
    )

    if value is not None:
        return safe_float(
            value,
            0.0,
        )

    timestamp_text = position.get(
        "timestamp"
    )

    if isinstance(
        timestamp_text,
        str,
    ):

        try:

            return datetime.fromisoformat(
                timestamp_text.replace(
                    "Z",
                    "+00:00",
                )
            ).timestamp()

        except ValueError:
            pass

    return 0.0


def sell_position(
    exchange: ccxt.binance,
    symbol: str,
    position: dict[str, Any],
    reason: str,
    current_price: float,
    actions: list[dict[str, Any]],
) -> bool:

    amount = safe_float(
        position.get("amount")
    )

    if amount <= 0:

        actions.append(
            {
                "action": "SELL_SKIPPED",
                "reason": (
                    "Position amount is zero or invalid"
                ),
            }
        )

        return False

    try:

        sell_amount = safe_float(
            exchange.amount_to_precision(
                symbol,
                amount,
            )
        )

    except Exception as exc:

        actions.append(
            {
                "action": "SELL_SKIPPED",
                "reason": (
                    f"Amount precision error: {exc}"
                ),
            }
        )

        return False

    if sell_amount <= 0:

        actions.append(
            {
                "action": "SELL_SKIPPED",
                "reason": (
                    "Calculated sell amount is zero"
                ),
            }
        )

        return False

    try:

        order = create_market_order(
            exchange,
            "sell",
            symbol,
            sell_amount,
        )

        executed_amount = safe_float(
            order.get("filled"),
            sell_amount,
        )

        execution_price = safe_float(
            order.get("average"),
            current_price,
        )

        entry_price = safe_float(
            position.get("entry_price")
        )

        pnl_pct = (
            (
                (
                    execution_price
                    - entry_price
                )
                / entry_price
            )
            * 100.0
            if entry_price > 0
            else 0.0
        )

        actions.append(
            {
                "action": "MARKET_SELL",
                "order_id": order.get("id"),
                "amount": executed_amount,
                "entry_price": entry_price,
                "highest_price": safe_float(
                    position.get(
                        "highest_price"
                    ),
                    entry_price,
                ),
                "exit_price": execution_price,
                "pnl_pct": (
                    f"{pnl_pct:+.3f}%"
                ),
                "reason": reason,
                "dry_run": bool(
                    order.get(
                        "dry_run",
                        False,
                    )
                ),
            }
        )

        return True

    except ccxt.InsufficientFunds as exc:

        actions.append(
            {
                "action": "SELL_FAILED",
                "error": (
                    "Insufficient BTC balance: "
                    f"{exc}"
                ),
                "reason": reason,
            }
        )

    except ccxt.InvalidOrder as exc:

        actions.append(
            {
                "action": "SELL_FAILED",
                "error": (
                    f"Invalid sell order: {exc}"
                ),
                "reason": reason,
            }
        )

    except ccxt.BaseError as exc:

        actions.append(
            {
                "action": "SELL_FAILED",
                "error": str(exc),
                "reason": reason,
            }
        )

    except Exception as exc:

        actions.append(
            {
                "action": "SELL_FAILED",
                "error": str(exc),
                "reason": reason,
            }
        )

    return False


def calculate_rsi(
    closes: list[float],
) -> float:

    if len(closes) < 15:
        return 50.0

    changes = [
        current - previous
        for previous, current in zip(
            closes[-15:-1],
            closes[-14:],
        )
    ]

    gains = [
        max(change, 0.0)
        for change in changes
    ]

    losses = [
        max(-change, 0.0)
        for change in changes
    ]

    average_gain = (
        sum(gains)
        / max(
            1,
            len(gains),
        )
    )

    average_loss = (
        sum(losses)
        / max(
            1,
            len(losses),
        )
    )

    if average_loss == 0:
        return 100.0

    relative_strength = (
        average_gain
        / average_loss
    )

    return (
        100.0
        - (
            100.0
            / (
                1.0
                + relative_strength
            )
        )
    )


def execute_trade_cycle() -> dict[str, Any]:

    raw_key = (
        os.environ.get(
            "BINANCE_API_KEY"
        )
        or os.environ.get(
            "BINANCE_KEY"
        )
        or ""
    )

    raw_secret = (
        os.environ.get(
            "BINANCE_API_SECRET"
        )
        or os.environ.get(
            "BINANCE_SECRET"
        )
        or ""
    )

    api_key = sanitize_key(
        raw_key
    )

    api_secret = sanitize_key(
        raw_secret
    )

    if not api_key or not api_secret:

        raise ValueError(
            "BINANCE_API_KEY و "
            "BINANCE_API_SECRET مطلوبان "
            "في Vercel Environment Variables"
        )

    symbol = os.environ.get(
        "SYMBOL",
        "BTC/USDT",
    ).strip()

    target_order_usd = max(
        0.0,
        safe_float(
            os.environ.get(
                "TARGET_ORDER_USD",
                "5.5",
            ),
            5.5,
        ),
    )

    max_positions = max(
        1,
        safe_int(
            os.environ.get(
                "MAX_POSITIONS",
                "1",
            ),
            1,
        ),
    )

    buy_cooldown_sec = max(
        0,
        safe_int(
            os.environ.get(
                "BUY_COOLDOWN_SEC",
                "30",
            ),
            30,
        ),
    )

    buy_dip_min_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "BUY_DIP_MIN_PCT",
                "0.25",
            ),
            0.25,
        ),
    )

    buy_rebound_confirm_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "BUY_REBOUND_CONFIRM_PCT",
                "0.08",
            ),
            0.08,
        ),
    )

    buy_rsi_max = safe_float(
        os.environ.get(
            "BUY_RSI_MAX",
            "48",
        ),
        48.0,
    )

    min_volatility_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "MIN_VOLATILITY_PCT",
                "0.20",
            ),
            0.20,
        ),
    )

    max_spread_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "MAX_SPREAD_PCT",
                "0.15",
            ),
            0.15,
        ),
    )

    trailing_enabled = env_bool(
        "TRAILING_STOP_ENABLED",
        True,
    )

    trailing_activation_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "TRAILING_ACTIVATION_PCT",
                "0.15",
            ),
            0.15,
        ),
    )

    trailing_callback_pct = max(
        0.0,
        safe_float(
            os.environ.get(
                "TRAILING_CALLBACK_PCT",
                "0.20",
            ),
            0.20,
        ),
    )

    stop_loss_pct = max(
        0.01,
        safe_float(
            os.environ.get(
                "STOP_LOSS_PCT",
                "0.40",
            ),
            0.40,
        ),
    )

    max_hold_time_sec = max(
        0,
        safe_int(
            os.environ.get(
                "MAX_HOLD_TIME_SEC",
                "1200",
            ),
            1200,
        ),
    )

    stagnant_exit_pct = safe_float(
        os.environ.get(
            "STAGNANT_EXIT_PCT",
            "0.00",
        ),
        0.0,
    )

    exchange = create_exchange(
        api_key,
        api_secret,
    )

    markets = exchange.load_markets()

    if symbol not in markets:

        raise ValueError(
            f"{symbol} is not available "
            "on Binance Spot"
        )

    market = markets[symbol]

    min_notional = get_min_notional(
        market
    )

    ticker = exchange.fetch_ticker(
        symbol
    )

    current_price = safe_float(
        ticker.get("last")
    )

    if current_price <= 0:

        raise ValueError(
            "Binance returned an invalid "
            "current price."
        )

    bid = safe_float(
        ticker.get("bid"),
        current_price,
    )

    ask = safe_float(
        ticker.get("ask"),
        current_price,
    )

    spread_pct = (
        (
            (
                ask - bid
            )
            / current_price
        )
        * 100.0
        if current_price > 0
        else 0.0
    )

    balance = exchange.fetch_balance()

    free_balances = balance.get(
        "free",
        {},
    )

    free_usdt = safe_float(
        free_balances.get("USDT")
    )

    base_currency = symbol.split(
        "/",
        1,
    )[0]

    free_base = safe_float(
        free_balances.get(
            base_currency
        )
    )

    positions = load_positions()

    now_ts = utc_timestamp()

    actions: list[
        dict[str, Any]
    ] = []

    # -------------------------------------------------
    # 1. Manage existing positions first.
    # -------------------------------------------------

    remaining: list[
        dict[str, Any]
    ] = []

    for position in positions:

        try:

            entry = safe_float(
                position.get(
                    "entry_price"
                )
            )

            amount = safe_float(
                position.get(
                    "amount"
                )
            )

            if entry <= 0 or amount <= 0:

                actions.append(
                    {
                        "action": (
                            "POSITION_REMOVED"
                        ),
                        "reason": (
                            "Invalid stored position"
                        ),
                    }
                )

                continue

            highest = max(
                safe_float(
                    position.get(
                        "highest_price"
                    ),
                    entry,
                ),
                current_price,
            )

            position[
                "highest_price"
            ] = highest

            pnl_pct = (
                (
                    current_price
                    - entry
                )
                / entry
                * 100.0
            )

            peak_gain_pct = (
                (
                    highest
                    - entry
                )
                / entry
                * 100.0
            )

            drop_from_peak_pct = (
                (
                    highest
                    - current_price
                )
                / highest
                * 100.0
                if highest > 0
                else 0.0
            )

            created_at = (
                position_created_timestamp(
                    position
                )
            )

            age = (
                max(
                    0.0,
                    now_ts - created_at,
                )
                if created_at > 0
                else 0.0
            )

            trailing_active = bool(
                position.get(
                    "trailing_active",
                    False,
                )
            )

            if (
                trailing_enabled
                and peak_gain_pct
                >= trailing_activation_pct
            ):
                trailing_active = True

            position[
                "trailing_active"
            ] = trailing_active

            position[
                "current_pnl_pct"
            ] = round(
                pnl_pct,
                4,
            )

            position[
                "peak_gain_pct"
            ] = round(
                peak_gain_pct,
                4,
            )

            exit_reason: str | None = None

            if (
                trailing_active
                and trailing_callback_pct > 0
                and drop_from_peak_pct
                >= trailing_callback_pct
            ):

                exit_reason = (
                    "Trailing reversal: "
                    f"-{drop_from_peak_pct:.3f}% "
                    f"from high ${highest:,.2f}"
                )

            elif (
                pnl_pct
                <= -stop_loss_pct
            ):

                exit_reason = (
                    "Emergency stop: "
                    f"{pnl_pct:.3f}%"
                )

            elif (
                max_hold_time_sec
                and age >= max_hold_time_sec
                and pnl_pct <= stagnant_exit_pct
            ):

                exit_reason = (
                    "Capital release after "
                    f"{int(age // 60)} minutes"
                )

            if (
                exit_reason
                and sell_position(
                    exchange,
                    symbol,
                    position,
                    exit_reason,
                    current_price,
                    actions,
                )
            ):
                continue

            remaining.append(
                position
            )

        except Exception as exc:

            actions.append(
                {
                    "action": (
                        "POSITION_ERROR"
                    ),
                    "error": str(exc),
                }
            )

            remaining.append(
                position
            )

    positions = remaining

    save_positions(
        positions
    )

    # -------------------------------------------------
    # 2. Refresh balances after possible sales.
    # -------------------------------------------------

    balance = exchange.fetch_balance()

    free_balances = balance.get(
        "free",
        {},
    )

    free_usdt = safe_float(
        free_balances.get("USDT")
    )

    free_base = safe_float(
        free_balances.get(
            base_currency
        )
    )

    # -------------------------------------------------
    # 3. Entry cooldown.
    # -------------------------------------------------

    last_buy_ts = max(
        (
            position_created_timestamp(
                position
            )
            for position in positions
        ),
        default=0.0,
    )

    cooldown_ok = (
        not last_buy_ts
        or (
            now_ts - last_buy_ts
            >= buy_cooldown_sec
        )
    )

    # -------------------------------------------------
    # 4. Look for a new confirmed entry.
    # -------------------------------------------------

    if len(positions) >= max_positions:

        actions.append(
            {
                "action": "HOLD",
                "reason": (
                    "Maximum open "
                    "position count reached"
                ),
            }
        )

    elif not cooldown_ok:

        remaining_cooldown = max(
            0,
            int(
                buy_cooldown_sec
                - (
                    now_ts
                    - last_buy_ts
                )
            ),
        )

        actions.append(
            {
                "action": "HOLD",
                "reason": (
                    "Buy cooldown active: "
                    f"{remaining_cooldown}s remaining"
                ),
            }
        )

    else:

        order_cost = max(
            target_order_usd,
            min_notional + 0.10,
        )

        if free_usdt < order_cost:

            actions.append(
                {
                    "action": "HOLD",
                    "reason": (
                        f"USDT insufficient: "
                        f"need {order_cost:.2f}, "
                        f"have {free_usdt:.2f}"
                    ),
                }
            )

        elif spread_pct > max_spread_pct:

            actions.append(
                {
                    "action": "HOLD",
                    "reason": (
                        f"Spread too high: "
                        f"{spread_pct:.3f}% > "
                        f"{max_spread_pct:.3f}%"
                    ),
                }
            )

        else:

            candles = exchange.fetch_ohlcv(
                symbol,
                timeframe="1m",
                limit=21,
            )

            if len(candles) < 15:

                actions.append(
                    {
                        "action": "HOLD",
                        "reason": (
                            "Insufficient "
                            "1m candle history"
                        ),
                    }
                )

            else:

                highs = [
                    safe_float(
                        candle[2]
                    )
                    for candle in candles
                ]

                lows = [
                    safe_float(
                        candle[3]
                    )
                    for candle in candles
                ]

                closes = [
                    safe_float(
                        candle[4]
                    )
                    for candle in candles
                ]

                valid_highs = [
                    value
                    for value in highs
                    if value > 0
                ]

                valid_lows = [
                    value
                    for value in lows
                    if value > 0
                ]

                if (
                    not valid_highs
                    or not valid_lows
                ):

                    actions.append(
                        {
                            "action": "HOLD",
                            "reason": (
                                "Invalid candle prices"
                            ),
                        }
                    )

                else:

                    window_high = max(
                        highs[:-2]
                    )

                    window_low = min(
                        lows[-4:]
                    )

                    dip_pct = (
                        (
                            (
                                window_high
                                - window_low
                            )
                            / window_high
                        )
                        * 100.0
                        if window_high > 0
                        else 0.0
                    )

                    rebound_pct = (
                        (
                            (
                                current_price
                                - window_low
                            )
                            / window_low
                        )
                        * 100.0
                        if window_low > 0
                        else 0.0
                    )

                    recent_high = max(
                        highs[-15:]
                    )

                    recent_low = min(
                        lows[-15:]
                    )

                    volatility_pct = (
                        (
                            (
                                recent_high
                                - recent_low
                            )
                            / recent_low
                        )
                        * 100.0
                        if recent_low > 0
                        else 0.0
                    )

                    rsi = calculate_rsi(
                        closes
                    )

                    previous_close = (
                        closes[-2]
                    )

                    rebound_confirmed = (
                        current_price
                        > previous_close
                        and rebound_pct
                        >= buy_rebound_confirm_pct
                    )

                    dip_confirmed = (
                        dip_pct
                        >= buy_dip_min_pct
                    )

                    if (
                        volatility_pct
                        < min_volatility_pct
                    ):

                        actions.append(
                            {
                                "action": "HOLD",
                                "reason": (
                                    "Low volatility: "
                                    f"{volatility_pct:.3f}%"
                                ),
                            }
                        )

                    elif not dip_confirmed:

                        actions.append(
                            {
                                "action": "HOLD",
                                "reason": (
                                    "No dip yet: "
                                    f"{dip_pct:.3f}% < "
                                    f"{buy_dip_min_pct:.3f}%"
                                ),
                            }
                        )

                    elif not rebound_confirmed:

                        actions.append(
                            {
                                "action": "HOLD",
                                "reason": (
                                    "Waiting for rebound "
                                    "confirmation: "
                                    f"{rebound_pct:.3f}%"
                                ),
                            }
                        )

                    elif rsi > buy_rsi_max:

                        actions.append(
                            {
                                "action": "HOLD",
                                "reason": (
                                    "Rebound already "
                                    "extended: "
                                    f"RSI {rsi:.1f} > "
                                    f"{buy_rsi_max:.1f}"
                                ),
                            }
                        )

                    else:

                        raw_amount = (
                            order_cost / ask
                        )

                        buy_amount = safe_float(
                            exchange.amount_to_precision(
                                symbol,
                                raw_amount,
                            )
                        )

                        estimated_cost = (
                            buy_amount * ask
                        )

                        if (
                            estimated_cost
                            < min_notional
                        ):

                            try:

                                minimum_amount = (
                                    safe_float(
                                        market.get(
                                            "limits",
                                            {},
                                        )
                                        .get(
                                            "amount",
                                            {},
                                        )
                                        .get(
                                            "min"
                                        )
                                    )
                                )

                                if minimum_amount > 0:

                                    buy_amount = max(
                                        buy_amount,
                                        minimum_amount,
                                    )

                                buy_amount = safe_float(
                                    exchange.amount_to_precision(
                                        symbol,
                                        buy_amount,
                                    )
                                )

                                estimated_cost = (
                                    buy_amount
                                    * ask
                                )

                            except Exception:
                                pass

                        if (
                            estimated_cost
                            < min_notional
                        ):

                            actions.append(
                                {
                                    "action": "HOLD",
                                    "reason": (
                                        f"Order cost "
                                        f"{estimated_cost:.4f} "
                                        f"is below Binance "
                                        f"minimum notional "
                                        f"{min_notional:.4f}"
                                    ),
                                }
                            )

                        elif buy_amount <= 0:

                            actions.append(
                                {
                                    "action": "HOLD",
                                    "reason": (
                                        "Calculated buy "
                                        "amount is zero"
                                    ),
                                }
                            )

                        else:

                            try:

                                order = (
                                    create_market_order(
                                        exchange,
                                        "buy",
                                        symbol,
                                        buy_amount,
                                    )
                                )

                                filled = safe_float(
                                    order.get(
                                        "filled"
                                    ),
                                    buy_amount,
                                )

                                entry_price = safe_float(
                                    order.get(
                                        "average"
                                    ),
                                    ask,
                                )

                                if filled <= 0:
                                    raise ValueError(
                                        "Binance returned "
                                        "zero filled amount."
                                    )

                                if entry_price <= 0:
                                    raise ValueError(
                                        "Invalid executed "
                                        "buy price."
                                    )

                                positions.append(
                                    {
                                        "id": order.get(
                                            "id"
                                        ),
                                        "symbol": symbol,
                                        "amount": filled,
                                        "entry_price": (
                                            entry_price
                                        ),
                                        "highest_price": (
                                            entry_price
                                        ),
                                        "cost": safe_float(
                                            order.get(
                                                "cost"
                                            ),
                                            entry_price
                                            * filled,
                                        ),
                                        "timestamp": (
                                            utc_now().isoformat()
                                        ),
                                        "created_at_ts": (
                                            now_ts
                                        ),
                                        "trailing_active": (
                                            False
                                        ),
                                        "side": "buy",
                                        "dry_run": bool(
                                            order.get(
                                                "dry_run",
                                                False,
                                            )
                                        ),
                                    }
                                )

                                save_positions(
                                    positions
                                )

                                actions.append(
                                    {
                                        "action": (
                                            "MARKET_BUY"
                                        ),
                                        "order_id": (
                                            order.get(
                                                "id"
                                            )
                                        ),
                                        "entry_price": (
                                            entry_price
                                        ),
                                        "amount": filled,
                                        "dip_pct": round(
                                            dip_pct,
                                            3,
                                        ),
                                        "rebound_pct": round(
                                            rebound_pct,
                                            3,
                                        ),
                                        "rsi": round(
                                            rsi,
                                            2,
                                        ),
                                        "volatility_15m": (
                                            round(
                                                volatility_pct,
                                                3,
                                            )
                                        ),
                                        "signal": (
                                            "DIP + REBOUND "
                                            "CONFIRMED"
                                        ),
                                        "dry_run": bool(
                                            order.get(
                                                "dry_run",
                                                False,
                                            )
                                        ),
                                    }
                                )

                            except ccxt.InsufficientFunds as exc:

                                actions.append(
                                    {
                                        "action": (
                                            "BUY_FAILED"
                                        ),
                                        "error": (
                                            "Insufficient "
                                            "USDT balance: "
                                            f"{exc}"
                                        ),
                                    }
                                )

                            except ccxt.InvalidOrder as exc:

                                actions.append(
                                    {
                                        "action": (
                                            "BUY_FAILED"
                                        ),
                                        "error": (
                                            "Binance rejected "
                                            f"order: {exc}"
                                        ),
                                    }
                                )

                            except ccxt.AuthenticationError as exc:

                                actions.append(
                                    {
                                        "action": (
                                            "BUY_FAILED"
                                        ),
                                        "error": (
                                            "Binance authentication "
                                            "failed. Check API "
                                            "credentials and "
                                            "permissions."
                                        ),
                                        "details": str(
                                            exc
                                        ),
                                    }
                                )

                            except ccxt.BaseError as exc:

                                actions.append(
                                    {
                                        "action": (
                                            "BUY_FAILED"
                                        ),
                                        "error": str(
                                            exc
                                        ),
                                    }
                                )

                            except Exception as exc:

                                actions.append(
                                    {
                                        "action": (
                                            "BUY_FAILED"
                                        ),
                                        "error": str(
                                            exc
                                        ),
                                    }
                                )

    return {
        "status": "success",
        "live_trading": LIVE_TRADING,
        "symbol": symbol,
        "current_price": current_price,
        "usdt_balance": free_usdt,
        f"{base_currency.lower()}_balance": free_base,
        "min_notional": min_notional,
        "active_positions_count": len(
            positions
        ),
        "active_positions": positions,
        "action_taken": actions,
        "strategy": (
            "BUY_DIP_REBOUND + "
            "HIGH_WATER_TRAILING + "
            "EMERGENCY_EXIT"
        ),
        "timestamp": utc_now().isoformat(),
    }


class handler(
    BaseHTTPRequestHandler
):

    def do_GET(self) -> None:
        self._handle_request()

    def do_POST(self) -> None:
        self._handle_request()

    def do_OPTIONS(self) -> None:

        self.send_response(204)

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            (
                "Content-Type, "
                "Authorization, "
                "X-Trade-Token, "
                "X-Trigger-Token"
            ),
        )

        self.end_headers()

    def _send_json(
        self,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:

        body = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        self.send_response(
            status_code
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def _handle_request(
        self,
    ) -> None:

        try:

            require_trigger_token(
                self
            )

            result = execute_trade_cycle()

            self._send_json(
                200,
                result,
            )

        except PermissionError as exc:

            self._send_json(
                401,
                {
                    "status": "error",
                    "error_type": (
                        "Unauthorized"
                    ),
                    "message": str(
                        exc
                    ),
                    "timestamp": (
                        utc_now().isoformat()
                    ),
                },
            )

        except ccxt.AuthenticationError as exc:

            self._send_json(
                500,
                {
                    "status": "error",
                    "error_type": (
                        type(exc).__name__
                    ),
                    "message": (
                        "Binance authentication "
                        "failed. Check "
                        "BINANCE_API_KEY, "
                        "BINANCE_API_SECRET "
                        "and Binance API permissions."
                    ),
                    "details": str(
                        exc
                    ),
                    "timestamp": (
                        utc_now().isoformat()
                    ),
                },
            )

        except Exception as exc:

            self._send_json(
                500,
                {
                    "status": "error",
                    "error_type": (
                        type(exc).__name__
                    ),
                    "message": str(
                        exc
                    ),
                    "timestamp": (
                        utc_now().isoformat()
                    ),
                },
            )
```
