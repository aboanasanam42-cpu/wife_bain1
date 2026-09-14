#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Binance Spot Cloud Trading Bot
BTC/USDT by default.

IMPORTANT:
LIVE_TRADING=false by default.
Never place real orders unless LIVE_TRADING=true is explicitly configured.
"""

import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import ccxt
from dotenv import load_dotenv


# ============================================================
# 1. Environment
# ============================================================

load_dotenv()


def sanitize_key(value: str | None) -> str:
    """Clean API keys copied into environment variables."""
    if not value:
        return ""

    cleaned = value.strip()

    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()

    return "".join(
        char for char in cleaned
        if char.isprintable() and not char.isspace()
    )


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default)).strip()

    try:
        return float(value)
    except ValueError:
        logging.getLogger("BinanceSpotBot").warning(
            "Invalid value for %s=%r. Using default %s.",
            name,
            value,
            default,
        )
        return float(default)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()

    try:
        return int(value)
    except ValueError:
        logging.getLogger("BinanceSpotBot").warning(
            "Invalid value for %s=%r. Using default %s.",
            name,
            value,
            default,
        )
        return int(default)


API_KEY = sanitize_key(
    os.getenv("BINANCE_API_KEY")
    or os.getenv("BINANCE_KEY")
)

API_SECRET = sanitize_key(
    os.getenv("BINANCE_API_SECRET")
    or os.getenv("BINANCE_SECRET")
)

SYMBOL = os.getenv("SYMBOL", "BTC/USDT").strip()

TARGET_ORDER_USD = max(
    0.0,
    env_float("TARGET_ORDER_USD", 5.5),
)

LIVE_TRADING = env_bool("LIVE_TRADING", False)

MAX_POSITIONS = max(
    1,
    env_int("MAX_POSITIONS", 1),
)

LOOP_INTERVAL_SEC = max(
    3,
    env_int("LOOP_INTERVAL_SEC", 10),
)

BUY_COOLDOWN_SEC = max(
    0,
    env_int("BUY_COOLDOWN_SEC", 30),
)

BUY_DIP_MIN_PCT = max(
    0.0,
    env_float("BUY_DIP_MIN_PCT", 0.25),
)

BUY_REBOUND_CONFIRM_PCT = max(
    0.0,
    env_float("BUY_REBOUND_CONFIRM_PCT", 0.08),
)

BUY_RSI_MAX = min(
    100.0,
    max(0.0, env_float("BUY_RSI_MAX", 48.0)),
)

MIN_VOLATILITY_PCT = max(
    0.0,
    env_float("MIN_VOLATILITY_PCT", 0.20),
)

MAX_SPREAD_PCT = max(
    0.0,
    env_float("MAX_SPREAD_PCT", 0.15),
)

TRAILING_STOP_ENABLED = env_bool(
    "TRAILING_STOP_ENABLED",
    True,
)

TRAILING_ACTIVATION_PCT = max(
    0.0,
    env_float("TRAILING_ACTIVATION_PCT", 0.15),
)

TRAILING_CALLBACK_PCT = max(
    0.0,
    env_float("TRAILING_CALLBACK_PCT", 0.20),
)

STOP_LOSS_PCT = max(
    0.01,
    env_float("STOP_LOSS_PCT", 0.40),
)

MAX_HOLD_TIME_SEC = max(
    0,
    env_int("MAX_HOLD_TIME_SEC", 1200),
)

STAGNANT_EXIT_PCT = env_float(
    "STAGNANT_EXIT_PCT",
    0.0,
)

POSITIONS_FILE = os.getenv(
    "POSITIONS_FILE",
    "positions.json",
)


# ============================================================
# 2. Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("BinanceSpotBot")


# ============================================================
# 3. Public IP
# ============================================================

def print_public_ip() -> None:
    """
    Display the current public IP.
    Useful when Binance API restrictions use IP whitelisting.
    """
    try:
        request = urllib.request.Request(
            "https://api.ipify.org",
            headers={
                "User-Agent": "BinanceSpotBot/1.0",
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=5,
        ) as response:
            public_ip = response.read().decode(
                "utf-8",
                errors="replace",
            ).strip()

        if public_ip:
            logger.info("MY_CURRENT_IP: %s", public_ip)

    except Exception as error:
        logger.warning(
            "Could not fetch public IP: %s",
            error,
        )


# ============================================================
# 4. API validation
# ============================================================

def check_api_keys() -> None:
    """Validate required Binance API credentials."""
    if not API_KEY or not API_SECRET:
        logger.error("=" * 70)
        logger.error(
            "BINANCE API credentials are missing."
        )
        logger.error(
            "Required environment variables:"
        )
        logger.error(
            "BINANCE_API_KEY or BINANCE_KEY"
        )
        logger.error(
            "BINANCE_API_SECRET or BINANCE_SECRET"
        )
        logger.error("=" * 70)

        raise RuntimeError(
            "Missing Binance API credentials."
        )


# ============================================================
# 5. Position persistence
# ============================================================

def load_positions() -> list[dict]:
    """Load locally persisted positions."""
    if not os.path.exists(POSITIONS_FILE):
        return []

    try:
        with open(
            POSITIONS_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, list):
            logger.warning(
                "%s does not contain a position list.",
                POSITIONS_FILE,
            )
            return []

        valid_positions = []

        for position in data:
            if not isinstance(position, dict):
                continue

            try:
                float(position["entry_price"])
                float(position["amount"])
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid saved position: %r",
                    position,
                )
                continue

            valid_positions.append(position)

        return valid_positions

    except (OSError, json.JSONDecodeError) as error:
        logger.warning(
            "Could not read %s: %s",
            POSITIONS_FILE,
            error,
        )

        return []


def save_positions(positions: list[dict]) -> None:
    """Atomically save positions to disk."""
    temporary_file = f"{POSITIONS_FILE}.tmp"

    try:
        with open(
            temporary_file,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                positions,
                file,
                indent=2,
                ensure_ascii=False,
            )

        os.replace(
            temporary_file,
            POSITIONS_FILE,
        )

    except OSError as error:
        logger.error(
            "Could not save positions: %s",
            error,
        )

        try:
            if os.path.exists(temporary_file):
                os.remove(temporary_file)
        except OSError:
            pass


# ============================================================
# 6. Binance connection
# ============================================================

def init_exchange() -> ccxt.binance:
    """Create authenticated Binance Spot exchange."""
    check_api_keys()

    exchange = ccxt.binance(
        {
            "apiKey": API_KEY,
            "secret": API_SECRET,
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {
                "defaultType": "spot",
                "adjustForTimeDifference": True,
            },
        }
    )

    return exchange


# ============================================================
# 7. Market helpers
# ============================================================

def get_min_notional(market: dict) -> float:
    """
    Determine the minimum order cost accepted by Binance.
    """
    default_minimum = 5.0

    try:
        limits = market.get("limits", {})
        cost_limits = limits.get("cost", {})

        cost_min = cost_limits.get("min")

        if cost_min is not None:
            return float(cost_min)

        filters = market.get(
            "info",
            {},
        ).get(
            "filters",
            [],
        )

        for item in filters:
            filter_type = item.get("filterType")

            if filter_type in {
                "NOTIONAL",
                "MIN_NOTIONAL",
            }:
                value = (
                    item.get("minNotional")
                    or item.get("notional")
                )

                if value is not None:
                    return float(value)

    except (
        TypeError,
        ValueError,
        AttributeError,
    ) as error:
        logger.warning(
            "Could not determine minNotional: %s",
            error,
        )

    return default_minimum


def get_amount_minimum(market: dict) -> float:
    """Return the minimum order amount if available."""
    try:
        amount_min = (
            market
            .get("limits", {})
            .get("amount", {})
            .get("min")
        )

        if amount_min is not None:
            return float(amount_min)

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        pass

    return 0.0


# ============================================================
# 8. RSI
# ============================================================

def calculate_rsi(
    closes: list[float],
    period: int = 14,
) -> float:
    """Calculate RSI using the latest period."""
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for index in range(1, len(closes)):
        difference = (
            closes[index]
            - closes[index - 1]
        )

        if difference > 0:
            gains.append(difference)
            losses.append(0.0)

        else:
            gains.append(0.0)
            losses.append(abs(difference))

    recent_gains = gains[-period:]
    recent_losses = losses[-period:]

    average_gain = sum(recent_gains) / period
    average_loss = sum(recent_losses) / period

    if average_loss == 0:
        if average_gain == 0:
            return 50.0

        return 100.0

    relative_strength = (
        average_gain / average_loss
    )

    return 100.0 - (
        100.0 / (1.0 + relative_strength)
    )


# ============================================================
# 9. Order helpers
# ============================================================

def execute_market_sell(
    exchange: ccxt.binance,
    amount: float,
    reason: str,
    current_price: float,
    entry_price: float,
) -> tuple[bool, float, str]:
    """
    Sell a position.
    Returns:
        success, execution_price, order_id
    """
    try:
        sell_amount = float(
            exchange.amount_to_precision(
                SYMBOL,
                amount,
            )
        )

        if sell_amount <= 0:
            raise ValueError(
                "Calculated sell amount is zero."
            )

        if LIVE_TRADING:
            order = exchange.create_market_sell_order(
                SYMBOL,
                sell_amount,
            )

            execution_price = float(
                order.get("average")
                or order.get("price")
                or current_price
            )

            order_id = str(
                order.get("id")
                or "unknown"
            )

        else:
            execution_price = current_price
            order_id = (
                f"sim_sell_"
                f"{reason}_"
                f"{int(time.time())}"
            )

        pnl_pct = (
            (execution_price - entry_price)
            / entry_price
            * 100.0
        )

        logger.info(
            "SELL %s | order=%s | price=%.8f | PnL=%+.3f%% | mode=%s",
            reason,
            order_id,
            execution_price,
            pnl_pct,
            "LIVE" if LIVE_TRADING else "SIMULATION",
        )

        return (
            True,
            execution_price,
            order_id,
        )

    except Exception as error:
        logger.error(
            "Sell failed (%s): %s",
            reason,
            error,
            exc_info=True,
        )

        return (
            False,
            current_price,
            "",
        )


# ============================================================
# 10. Main trading loop
# ============================================================

def main() -> None:

    logger.info("=" * 70)
    logger.info(
        "Starting Binance Spot Cloud Trading Bot"
    )
    logger.info(
        "Symbol: %s",
        SYMBOL,
    )
    logger.info(
        "Trading mode: %s",
        "LIVE" if LIVE_TRADING else "SIMULATION",
    )
    logger.info(
        "Target order: %.2f USDT",
        TARGET_ORDER_USD,
    )
    logger.info(
        "Max positions: %d",
        MAX_POSITIONS,
    )
    logger.info("=" * 70)

    print_public_ip()

    exchange = init_exchange()

    # --------------------------------------------------------
    # Load markets
    # --------------------------------------------------------

    try:
        markets = exchange.load_markets()

        if SYMBOL not in markets:
            raise RuntimeError(
                f"{SYMBOL} is not available on Binance Spot."
            )

        market = markets[SYMBOL]

        if not market.get("spot", True):
            raise RuntimeError(
                f"{SYMBOL} is not configured as a Spot market."
            )

        min_notional = get_min_notional(
            market
        )

        amount_minimum = get_amount_minimum(
            market
        )

        logger.info(
            "Market validated: %s",
            SYMBOL,
        )

        logger.info(
            "Minimum order cost: %.8f USDT",
            min_notional,
        )

        logger.info(
            "Minimum amount: %.12f",
            amount_minimum,
        )

    except Exception as error:
        logger.error(
            "Could not initialize Binance markets: %s",
            error,
            exc_info=True,
        )
        raise

    positions = load_positions()

    logger.info(
        "Loaded %d saved position(s).",
        len(positions),
    )

    last_buy_timestamp = 0.0

    # ========================================================
    # Continuous loop
    # ========================================================

    while True:

        try:
            now_ts = time.time()

            # ------------------------------------------------
            # 1. Ticker
            # ------------------------------------------------

            ticker = exchange.fetch_ticker(
                SYMBOL
            )

            current_price = float(
                ticker.get("last") or 0.0
            )

            bid_price = float(
                ticker.get("bid")
                or current_price
            )

            ask_price = float(
                ticker.get("ask")
                or current_price
            )

            if current_price <= 0:
                raise RuntimeError(
                    "Binance returned an invalid current price."
                )

            spread_pct = 0.0

            if bid_price > 0 and ask_price > 0:
                spread_pct = (
                    (ask_price - bid_price)
                    / current_price
                    * 100.0
                )

            # ------------------------------------------------
            # 2. Balance
            # ------------------------------------------------

            balance = exchange.fetch_balance()

            free_balances = balance.get(
                "free",
                {},
            )

            free_usdt = float(
                free_balances.get(
                    "USDT",
                    0.0,
                )
                or 0.0
            )

            base_currency = SYMBOL.split(
                "/"
            )[0]

            free_base = float(
                free_balances.get(
                    base_currency,
                    0.0,
                )
                or 0.0
            )

            total_usdt_estimate = (
                free_usdt
                + (
                    free_base
                    * current_price
                )
            )

            logger.info(
                "PRICE=%s | spread=%.3f%% | "
                "free_USDT=%.4f | %s=%.8f | "
                "estimated_total=%.2f",
                f"${current_price:,.2f}",
                spread_pct,
                free_usdt,
                base_currency,
                free_base,
                total_usdt_estimate,
            )

            # ------------------------------------------------
            # 3. Manage existing positions
            # ------------------------------------------------

            remaining_positions = []

            for index, position in enumerate(
                positions,
                start=1,
            ):

                try:
                    entry_price = float(
                        position["entry_price"]
                    )

                    amount = float(
                        position["amount"]
                    )

                    created_at_ts = float(
                        position.get(
                            "created_at_ts",
                            now_ts,
                        )
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:

                    logger.error(
                        "Invalid position #%d: %s",
                        index,
                        error,
                    )

                    continue

                if entry_price <= 0 or amount <= 0:
                    logger.error(
                        "Invalid position #%d values.",
                        index,
                    )
                    continue

                highest_price = max(
                    float(
                        position.get(
                            "highest_price",
                            entry_price,
                        )
                    ),
                    entry_price,
                )

                trailing_active = bool(
                    position.get(
                        "trailing_active",
                        False,
                    )
                )

                if current_price > highest_price:
                    highest_price = current_price

                position["highest_price"] = (
                    highest_price
                )

                pnl_pct = (
                    (current_price - entry_price)
                    / entry_price
                    * 100.0
                )

                peak_gain_pct = (
                    (highest_price - entry_price)
                    / entry_price
                    * 100.0
                )

                drop_from_peak_pct = 0.0

                if highest_price > 0:
                    drop_from_peak_pct = (
                        (highest_price - current_price)
                        / highest_price
      
