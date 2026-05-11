# Paper trading — W5 operational shakedown (L2 semi-auto + UX pack)

## Comandi disponibili

| Comando | Quando | Cosa fa |
|---|---|---|
| `catalystlab paper-tick --sector ai_infra` | Una volta al giorno | Detect nuovi earnings con \|SUE\|>1.0, transition state, rigenera `data/processed/dashboard_<sector>.html` |
| `catalystlab today --sector ai_infra` | Quando vuoi sapere "che faccio oggi?" | Stampa azioni del giorno (OPEN/CLOSE), cap usato, slot, drawdown, posizioni aperte, prossime earnings |
| Aprire `data/processed/dashboard_<sector>.html` in browser | Sempre disponibile | Vista visuale completa: KPI, banner drawdown, today actions, posizioni aperte/chiuse, alerts, earnings upcoming |


Per ADR 0003 / prereg §8.1, il verdict POSITIVE su cat A T+60 triggera 1 mese
di paper trading PRIMA del live trading. Per ADR 0004 ogni candidate trade
richiede verifica manuale IR (~20% sign-flip rate su yfinance).

## Workflow operativo (3 step ricorsivo)

### Step 1 — paper-tick: detect + transition (CLI auto)

Una volta al giorno (o quando vuoi):

```bash
uv run python -m catalystlab.cli paper-tick --sector ai_infra
```

Cosa fa il CLI:

1. **Detect**: fetch_earnings sull'universe, identifica nuovi eventi con
   `|SUE| > 1.0` annunciati negli ultimi 7 giorni (default lookback).
2. **Append**: aggiunge righe con `status=pending_review` al CSV.
3. **Transition approved → in_flight**: per ogni riga `status=approved`,
   se oggi >= T+1 → fetch yfinance adj_close, registra entry, `status=in_flight`.
4. **Transition in_flight → closed**: per ogni riga `status=in_flight`,
   se oggi >= T+60 → fetch exit_price, computa gross/net return,
   `status=closed`.
5. **Print** summary: nuovi candidati, transizioni, P&L cumulativo netto.

**Opzioni**:
- `--csv path/to/file.csv` (default: `paper_trading/A_T+60_<YYYY-MM>.csv`)
- `--sue-threshold 1.0` (prereg §3.1 standard)
- `--min-event-date 2026-05-11` (default: today−7gg)

### Step 2 — Human IR verification (manuale, 2 min/evento)

Per ogni `pending_review` row, il CLI stampa:

```
ACTION: review pending_review row(s) — verify IR press release,
edit CSV: status pending_review -> approved (or rejected).
```

Workflow di verifica:

1. Apri il CSV in un editor (es. `vim paper_trading/A_T+60_2026-05.csv`)
2. Per la riga `pending_review`: trova la URL IR press release del ticker
   (es. investors.constellationenergy.com per CEG)
3. Verifica:
   - `actual_eps` (yfinance) corrisponde ad `adjusted EPS` (IR release)?
   - Sign della surprise (beat/miss) concorda con IR?
4. Modifica:
   - Se ✅ concordano → `status=approved`
   - Se ❌ yfinance ha sign-flip → `status=rejected`, nota in `notes`
   - Se yfinance ha magnitude sbagliata ma sign corretto → puoi `approved`
     con nota o `rejected` (ADR 0004 caveat)

Salva il CSV.

### Step 3 — Next paper-tick raccoglie le tue approvazioni

Il prossimo `paper-tick` vedrà le righe `approved`, e se oggi >= T+1
le porterà a `in_flight` con entry_price.

## Schema CSV `A_T+60_<YYYY-MM>.csv`

| Column | Type | Description |
|---|---|---|
| trade_id | int | sequential id (auto) |
| ticker | str | universe ticker (auto) |
| event_date | YYYY-MM-DD | earnings announcement date (auto) |
| sue | float | SUE = (actual−estimate)/std(estimate); auto from fetch_earnings |
| sue_sign | int {-1, 0, +1} | sign of SUE; entry direction (LONG if +, SHORT if −) |
| status | str | pending_review → approved/rejected → in_flight → closed |
| entry_date | YYYY-MM-DD | T+1 trading day (auto when in_flight) |
| entry_price | float | yfinance adj_close on entry_date (auto) |
| exit_date | YYYY-MM-DD | T+60 trading day (auto when closed) |
| exit_price | float | yfinance adj_close on exit_date (auto) |
| gross_return | float | (exit−entry)/entry × sue_sign (auto when closed) |
| cost_bps | float | applied cost in bps (auto, default 95.5) |
| net_return | float | gross_return − cost_bps/10000 (auto) |
| notes | str | manual annotations (IR mismatch, data anomalies) |

## State machine

```
                 paper-tick auto       human review       paper-tick auto       paper-tick auto
                ↓                     ↓                  ↓                     ↓
NEW EVENT  →  pending_review   →   approved        →   in_flight         →   closed
detected                          (or rejected      (T+1, entry price)     (T+60, exit price,
                                  → no trade)                                gross + net P&L)
```

## Decision criteria (fine W5)

- **Paper OK**: ≥1 trade `closed` con pipeline operativa OK. Cost realism
  entro 75-100 bps prereg §5.2.
- **Paper KO**: timing issues, broker UI gaps, data errors → reject live.

L'outcome W5 è **operational only**. Lo statistical Step 1 v1 verdict resta
binding; il v2 re-source happens W6-W7 (ADR 0004 Track 2).

## Daily routine (raccomandato)

Lunedì mattina:

```bash
# 1. Pull aggiornamenti repo (se collaborativo)
# 2. Run paper-tick
uv run python -m catalystlab.cli paper-tick --sector ai_infra

# 3. Se "new candidates" > 0:
#    - Apri CSV
#    - Per ogni pending_review, verifica IR + approve/reject
#    - Salva CSV
#    - (opzionale) Re-run paper-tick per processare approved subito

# 4. Commit changes
git add paper_trading/
git commit -m "paper: update W5 trades"
```

## Helper commands

```bash
# Check P&L summary (Python one-liner)
uv run python -c "
import pandas as pd
df = pd.read_csv('paper_trading/A_T+60_2026-05.csv')
print(df.groupby('status').size())
closed = df[df['status']=='closed']
if not closed.empty:
    print(f'Net P&L: {closed[\"net_return\"].sum():+.4f}')
    print(f'Mean: {closed[\"net_return\"].mean():+.4f}')
    print(f'Trades: {len(closed)}')
"

# Check upcoming earnings in universe (next 14 days)
uv run python -c "
import yfinance as yf, pandas as pd
universe = ['VRT','ETN','GEV','PWR','CEG','VST','ANET','MOD']
today = pd.Timestamp.today().normalize()
for t in universe:
    df = yf.Ticker(t).get_earnings_dates(limit=8)
    if df is not None and not df.empty:
        idx_naive = df.index.tz_localize(None) if df.index.tz else df.index
        upcoming = df.index[(idx_naive >= today) & (idx_naive <= today + pd.Timedelta(days=14))]
        if len(upcoming):
            print(t, [d.strftime('%Y-%m-%d') for d in upcoming])
"
```
