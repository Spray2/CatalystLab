# Paper trading — W5 operational shakedown

Per ADR 0003 §"Decision" and prereg §8.1, the POSITIVE Step 1 v1
verdict on A T+60 (PEAD) triggers a 1-month paper trading phase
**before** any live capital deployment. ADR 0004 documents the data
quality caveat and the decision to proceed.

## Scope

- **Winning combination**: cat A (earnings), holding window T+60
- **Trigger**: company earnings announcement with |SUE| > 1.0 (prereg §3.1)
  - SUE = (actual - consensus) / std(consensus, last 8 quarters)
  - **Caveat**: SUE is computed from yfinance EPS data which has
    ~20% sign-flip rate (ADR 0004). Manual verification of each
    candidate trade against the company IR press release is recommended.
- **Entry**: T+1 (next US trading day open) — prereg §4 forbids T+0
- **Exit**: T+60 (60 trading days later, close)
- **Position size**: €1000 nominal (paper, no real capital)
- **Universe**: VRT, ETN, GEV, PWR, CEG, VST, ANET, MOD
- **Duration**: 1 month (2026-05-11 → 2026-06-10 approx)

## Schema `A_T+60_2026-05.csv`

| Column | Type | Description |
|---|---|---|
| trade_id | int | sequential id |
| ticker | str | universe ticker |
| event_date | YYYY-MM-DD | earnings announcement date |
| sue | float | computed SUE; sign indicates beat (+) / miss (-) |
| sue_sign | int {-1, 0, +1} | sign of SUE, used for entry direction |
| entry_date | YYYY-MM-DD | next trading day after event_date |
| entry_price | float | adjusted close at entry_date |
| exit_date | YYYY-MM-DD | event_date + 60 trading days |
| exit_price | float | adjusted close at exit_date |
| gross_return | float | (exit_price - entry_price) / entry_price * sue_sign |
| cost_bps | float | applied round-trip cost in bps (95.5 default) |
| net_return | float | gross_return - cost_bps / 10000 |
| status | str | one of: pending, in_flight, closed, aborted |
| notes | str | manual notes (IR EPS verification, data anomalies, etc.) |

## Workflow operativo settimanale

1. **Mon morning**: check the next 7 days of earnings for universe via
   `uv run python -c "..."` snippet or yfinance get_earnings_dates.
2. **Day-of-earnings**: post-market, compute SUE manually (or run
   `fetch_earnings` then verify the row against IR press release).
3. **If |SUE| > 1.0 AND IR press release confirms direction**:
   add a new row, status=`pending`, entry_date = next trading day.
4. **T+1 open**: record entry_price (yfinance adj_close T+1, or
   Fineco quote if available), status=`in_flight`.
5. **T+60 close**: record exit_price, compute gross_return, net_return,
   status=`closed`.
6. **End of month**: tally net P&L, count of trades, average net return,
   verify cost realism vs prereg §5 (target ~95.5 bps round-trip).

## Manual checks per row

Per ADR 0004, every candidate trade is **manually verified against the
company IR press release**:

- `actual_eps` matches the adjusted/operating EPS in the IR release
- `estimate_eps` matches the consensus (IBES/Refinitiv) reported by
  the company or in analyst preview articles
- If yfinance and IR disagree on EPS magnitude or sign → use IR values
  for the trade decision; flag the row with `note: yfinance-IR mismatch`

## Decision criteria (end of W5)

- **Paper OK**: at least 1 trade fully closed (entry + exit) with the
  operational pipeline working. Cost realism within 75-100 bps per
  prereg §5.2.
- **Paper KO**: pipeline failures (timing issues, broker UI gaps,
  data issues) → reject Step 2b live trading, re-evaluate.

The W5 outcome is operational only. The statistical Step 1 v1 verdict
stands; the v2 re-source happens in W6-W7 (ADR 0004 Track 2).

## Helper commands

```bash
# Check upcoming earnings in universe (next 14 days)
uv run python -c "
import yfinance as yf, pandas as pd
universe = ['VRT','ETN','GEV','PWR','CEG','VST','ANET','MOD']
today = pd.Timestamp.today().normalize()
for t in universe:
    df = yf.Ticker(t).get_earnings_dates(limit=8)
    if df is not None and not df.empty:
        upcoming = df.index[(df.index.tz_localize(None) >= today)
                            & (df.index.tz_localize(None) <= today + pd.Timedelta(days=14))]
        if len(upcoming):
            print(t, list(upcoming.strftime('%Y-%m-%d')))
"

# Append a new paper trade row (interactive)
# - Edit paper_trading/A_T+60_2026-05.csv directly in a text editor
# - Or use pandas:
uv run python -c "
import pandas as pd
df = pd.read_csv('paper_trading/A_T+60_2026-05.csv')
new = pd.DataFrame([{
    'trade_id': len(df)+1,
    'ticker': 'TICKER', 'event_date': 'YYYY-MM-DD',
    'sue': 0.0, 'sue_sign': 0,
    'entry_date': '', 'entry_price': float('nan'),
    'exit_date': '', 'exit_price': float('nan'),
    'gross_return': float('nan'), 'cost_bps': 95.5, 'net_return': float('nan'),
    'status': 'pending', 'notes': '',
}])
pd.concat([df, new], ignore_index=True).to_csv('paper_trading/A_T+60_2026-05.csv', index=False)
"
```
