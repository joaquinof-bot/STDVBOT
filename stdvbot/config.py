"""Configuration loaded from the environment (Setup steps 4-13)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENVIRONMENTS = {
    "demo": {
        "rest": "https://demo.tradovateapi.com/v1",
        "websocket": "wss://demo.tradovateapi.com/v1/websocket",
    },
    "live": {
        "rest": "https://live.tradovateapi.com/v1",
        "websocket": "wss://live.tradovateapi.com/v1/websocket",
    },
}

MARKET_DATA_WEBSOCKET = "wss://md.tradovateapi.com/v1/websocket"

ARMS = ("regime_gated", "permissive", "random_control")


class ConfigError(Exception):
    """Raised when the environment is missing or contradicts required settings."""


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from `path` into os.environ without overwriting."""
    dotenv = Path(path)
    if not dotenv.is_file():
        return
    for raw in dotenv.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class TradovateCredentials:
    """The six values recorded in Setup step 3, plus the device identifier."""

    username: str
    password: str
    app_id: str
    app_version: str
    cid: str
    sec: str
    device_id: str

    def as_auth_payload(self) -> dict[str, str]:
        return {
            "name": self.username,
            "password": self.password,
            "appId": self.app_id,
            "appVersion": self.app_version,
            "cid": self.cid,
            "sec": self.sec,
            "deviceId": self.device_id,
        }

    def __repr__(self) -> str:  # never leak secrets into logs or tracebacks
        return f"TradovateCredentials(username={self.username!r}, app_id={self.app_id!r}, ...)"


@dataclass(frozen=True)
class Config:
    environment: str
    credentials: TradovateCredentials
    account_spec: str | None

    symbol: str
    risk_per_trade_pct: float
    max_concurrent_positions: int
    daily_loss_limit_pct: float
    confluence_threshold: int
    stagnant_cutoff_minutes: int

    vwap_tolerance_ticks: int
    round_number_tolerance_ticks: int
    poi_tolerance_ticks: int

    heartbeat_interval_seconds: int
    feed_stale_seconds: int

    arm: str
    random_seed: int

    @property
    def rest_url(self) -> str:
        return ENVIRONMENTS[self.environment]["rest"]

    @property
    def websocket_url(self) -> str:
        return ENVIRONMENTS[self.environment]["websocket"]

    @property
    def is_simulation(self) -> bool:
        return self.environment == "demo"


def load_config(dotenv_path: str | Path = ".env") -> Config:
    """Build a Config from .env plus the process environment."""
    load_dotenv(dotenv_path)

    environment = os.environ.get("TRADOVATE_ENV", "demo").strip().lower()
    if environment not in ENVIRONMENTS:
        raise ConfigError(
            f"TRADOVATE_ENV must be one of {sorted(ENVIRONMENTS)}, got {environment!r}"
        )

    arm = os.environ.get("STDVBOT_ARM", "regime_gated").strip().lower()
    if arm not in ARMS:
        raise ConfigError(f"STDVBOT_ARM must be one of {list(ARMS)}, got {arm!r}")

    credentials = TradovateCredentials(
        username=_require("TRADOVATE_USERNAME"),
        password=_require("TRADOVATE_PASSWORD"),
        app_id=os.environ.get("TRADOVATE_APP_ID", "STDVBOT").strip() or "STDVBOT",
        app_version=os.environ.get("TRADOVATE_APP_VERSION", "1.0").strip() or "1.0",
        cid=_require("TRADOVATE_CID"),
        sec=_require("TRADOVATE_SEC"),
        device_id=_require("TRADOVATE_DEVICE_ID"),
    )

    risk_per_trade_pct = _float("STDVBOT_RISK_PER_TRADE_PCT", 1.0)
    daily_loss_limit_pct = _float("STDVBOT_DAILY_LOSS_LIMIT_PCT", 3.0)
    if not 0 < risk_per_trade_pct <= 100:
        raise ConfigError("STDVBOT_RISK_PER_TRADE_PCT must be between 0 and 100")
    if not 0 < daily_loss_limit_pct <= 100:
        raise ConfigError("STDVBOT_DAILY_LOSS_LIMIT_PCT must be between 0 and 100")
    if risk_per_trade_pct > daily_loss_limit_pct:
        raise ConfigError(
            "Risk per trade exceeds the daily loss limit, so the circuit breaker "
            "could trip on a single trade. Lower STDVBOT_RISK_PER_TRADE_PCT."
        )

    account_spec = os.environ.get("TRADOVATE_ACCOUNT_SPEC", "").strip() or None

    return Config(
        environment=environment,
        credentials=credentials,
        account_spec=account_spec,
        symbol=os.environ.get("STDVBOT_SYMBOL", "MNQ").strip().upper(),
        risk_per_trade_pct=risk_per_trade_pct,
        max_concurrent_positions=_int("STDVBOT_MAX_CONCURRENT_POSITIONS", 1),
        daily_loss_limit_pct=daily_loss_limit_pct,
        confluence_threshold=_int("STDVBOT_CONFLUENCE_THRESHOLD", 2),
        stagnant_cutoff_minutes=_int("STDVBOT_STAGNANT_CUTOFF_MINUTES", 30),
        vwap_tolerance_ticks=_int("STDVBOT_VWAP_TOLERANCE_TICKS", 8),
        round_number_tolerance_ticks=_int("STDVBOT_ROUND_NUMBER_TOLERANCE_TICKS", 4),
        poi_tolerance_ticks=_int("STDVBOT_POI_TOLERANCE_TICKS", 8),
        heartbeat_interval_seconds=_int("STDVBOT_HEARTBEAT_INTERVAL_SECONDS", 15),
        feed_stale_seconds=_int("STDVBOT_FEED_STALE_SECONDS", 90),
        arm=arm,
        random_seed=_int("STDVBOT_RANDOM_SEED", 1337),
    )
