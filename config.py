"""
Binance Spot 24/7 Scalper Bot Configuration
Handles environment variables, validation, and symbol formatting for Spot trading.
"""

import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback to standard library .env parser if python-dotenv is not installed
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, "").strip().lower()
    if val in ("true", "1", "yes", "t", "on"):
        return True
    if val in ("false", "0", "no", "f", "off"):
        return False
    return default


def get_env_float(key: str, default: float) -> float:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def mask_key(key: Optional[str]) -> str:
    """Mask sensitive API key strings for safe diagnostic logging."""
    if not key or key.strip() in ("", "your_binance_api_key_here", "your_api_key"):
        return "NOT_SET"
    k = key.strip()
    if len(k) <= 8:
        return f"{k[:2]}...{k[-2:]} (len: {len(k)})"
    return f"{k[:4]}...{k[-4:]} (len: {len(k)})"


class Config:
    # -------------------------------------------------------------
    # API Credentials & Execution Mode (Binance Spot)
    # -------------------------------------------------------------
    API_KEY: str = os.getenv("BINANCE_API_KEY", "").strip()
    API_SECRET: str = os.getenv("BINANCE_API_SECRET", "").strip()
    LIVE_TRADING: bool = get_env_bool("LIVE_TRADING", False)
    TESTNET: bool = get_env_bool("TESTNET", False)
    BINANCE_PROXY: Optional[str] = os.getenv("BINANCE_PROXY", "").strip() or None

    # -------------------------------------------------------------
    # Spot Trading Pair & Sizing
    # -------------------------------------------------------------
    RAW_SYMBOL: str = os.getenv("SYMBOL", "BTC/USDT").strip().upper()

    @classmethod
    def get_spot_symbol(cls) -> str:
        """
        Normalize symbol to standard CCXT Spot format: 'BTC/USDT'
        Accepts: BTCUSDT, BTC/USDT, BTC_USDT, BTC-USDT
        """
        sym = cls.RAW_SYMBOL.replace("-", "/").replace("_", "/").replace(":", "/")
        if "/" in sym:
            parts = sym.split("/")
            return f"{parts[0]}/{parts[1]}"
        if sym.endswith("USDT"):
            return f"{sym[:-4]}/USDT"
        if sym.endswith("BUSD"):
            return f"{sym[:-4]}/BUSD"
        if sym.endswith("FDUSD"):
            return f"{sym[:-5]}/FDUSD"
        return f"{sym}/USDT"

    @classmethod
    def get_base_quote(cls) -> tuple[str, str]:
        sym = cls.get_spot_symbol()
        base, quote = sym.split("/")
        return base, quote

    @classmethod
    def get_binance_raw_symbol(cls) -> str:
        """Returns raw exchange symbol like BTCUSDT"""
        return cls.get_spot_symbol().replace("/", "")

    # Target order notional in quote currency (USDT) - automatically enforced >= $10.0 for Binance Spot
    _raw_target_usd = get_env_float("TARGET_ORDER_USD", 11.0)
    TARGET_ORDER_USD: float = max(10.5, _raw_target_usd) if _raw_target_usd > 0 else 11.0
    MAX_POSITIONS: int = get_env_int("MAX_POSITIONS", 1)

    # -------------------------------------------------------------
    # Timing & Frequency (Real-time scalping loop)
    # -------------------------------------------------------------
    LOOP_INTERVAL_SEC: float = get_env_float("LOOP_INTERVAL_SEC", 5.0)
    BUY_COOLDOWN_SEC: int = get_env_int("BUY_COOLDOWN_SEC", 60)

    # -------------------------------------------------------------
    # Entry Strategy: Confirmed Dip + Rebound + RSI Momentum
    # -------------------------------------------------------------
    BUY_DIP_MIN_PCT: float = get_env_float("BUY_DIP_MIN_PCT", 0.25)
    BUY_REBOUND_CONFIRM_PCT: float = get_env_float("BUY_REBOUND_CONFIRM_PCT", 0.08)
    BUY_RSI_MAX: float = get_env_float("BUY_RSI_MAX", 48.0)
    MIN_VOLATILITY_PCT: float = get_env_float("MIN_VOLATILITY_PCT", 0.20)
    MAX_SPREAD_PCT: float = get_env_float("MAX_SPREAD_PCT", 0.15)

    # -------------------------------------------------------------
    # Exit Strategy: Trailing Take-Profit & Capital Protection
    # -------------------------------------------------------------
    TRAILING_STOP_ENABLED: bool = get_env_bool("TRAILING_STOP_ENABLED", True)
    TRAILING_ACTIVATION_PCT: float = get_env_float("TRAILING_ACTIVATION_PCT", 0.35)
    TRAILING_CALLBACK_PCT: float = get_env_float("TRAILING_CALLBACK_PCT", 0.15)
    STOP_LOSS_PCT: float = get_env_float("STOP_LOSS_PCT", 0.80)
    MAX_HOLD_TIME_SEC: int = get_env_int("MAX_HOLD_TIME_SEC", 1200)
    STAGNANT_EXIT_PCT: float = get_env_float("STAGNANT_EXIT_PCT", 0.10)

    # -------------------------------------------------------------
    # Network, Dashboard & State
    # -------------------------------------------------------------
    PORT: int = get_env_int("PORT", 8080)
    STATE_FILE: str = os.getenv("STATE_FILE", "spot_state.json")

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if cls.TARGET_ORDER_USD < 5.0:
            errors.append(f"TARGET_ORDER_USD ({cls.TARGET_ORDER_USD}) is below Binance Spot minNotional ($5). Recommended >= $10.")
        if cls.LOOP_INTERVAL_SEC < 1.0:
            errors.append("LOOP_INTERVAL_SEC must be >= 1.0 second.")
        if cls.STOP_LOSS_PCT <= 0:
            errors.append("STOP_LOSS_PCT must be > 0.")
        if cls.TRAILING_ACTIVATION_PCT <= cls.TRAILING_CALLBACK_PCT:
            errors.append("TRAILING_ACTIVATION_PCT should be strictly greater than TRAILING_CALLBACK_PCT.")
        if cls.LIVE_TRADING:
            if not cls.API_KEY or cls.API_KEY in ("your_binance_api_key_here", "NOT_SET"):
                errors.append("LIVE_TRADING is True, but BINANCE_API_KEY is missing or invalid.")
            if not cls.API_SECRET or cls.API_SECRET in ("your_binance_api_secret_here", "NOT_SET"):
                errors.append("LIVE_TRADING is True, but BINANCE_API_SECRET is missing or invalid.")
        return errors
