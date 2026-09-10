"""Strategy configuration."""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .data import DEFAULT_TIMEFRAME_STACK
from .indicators.killzones import DEFAULT_KILLZONES


@dataclass
class StrategyConfig:
    # Timeframes checked top-down for RSI/VWAP alignment, highest first.
    timeframe_stack: list[str] = field(default_factory=lambda: list(DEFAULT_TIMEFRAME_STACK))
    # The timeframe the entry trigger candle is evaluated on.
    entry_timeframe: str = "5m"

    # VWAP
    vwap_anchor: str = "D"
    vwap_bands: tuple[float, ...] = (1.0, 2.0, 3.0)
    vwap_swing_band: float = 2.0  # which band defines a "swing" extension

    # RSI
    rsi_length: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    rsi_neutral: float = 50.0  # every timeframe must at least be on this side

    # Trendlines
    trendline_pivot_window: int = 3
    trendline_use_last_n: int = 2
    trendline_tolerance_atr_mult: float = 0.25
    trendline_timeframes: list[str] = field(default_factory=lambda: ["1h", "5m"])

    # Killzones (UTC)
    killzones: dict[str, tuple[int, int, int, int]] = field(
        default_factory=lambda: dict(DEFAULT_KILLZONES)
    )

    # Risk / trade management
    risk_per_trade_pct: float = 0.5  # % of equity risked per trade
    atr_length: int = 14
    stop_atr_mult: float = 1.5  # stop = swing extreme +/- this * ATR
    target_r_multiple: float = 2.0  # take profit at this multiple of risk
    max_bars_in_trade: int = 400  # safety time-stop, in entry-timeframe bars

    @staticmethod
    def from_yaml(path: str) -> "StrategyConfig":
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        cfg = StrategyConfig()
        for key, value in raw.items():
            if not hasattr(cfg, key):
                raise ValueError(f"Unknown config key: {key}")
            if key == "killzones" and value:
                value = {k: tuple(v) for k, v in value.items()}
            if key == "vwap_bands" and value:
                value = tuple(value)
            setattr(cfg, key, value)
        return cfg
