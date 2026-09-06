"""Tradovate REST connection: authentication, account state, orders, health.

Covers Setup step 11 (`check-connection`) and Procedure steps 38, 41-49.
Every method that can move money is explicit about it; nothing here trades on
its own.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import Config, TradovateCredentials

log = logging.getLogger(__name__)

TOKEN_CACHE = Path(".tradovate_token.json")
RENEW_MARGIN_SECONDS = 600  # renew when under 10 minutes of validity remains
REQUEST_TIMEOUT_SECONDS = 20


class TradovateError(Exception):
    """Any failure talking to Tradovate."""


class AuthenticationError(TradovateError):
    """Credentials were rejected, or the account is not entitled to API access."""


class PenaltyBoxError(TradovateError):
    """Tradovate is rate-limiting this application and issued a p-ticket.

    Tradovate answers a too-frequent auth request with a ticket and a wait time
    instead of a token. Retrying immediately extends the penalty, so the caller
    must wait `penalty_seconds` before trying again.
    """

    def __init__(self, message: str, penalty_seconds: float) -> None:
        super().__init__(message)
        self.penalty_seconds = penalty_seconds


@dataclass(frozen=True)
class AccessToken:
    token: str
    market_data_token: str
    expires_at: float  # unix seconds

    @property
    def seconds_remaining(self) -> float:
        return self.expires_at - time.time()

    @property
    def needs_renewal(self) -> bool:
        return self.seconds_remaining < RENEW_MARGIN_SECONDS


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    account_type: str
    active: bool


@dataclass(frozen=True)
class AccountSnapshot:
    """What the sizing and circuit-breaker rules read (Procedure steps 38, 41)."""

    equity: float
    realized_pnl: float
    open_pnl: float

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.open_pnl


@dataclass(frozen=True)
class Position:
    id: int
    contract_id: int
    net_position: int

    @property
    def is_open(self) -> bool:
        return self.net_position != 0


def _parse_expiration(raw: str | None) -> float:
    """Tradovate returns ISO-8601 with a trailing Z; fall back to a short window."""
    if not raw:
        return time.time() + 3600
    from datetime import datetime

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        log.warning("Unrecognized token expiration %r; assuming one hour", raw)
        return time.time() + 3600


class TradovateClient:
    """Thread-safe REST client. One instance per running bot."""

    def __init__(
        self,
        config: Config,
        session: requests.Session | None = None,
        token_cache: Path | None = TOKEN_CACHE,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.token_cache = token_cache
        self._token: AccessToken | None = None
        self._account: Account | None = None
        self._lock = threading.RLock()

    # -- transport ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.config.rest_url}/{path.lstrip('/')}"

    def _post(
        self, path: str, payload: dict[str, Any], authenticated: bool = True
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._valid_token().token}"
        return self._send("POST", path, headers, json_body=payload)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._valid_token().token}"}
        return self._send("GET", path, headers, params=params)

    def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self.session.request(
                method,
                self._url(path),
                headers=headers,
                json=json_body,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # The safety loop (Procedure step 49) treats this as loss of the
            # broker connection and flattens.
            raise TradovateError(f"{method} {path} failed: {exc}") from exc

        if response.status_code == 401:
            raise AuthenticationError(f"{method} {path} returned 401 Unauthorized")
        if response.status_code >= 400:
            raise TradovateError(
                f"{method} {path} returned {response.status_code}: {response.text[:400]}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise TradovateError(f"{method} {path} returned non-JSON body") from exc

    # -- authentication ----------------------------------------------------

    def authenticate(self) -> AccessToken:
        """Exchange credentials for an access token (Setup step 11)."""
        with self._lock:
            cached = self._load_cached_token()
            if cached and not cached.needs_renewal:
                self._token = cached
                return cached

            payload = self.config.credentials.as_auth_payload()
            body = self._send(
                "POST",
                "/auth/accesstokenrequest",
                {"Content-Type": "application/json"},
                json_body=payload,
            )
            token = self._token_from_response(body)
            self._token = token
            self._store_token(token)
            log.info(
                "Authenticated to Tradovate %s; token valid for %.0f minutes",
                self.config.environment,
                token.seconds_remaining / 60,
            )
            return token

    def _token_from_response(self, body: Any) -> AccessToken:
        if not isinstance(body, dict):
            raise AuthenticationError("Malformed auth response")

        if body.get("p-ticket"):
            penalty = float(body.get("p-time") or 60)
            raise PenaltyBoxError(
                f"Tradovate issued a penalty ticket; wait {penalty:.0f}s before retrying. "
                "This means auth requests were sent too frequently.",
                penalty_seconds=penalty,
            )
        if body.get("errorText"):
            raise AuthenticationError(str(body["errorText"]))

        access_token = body.get("accessToken")
        if not access_token:
            raise AuthenticationError(
                "Auth response contained no accessToken. Confirm API access is "
                "enabled for this account and that TRADOVATE_ENV matches it."
            )
        return AccessToken(
            token=access_token,
            market_data_token=body.get("mdAccessToken") or access_token,
            expires_at=_parse_expiration(body.get("expirationTime")),
        )

    def _valid_token(self) -> AccessToken:
        with self._lock:
            if self._token is None:
                return self.authenticate()
            if not self._token.needs_renewal:
                return self._token
            return self._renew()

    def _renew(self) -> AccessToken:
        with self._lock:
            current = self._token
            if current is None:
                return self.authenticate()
            try:
                body = self._send(
                    "POST",
                    "/auth/renewaccesstoken",
                    {"Authorization": f"Bearer {current.token}"},
                )
                token = self._token_from_response(body)
            except TradovateError as exc:
                log.warning("Token renewal failed (%s); re-authenticating", exc)
                self._token = None
                self._clear_cached_token()
                return self.authenticate()
            self._token = token
            self._store_token(token)
            return token

    def _load_cached_token(self) -> AccessToken | None:
        if self.token_cache is None or not self.token_cache.is_file():
            return None
        try:
            data = json.loads(self.token_cache.read_text())
            return AccessToken(
                token=data["token"],
                market_data_token=data["market_data_token"],
                expires_at=float(data["expires_at"]),
            )
        except (ValueError, KeyError, OSError):
            return None

    def _store_token(self, token: AccessToken) -> None:
        if self.token_cache is None:
            return
        try:
            self.token_cache.write_text(
                json.dumps(
                    {
                        "token": token.token,
                        "market_data_token": token.market_data_token,
                        "expires_at": token.expires_at,
                    }
                )
            )
            self.token_cache.chmod(0o600)
        except OSError as exc:
            log.warning("Could not cache token: %s", exc)

    def _clear_cached_token(self) -> None:
        if self.token_cache is not None:
            self.token_cache.unlink(missing_ok=True)

    # -- account state -----------------------------------------------------

    def list_accounts(self) -> list[Account]:
        body = self._get("/account/list") or []
        return [
            Account(
                id=int(item["id"]),
                name=str(item.get("name", "")),
                account_type=str(item.get("accountType", "")),
                active=bool(item.get("active", True)),
            )
            for item in body
        ]

    def account(self) -> Account:
        """Resolve the trading account once, then reuse it (Setup step 11)."""
        with self._lock:
            if self._account is not None:
                return self._account

            accounts = [a for a in self.list_accounts() if a.active]
            if not accounts:
                raise TradovateError("No active Tradovate accounts on these credentials")

            if self.config.account_spec:
                matches = [a for a in accounts if a.name == self.config.account_spec]
                if not matches:
                    names = ", ".join(a.name for a in accounts)
                    raise TradovateError(
                        f"TRADOVATE_ACCOUNT_SPEC={self.config.account_spec!r} matched "
                        f"no active account. Available: {names}"
                    )
                self._account = matches[0]
            elif len(accounts) > 1:
                names = ", ".join(a.name for a in accounts)
                raise TradovateError(
                    f"{len(accounts)} active accounts found ({names}). Set "
                    "TRADOVATE_ACCOUNT_SPEC so the bot cannot trade the wrong one."
                )
            else:
                self._account = accounts[0]

            return self._account

    def snapshot(self) -> AccountSnapshot:
        """Equity and P&L, for position sizing and the circuit breaker."""
        body = self._post(
            "/cashBalance/getcashbalancesnapshot", {"accountId": self.account().id}
        )
        if not isinstance(body, dict):
            raise TradovateError("Malformed cash balance snapshot")
        return AccountSnapshot(
            equity=float(body.get("totalCashValue") or 0.0),
            realized_pnl=float(body.get("realizedPnL") or 0.0),
            open_pnl=float(body.get("openPnL") or 0.0),
        )

    def open_positions(self) -> list[Position]:
        """Non-flat positions on the configured account (Procedure step 42)."""
        account_id = self.account().id
        body = self._get("/position/list") or []
        positions = [
            Position(
                id=int(item["id"]),
                contract_id=int(item["contractId"]),
                net_position=int(item.get("netPos") or 0),
            )
            for item in body
            if int(item.get("accountId", -1)) == account_id
        ]
        return [p for p in positions if p.is_open]

    def find_contract_id(self, symbol: str) -> int:
        body = self._get("/contract/find", {"name": symbol})
        if not isinstance(body, dict) or "id" not in body:
            raise TradovateError(f"No contract found for symbol {symbol!r}")
        return int(body["id"])

    # -- orders ------------------------------------------------------------

    def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_price: float,
        target_price: float,
    ) -> dict[str, Any]:
        """Submit entry plus attached stop and target (Procedure step 43).

        `action` is "Buy" or "Sell"; the brackets take the opposite side.
        """
        if action not in ("Buy", "Sell"):
            raise ValueError(f"action must be 'Buy' or 'Sell', got {action!r}")
        if quantity < 1:
            raise ValueError("quantity must be at least 1 contract")

        exit_action = "Sell" if action == "Buy" else "Buy"
        account = self.account()
        payload = {
            "accountSpec": account.name,
            "accountId": account.id,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Market",
            "isAutomated": True,
            "bracket1": {
                "action": exit_action,
                "orderType": "Limit",
                "price": target_price,
                "timeInForce": "GTC",
            },
            "bracket2": {
                "action": exit_action,
                "orderType": "Stop",
                "stopPrice": stop_price,
                "timeInForce": "GTC",
            },
        }
        body = self._post("/order/placeOSO", payload)
        if isinstance(body, dict) and body.get("failureReason"):
            raise TradovateError(
                f"Order rejected: {body.get('failureReason')} "
                f"{body.get('failureText', '')}".strip()
            )
        return body if isinstance(body, dict) else {}

    def flatten(self, reason: str) -> list[dict[str, Any]]:
        """Close every open position at market (Procedure steps 47 and 49).

        This is the fail-safe path: it is called when the feed or the broker
        connection cannot be trusted, so it liquidates rather than reasoning
        about what the position should be.
        """
        results: list[dict[str, Any]] = []
        account_id = self.account().id
        for position in self.open_positions():
            log.warning(
                "Flattening position %s (net %+d) — reason: %s",
                position.id,
                position.net_position,
                reason,
            )
            results.append(
                self._post(
                    "/order/liquidateposition",
                    {
                        "accountId": account_id,
                        "contractId": position.contract_id,
                        "admin": False,
                    },
                )
                or {}
            )
        return results

    # -- health ------------------------------------------------------------

    def health_check(self) -> bool:
        """Broker-side half of the heartbeat (Procedure step 48)."""
        try:
            self._get("/account/list")
            return True
        except TradovateError as exc:
            log.error("Broker health check failed: %s", exc)
            return False
