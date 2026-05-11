# ADR 0004 — yfinance EPS sourcing inconsistency: finding + W5/W6 strategy

- **Status**: Accepted
- **Date**: 2026-05-11
- **Authors**: Prometeus
- **Supersedes**: —
- **Related**: ADR 0002 (re-curation procedure), ADR 0003 (Step 1 v1 verdict)

## Context

The prereg §3.1 quality gate (*"manualmente verificata su 3 ticker
random"*) was executed retrospectively on the W4 Step 1 ufficiale
dataset (commit `0643568`, verdict POSITIVE on A T+60). The check
expanded beyond the prereg-minimum 3 random into a stratified sample
of 12 events covering all 8 universe tickers, plus all SUE-magnitude
outliers (|SUE| > 3).

### Finding

The yfinance `get_earnings_dates` endpoint returns inconsistent EPS
methodology across tickers and quarters:

|  Category | Count | % | Example |
|---|---|---|---|
| ✅ Correct (matches reported adjusted/operating EPS) | 5 / 10 | 50% | GEV 2026-01-28, ETN 2023-10-31, VRT 2025-02-12, PWR 2024-10-31 |
| ⚠️ Sign-correct, magnitude wrong | 3 / 10 | 30% | CEG 2023-02-16 ($0.17 vs reported $2.30), ANET 2025-02-18 (pre/post split) |
| ❌ SIGN-FLIP | 2 / 10 | **20%** | MOD 2026-02-04, CEG 2025-05-06 |
| inconclusive | 2 | — | VST × 2 (web doesn't disclose EPS specific) |

The two confirmed sign-flips both follow the same pattern: company
reports a GAAP net **loss** alongside an adjusted/operating EPS **beat**.
yfinance picks up GAAP basic EPS (the loss); analysts and consensus
data are on the adjusted basis (the beat). The SUE sign therefore
inverts.

The prereg §3.1 references "IBES/Refinitiv" consensus, which is
universally an adjusted/operating-EPS family. The actual reported EPS
that should match consensus is therefore also adjusted, not GAAP basic.

### Sensitivity test (in `notebooks/02_outlier_sensitivity.py`)

Re-computing cat A T+60 with the confirmed MOD 2026-02-04 sign-flip
removed:

| Scenario | n | IC | BH-p | CI 95% | hit_rate | Verdict |
|---|---|---|---|---|---|---|
| BINDING (all events, W4) | 65 | 0.319 | 0.0483 | [0.052, 0.548] | 62.5% | POSITIVE |
| MOD 2026-02-04 removed | 64 | 0.322 | 0.0477 | [0.054, 0.557] | 63.5% | POSITIVE |
| ALL MOD events removed (8) | 57 | 0.317 | 0.0775 | [0.010, 0.582] | 60.7% | AMBIGUOUS |

The W4 verdict POSITIVE is **robust to single-outlier removal** (the one
case verified as data error). Only an aggressive, unjustified removal
of all MOD events shifts the verdict to AMBIGUOUS.

### Implication for the binding verdict

Per ADR 0002 §"One shot" the W4 verdict is binding regardless of
retrospective findings. ADR 0003 records POSITIVE on A T+60 as the
Step 1 v1 result.

This finding does NOT modify the verdict. It does add three caveats:

1. **The IC=0.319 estimate is on data with ~20% confirmed sign-flips**.
   True IC under a corrected dataset could be higher (if signal real
   and yfinance noise dilutes it) or lower (if signal is partly
   artifact of inconsistent sign assignment). Cannot determine without
   re-sourcing.

2. **Cat A T+60 specifically survives the single-outlier removal**,
   suggesting the signal is robust to localized data error.

3. **The aggregate signal direction (drift positive when SUE positive)
   is preserved in 8/10 confirmed events** — yfinance is sign-correct
   in 80% of the small sample.

## Decision

Two-track strategy:

### Track 1 — W5 (now): Paper trading 1 month on v1 verdict

Proceed to paper trading per prereg §8.1 binding action on POSITIVE
verdict, with the explicit caveat that:

- Paper trading is **operational shakedown** (timing, FX, commission,
  workflow) — explicitly NOT statistical re-validation per §8.1.
- Operational testing is **independent of EPS source quality**: it
  validates the framework's executability (entry T+1, exit T+60,
  cost realism), not the IC.
- New SUE>1.0 trigger events monitored from W5 start (today, 2026-05-11)
  through W5 end (~2026-06-10).
- Cap: €0 real capital (paper).

Deliverable W5: `paper_trading/A_T+60_2026-05.csv` with completed
or in-flight simulated trades + operational P&L tracking.

### Track 2 — W6-W7 (after W5): prereg v2 with authoritative EPS source

After W5 paper trading completes:

1. Write `docs/prereg_step1_ai_infra_v2.docx` (new lockfile, new
   timestamp, new SHA-256). Maintains universe, holding windows,
   thresholds, cost model unchanged. **Only modification**: explicit
   EPS source specification (adjusted/operating non-GAAP from
   company IR or third-party API; no GAAP basic).

2. Implement new `ingestion/earnings.py` using:
   - Third-party API (Polygon.io / Financial Modeling Prep free tier),
     OR
   - WebFetch pipeline against company IR press releases, OR
   - Hybrid manual override

   yfinance remains primary source for **prices OHLCV** (no issue
   there); only `get_earnings_dates` is replaced.

3. Re-run pipeline → ADR 0005 with Step 1 v2 verdict (POSITIVE,
   NEGATIVE, AMBIGUOUS).

4. **Live €5k decision binding on v2 verdict + W5 paper operational
   OK**, NOT on W5 paper P&L (paper is operational, not statistical).

### What this ADR does NOT modify

- ADR 0003 stands; W4 v1 verdict POSITIVE archived as v1 result.
- Live €5k cap binding per §10.1, drawdown triggers §10.3, time stop
  §10.5 — all unchanged.
- Sector universe, event definitions, holding windows, thresholds —
  all unchanged.

## Consequences

**Positive**

- Step 1 honesty: the data-quality concern is documented, not buried.
- W5 paper trading proceeds — no time lost, operational learning
  starts now.
- v2 will be conducted on clean data BEFORE live trading commits real
  capital.
- Paper trading tooling (CSV schema, monitoring, P&L tracker) is
  reusable for the eventual live runs regardless of v2 outcome.

**Negative / accepted**

- If W7 v2 verdict differs from W4 v1 verdict (POSITIVE → NEGATIVE or
  AMBIGUOUS), the W5 paper trading effort is operationally useful but
  statistically irrelevant. Acceptable trade-off.

**Risk**

- Bias from seeing W4 v1 POSITIVE while designing v2 source. Mitigation:
  v2 spec is committed (this ADR + future v2 doc) before re-running,
  and v2 maintains v1 prereg §3-§6 verbatim except for the EPS
  ingestion mechanism.

## Status history

- 2026-05-11 — Accepted (post-quality-gate session).
