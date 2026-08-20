# STDVBOT

Autonomous regime-gated reversal trading system.

The full experimental protocol — hypothesis, variables, controls, the 60-step
operating procedure, and the analysis plan — is in
[`docs/ISEF_PROCEDURES.md`](docs/ISEF_PROCEDURES.md).

## Status

| Component | State |
| --- | --- |
| Configuration and risk parameters (`stdvbot/config.py`) | done |
| Tradovate connection: auth, accounts, orders, flatten, health (`stdvbot/tradovate.py`) | done |
| `stdvbot check-connection` (`stdvbot/cli.py`) | done |
| Market data feed (1m / 4H / Daily) | not built |
| Candlestick patterns (`stdvbot/candles.py`) | not built |
| HTF bias and regime classification | not built |
| Leg watcher and inverse-Fibonacci grid | not built |
| Confluence scoring and trade decision | not built |
| Decision log and CSV export | not built |

## Setup

```bash
pip install -e .
cp .env.example .env
python3 -c "import uuid; print(uuid.uuid4())"   # paste into TRADOVATE_DEVICE_ID
$EDITOR .env
stdvbot check-connection
```

`check-connection` implements Setup step 11: it authenticates, resolves exactly
one account, reads the cash balance, derives the risk amount and circuit-breaker
threshold from it, and reports whether the account is currently flat. It exits
non-zero on any failure so it can gate a startup script.

## Safety notes

- `TRADOVATE_ENV=demo` targets the simulation environment. `live` targets real
  funded accounts; `check-connection` prints a warning when it is set.
- `.env` and the cached token file are both gitignored. `TradovateCredentials`
  overrides `__repr__` so secrets do not leak into logs or tracebacks.
- If more than one active account is visible, the client refuses to guess and
  requires `TRADOVATE_ACCOUNT_SPEC`.
- Tradovate answers over-frequent auth attempts with a penalty ticket rather
  than a token; the client raises `PenaltyBoxError` carrying the required wait
  instead of retrying into a longer penalty.
- `flatten()` is the fail-safe path for Procedure steps 47 and 49: it
  liquidates at market rather than reasoning about what the position should be.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

No test contacts the network; the HTTP session is faked.
