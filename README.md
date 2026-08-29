# STDVBOT

Autonomous regime-gated reversal trading system.

The full experimental protocol — hypothesis, variables, controls, the 60-step
operating procedure, and the analysis plan — is in
[`docs/ISEF_PROCEDURES.md`](docs/ISEF_PROCEDURES.md).

## Status

This is a **historical simulation study**. No brokerage account is connected and no
orders are transmitted anywhere. See [`docs/ISEF_PROCEDURES.md`](docs/ISEF_PROCEDURES.md)
for the full protocol.

| Component | State |
| --- | --- |
| Configuration and risk parameters (`stdvbot/config.py`) | done |
| Bars, session arithmetic, resampling, CSV loading (`stdvbot/bars.py`) | done |
| Candlestick reversal patterns (`stdvbot/candles.py`) | done |
| Tradovate connection (`stdvbot/tradovate.py`) | built, **not used by the study** |
| `stdvbot check-connection` (`stdvbot/cli.py`) | done |
| HTF bias and regime classification | not built |
| Leg detection and inverse-Fibonacci grid | not built |
| Session VWAP and POI computation | not built |
| Confluence scoring and trade decision | not built |
| Backtest engine and decision log | not built |
| `stdvbot verify-data` / `export-log` | not built |

### On the Tradovate module

`stdvbot/tradovate.py` is complete and tested, but the study does not use it. Tradovate
issues API keys only to live accounts holding over $1,000, and prop-firm accounts are
excluded from that path entirely. Prop firms including Apex also prohibit fully
autonomous bots that manage both entry and exit — which is exactly what this system is.
The module is kept because it is finished and may serve a future personally-funded
simulation account, but nothing in the experimental protocol depends on it.

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
