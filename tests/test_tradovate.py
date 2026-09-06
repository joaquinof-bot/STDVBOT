import json
import unittest
from unittest.mock import Mock

from stdvbot.config import Config, TradovateCredentials
from stdvbot.tradovate import (
    AuthenticationError,
    PenaltyBoxError,
    TradovateClient,
    TradovateError,
)

CREDENTIALS = TradovateCredentials(
    username="student",
    password="pw",
    app_id="STDVBOT",
    app_version="1.0",
    cid="123",
    sec="abc",
    device_id="d-1",
)

CONFIG = Config(
    environment="demo",
    credentials=CREDENTIALS,
    account_spec=None,
    symbol="MNQ",
    risk_per_trade_pct=1.0,
    max_concurrent_positions=1,
    daily_loss_limit_pct=3.0,
    confluence_threshold=2,
    stagnant_cutoff_minutes=30,
    vwap_tolerance_ticks=8,
    round_number_tolerance_ticks=4,
    poi_tolerance_ticks=8,
    heartbeat_interval_seconds=15,
    feed_stale_seconds=90,
    arm="regime_gated",
    random_seed=1337,
)


def response(payload, status=200):
    reply = Mock()
    reply.status_code = status
    reply.content = json.dumps(payload).encode()
    reply.text = json.dumps(payload)
    reply.json.return_value = payload
    return reply


class FakeSession:
    """Records requests and replays queued responses in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.replies:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self.replies.pop(0)


def client(replies):
    return TradovateClient(CONFIG, session=FakeSession(replies), token_cache=None)


TOKEN = {
    "accessToken": "tok",
    "mdAccessToken": "md",
    "expirationTime": "2099-01-01T00:00:00.000Z",
}


class AuthTests(unittest.TestCase):
    def test_authenticate_stores_both_tokens(self):
        c = client([response(TOKEN)])
        token = c.authenticate()
        self.assertEqual(token.token, "tok")
        self.assertEqual(token.market_data_token, "md")
        self.assertFalse(token.needs_renewal)

    def test_authenticate_targets_the_demo_host(self):
        c = client([response(TOKEN)])
        c.authenticate()
        _, url, _ = c.session.calls[0]
        self.assertTrue(url.startswith("https://demo.tradovateapi.com/v1"))

    def test_penalty_ticket_raises_with_the_wait_time(self):
        c = client([response({"p-ticket": "t", "p-time": 45})])
        with self.assertRaises(PenaltyBoxError) as ctx:
            c.authenticate()
        self.assertEqual(ctx.exception.penalty_seconds, 45)

    def test_error_text_becomes_an_authentication_error(self):
        c = client([response({"errorText": "Invalid credentials"})])
        with self.assertRaises(AuthenticationError):
            c.authenticate()

    def test_missing_token_is_reported_clearly(self):
        c = client([response({})])
        with self.assertRaises(AuthenticationError) as ctx:
            c.authenticate()
        self.assertIn("accessToken", str(ctx.exception))


class AccountTests(unittest.TestCase):
    def test_single_active_account_is_selected(self):
        c = client([
            response(TOKEN),
            response([{"id": 7, "name": "DEMO7", "accountType": "Customer", "active": True}]),
        ])
        self.assertEqual(c.account().id, 7)

    def test_multiple_accounts_refuse_to_guess(self):
        c = client([
            response(TOKEN),
            response([
                {"id": 7, "name": "DEMO7", "active": True},
                {"id": 8, "name": "DEMO8", "active": True},
            ]),
        ])
        with self.assertRaises(TradovateError) as ctx:
            c.account()
        self.assertIn("TRADOVATE_ACCOUNT_SPEC", str(ctx.exception))

    def test_inactive_accounts_are_ignored(self):
        c = client([
            response(TOKEN),
            response([
                {"id": 7, "name": "OLD", "active": False},
                {"id": 8, "name": "DEMO8", "active": True},
            ]),
        ])
        self.assertEqual(c.account().name, "DEMO8")

    def test_snapshot_reads_equity_and_pnl(self):
        c = client([
            response(TOKEN),
            response([{"id": 7, "name": "DEMO7", "active": True}]),
            response({"totalCashValue": 50000.0, "realizedPnL": -120.5, "openPnL": 30.0}),
        ])
        snapshot = c.snapshot()
        self.assertEqual(snapshot.equity, 50000.0)
        self.assertAlmostEqual(snapshot.total_pnl, -90.5)

    def test_open_positions_exclude_flat_and_other_accounts(self):
        c = client([
            response(TOKEN),
            response([{"id": 7, "name": "DEMO7", "active": True}]),
            response([
                {"id": 1, "accountId": 7, "contractId": 100, "netPos": 2},
                {"id": 2, "accountId": 7, "contractId": 101, "netPos": 0},
                {"id": 3, "accountId": 9, "contractId": 102, "netPos": 5},
            ]),
        ])
        positions = c.open_positions()
        self.assertEqual([p.id for p in positions], [1])


class OrderTests(unittest.TestCase):
    def _client_with_account(self, *extra):
        return client([
            response(TOKEN),
            response([{"id": 7, "name": "DEMO7", "active": True}]),
            *extra,
        ])

    def test_bracket_order_sends_opposing_stop_and_target(self):
        c = self._client_with_account(response({"orderId": 555}))
        c.place_bracket_order("MNQZ5", "Buy", 3, stop_price=20950.0, target_price=21100.0)
        _, url, kwargs = c.session.calls[-1]
        self.assertIn("/order/placeOSO", url)
        body = kwargs["json"]
        self.assertEqual(body["action"], "Buy")
        self.assertEqual(body["orderQty"], 3)
        self.assertTrue(body["isAutomated"])
        self.assertEqual(body["bracket1"], {
            "action": "Sell", "orderType": "Limit", "price": 21100.0, "timeInForce": "GTC",
        })
        self.assertEqual(body["bracket2"], {
            "action": "Sell", "orderType": "Stop", "stopPrice": 20950.0, "timeInForce": "GTC",
        })

    def test_sell_entry_brackets_buy_back(self):
        c = self._client_with_account(response({"orderId": 556}))
        c.place_bracket_order("MNQZ5", "Sell", 1, stop_price=21100.0, target_price=20950.0)
        body = c.session.calls[-1][2]["json"]
        self.assertEqual(body["bracket1"]["action"], "Buy")
        self.assertEqual(body["bracket2"]["action"], "Buy")

    def test_rejected_order_raises(self):
        c = self._client_with_account(
            response({"failureReason": "InsufficientMargin", "failureText": "no funds"})
        )
        with self.assertRaises(TradovateError) as ctx:
            c.place_bracket_order("MNQZ5", "Buy", 1, 1.0, 2.0)
        self.assertIn("InsufficientMargin", str(ctx.exception))

    def test_invalid_action_is_rejected_before_any_request(self):
        c = self._client_with_account()
        with self.assertRaises(ValueError):
            c.place_bracket_order("MNQZ5", "Long", 1, 1.0, 2.0)

    def test_zero_quantity_is_rejected_before_any_request(self):
        c = self._client_with_account()
        with self.assertRaises(ValueError):
            c.place_bracket_order("MNQZ5", "Buy", 0, 1.0, 2.0)

    def test_flatten_liquidates_every_open_position(self):
        c = self._client_with_account(
            response([
                {"id": 1, "accountId": 7, "contractId": 100, "netPos": 2},
                {"id": 2, "accountId": 7, "contractId": 101, "netPos": -1},
            ]),
            response({"ok": True}),
            response({"ok": True}),
        )
        results = c.flatten(reason="connectivity_halt")
        self.assertEqual(len(results), 2)
        liquidations = [k["json"] for _, u, k in c.session.calls if "liquidateposition" in u]
        self.assertEqual([b["contractId"] for b in liquidations], [100, 101])

    def test_flatten_is_a_noop_when_already_flat(self):
        c = self._client_with_account(response([]))
        self.assertEqual(c.flatten(reason="cutoff"), [])


class HealthTests(unittest.TestCase):
    def test_health_check_true_when_broker_answers(self):
        c = client([response(TOKEN), response([{"id": 7, "name": "D", "active": True}])])
        self.assertTrue(c.health_check())

    def test_health_check_false_when_the_request_fails(self):
        import requests

        session = FakeSession([response(TOKEN)])
        original = session.request

        def failing(method, url, **kwargs):
            if "account/list" in url:
                raise requests.RequestException("connection reset")
            return original(method, url, **kwargs)

        session.request = failing
        c = TradovateClient(CONFIG, session=session, token_cache=None)
        c.authenticate()
        self.assertFalse(c.health_check())

    def test_http_401_is_an_authentication_error(self):
        c = client([response(TOKEN), response({"err": "no"}, status=401)])
        with self.assertRaises(AuthenticationError):
            c.list_accounts()


if __name__ == "__main__":
    unittest.main()
