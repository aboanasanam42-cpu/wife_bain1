"""
Technical Indicators & Market Analysis Module (Pure Python, No external TA-Lib dependency)
Computes RSI, EMA, Volatility, Spread, and Dip-Rebound Signals.
"""

from typing import List, Tuple, Optional


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calculates Relative Strength Index (RSI). Returns 50.0 if not enough data."""
    if len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Smoothed Wilder moving average
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    """Calculates Exponential Moving Average (EMA)."""
    if len(prices) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p - ema) * multiplier + ema
    return ema


def calculate_volatility_pct(highs: List[float], lows: List[float], current_price: float) -> float:
    """Calculates average high-low range percentage over recent bars."""
    if not highs or not lows or current_price <= 0:
        return 0.0
    count = min(len(highs), len(lows), 10)
    ranges = [(h - l) / current_price * 100.0 for h, l in zip(highs[-count:], lows[-count:])]
    return round(sum(ranges) / len(ranges), 3) if ranges else 0.0


def calculate_dip_and_rebound(
    closes: List[float], current_price: float, lookback: int = 15
) -> Tuple[float, float]:
    """
    Measures:
    1. dip_pct: How much the lowest point in lookback fell from the local swing high (%).
    2. rebound_pct: How much current price has bounced from that recent swing low (%).
    """
    if len(closes) < 5 or current_price <= 0:
        return 0.0, 0.0

    window = closes[-lookback:] if len(closes) >= lookback else closes
    swing_high = max(window)
    swing_low = min(window)

    if swing_high <= 0:
        return 0.0, 0.0

    dip_pct = ((swing_high - swing_low) / swing_high) * 100.0
    rebound_pct = ((current_price - swing_low) / swing_low) * 100.0 if swing_low > 0 else 0.0

    return round(dip_pct, 3), round(rebound_pct, 3)
