"""Command line entry points. `stdvbot check-connection` is Setup step 11."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_config
from .tradovate import PenaltyBoxError, TradovateClient, TradovateError

OK = "  [ok]  "
FAIL = " [fail] "


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def check_connection(args: argparse.Namespace) -> int:
    """Verify authentication, account resolution, and cash balance."""
    try:
        config = load_config(args.env_file)
    except ConfigError as exc:
        print(f"{FAIL}configuration: {exc}")
        return 2

    print(f"Environment : {config.environment}"
          f"{'  (simulation — no real capital at risk)' if config.is_simulation else ''}")
    print(f"Symbol      : {config.symbol}")
    print(f"Arm         : {config.arm}")
    print(f"Risk/trade  : {config.risk_per_trade_pct}%   "
          f"Daily limit: {config.daily_loss_limit_pct}%   "
          f"Max positions: {config.max_concurrent_positions}")
    print()

    if not config.is_simulation:
        print("WARNING: TRADOVATE_ENV=live. Orders will be sent to a real funded")
        print("         account. Set TRADOVATE_ENV=demo for the study.")
        print()

    client = TradovateClient(config)

    try:
        token = client.authenticate()
    except PenaltyBoxError as exc:
        print(f"{FAIL}authentication: {exc}")
        return 3
    except TradovateError as exc:
        print(f"{FAIL}authentication: {exc}")
        return 3
    print(f"{OK}authentication — token valid for {token.seconds_remaining / 60:.0f} min")

    try:
        account = client.account()
    except TradovateError as exc:
        print(f"{FAIL}account: {exc}")
        return 4
    print(f"{OK}account — {account.name} (id {account.id}, {account.account_type})")

    try:
        snapshot = client.snapshot()
    except TradovateError as exc:
        print(f"{FAIL}cash balance: {exc}")
        return 5

    if snapshot.equity <= 0:
        print(f"{FAIL}cash balance — equity is {snapshot.equity:,.2f}; "
              "position sizing cannot run against a non-positive balance")
        return 5
    print(f"{OK}cash balance — equity {snapshot.equity:,.2f}, "
          f"realized {snapshot.realized_pnl:+,.2f}, open {snapshot.open_pnl:+,.2f}")

    risk_amount = snapshot.equity * config.risk_per_trade_pct / 100
    loss_limit = snapshot.equity * config.daily_loss_limit_pct / 100
    print(f"{OK}derived — risk per trade {risk_amount:,.2f}, "
          f"circuit breaker at {loss_limit:,.2f} of daily loss")

    try:
        positions = client.open_positions()
    except TradovateError as exc:
        print(f"{FAIL}positions: {exc}")
        return 6
    if positions:
        print(f"{OK}positions — {len(positions)} open "
              f"(the bot will refuse new entries until flat)")
    else:
        print(f"{OK}positions — flat")

    print("\nConnection verified. Setup step 11 complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Shared flags live on a parent parser so they are accepted both before and
    # after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", default=".env", help="path to the .env file")
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(
        prog="stdvbot", description=__doc__, parents=[common]
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check-connection",
        parents=[common],
        help="verify Tradovate credentials, account, and balance",
    )
    check.set_defaults(func=check_connection)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
