import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stdvbot.config import ConfigError, load_config

REQUIRED = {
    "TRADOVATE_USERNAME": "student",
    "TRADOVATE_PASSWORD": "pw",
    "TRADOVATE_CID": "123",
    "TRADOVATE_SEC": "abc",
    "TRADOVATE_DEVICE_ID": "d-1",
}


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        for key in list(os.environ):
            if key.startswith(("TRADOVATE_", "STDVBOT_")):
                del os.environ[key]
        os.environ.update(REQUIRED)
        self._tmp = TemporaryDirectory()
        self.missing_env = Path(self._tmp.name) / "absent.env"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        self._tmp.cleanup()

    def load(self):
        return load_config(self.missing_env)

    def test_defaults_match_the_documented_setup_values(self):
        config = self.load()
        self.assertEqual(config.environment, "demo")
        self.assertTrue(config.is_simulation)
        self.assertEqual(config.symbol, "MNQ")
        self.assertEqual(config.risk_per_trade_pct, 1.0)
        self.assertEqual(config.max_concurrent_positions, 1)
        self.assertEqual(config.daily_loss_limit_pct, 3.0)
        self.assertEqual(config.confluence_threshold, 2)
        self.assertEqual(config.stagnant_cutoff_minutes, 30)
        self.assertEqual(config.arm, "regime_gated")

    def test_demo_and_live_resolve_to_different_hosts(self):
        demo = self.load().rest_url
        os.environ["TRADOVATE_ENV"] = "live"
        live = self.load()
        self.assertNotEqual(demo, live.rest_url)
        self.assertIn("demo.", demo)
        self.assertIn("live.", live.rest_url)
        self.assertFalse(live.is_simulation)

    def test_missing_credential_is_rejected(self):
        del os.environ["TRADOVATE_SEC"]
        with self.assertRaises(ConfigError) as ctx:
            self.load()
        self.assertIn("TRADOVATE_SEC", str(ctx.exception))

    def test_unknown_environment_is_rejected(self):
        os.environ["TRADOVATE_ENV"] = "production"
        with self.assertRaises(ConfigError):
            self.load()

    def test_unknown_arm_is_rejected(self):
        os.environ["STDVBOT_ARM"] = "whatever"
        with self.assertRaises(ConfigError):
            self.load()

    def test_risk_larger_than_daily_limit_is_rejected(self):
        os.environ["STDVBOT_RISK_PER_TRADE_PCT"] = "5"
        os.environ["STDVBOT_DAILY_LOSS_LIMIT_PCT"] = "3"
        with self.assertRaises(ConfigError):
            self.load()

    def test_non_numeric_risk_is_rejected(self):
        os.environ["STDVBOT_RISK_PER_TRADE_PCT"] = "one percent"
        with self.assertRaises(ConfigError):
            self.load()

    def test_credentials_repr_hides_the_secret(self):
        rendered = repr(self.load().credentials)
        self.assertNotIn("abc", rendered)
        self.assertNotIn("pw", rendered)


if __name__ == "__main__":
    unittest.main()
