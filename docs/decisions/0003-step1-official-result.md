# ADR 0003 — Step 1 ufficiale result: POSITIVE on A T+60 (PEAD)

- **Status**: Accepted
- **Date**: 2026-05-10
- **Authors**: Prometeus
- **Supersedes**: —
- **Related**: ADR 0002 (re-curation procedure)

## Context

Per ADR 0002 §"One shot" the pipeline run that follows the deterministic
re-curation pass is the Step 1 ufficiale, binding per prereg §8 regardless
of outcome. The re-curation completed in commit `0643568` (W4 T1):

- Cat B (hyperscaler PPA): 5 events (W2 had 2)
- Cat C (order intake): 5 events (W2 had 3)
- Cat D (sector shock): 6 events (unchanged)
- Cat E (analyst tier-1): 11 events (W2 had 4)
- Cat A (earnings): 178 events (auto-fetched by `fetch_earnings`)

Total: 27 curated events + 178 auto = ~205 logical events, broadcast and
cross-joined to 247 panel-event-rows for the engine.

The pipeline was then run end-to-end exactly once:

```
$ uv run python -m catalystlab.cli build-panel --sector ai_infra
$ uv run python -m catalystlab.cli event-study --sector ai_infra
$ uv run python -m catalystlab.cli decide --sector ai_infra
verdict:  POSITIVE
winning:  1
ambig:    5
```

## Decision (binding per prereg §8.1)

**Step 1 verdict for sector AI Infrastructure US: POSITIVE.**

Winning combination:

| | |
|---|---|
| Category × Window | A × T+60 (PEAD, ~3 months post earnings) |
| n_valid events | 65 |
| IC (Spearman, magnitude=SUE vs CAR) | 0.319 |
| Uncorrected p-value | 0.0097 |
| BH-corrected p (n_tests=5 per holding window) | 0.0483 |
| Hit rate (sign-coherent CAR vs SUE) | 62.5% |
| Bootstrap CI 95% (n_resample=1000, seed=42) | [0.063, 0.546] |
| Mean CAR net of cost (95.5 bps round-trip) | +573 bps |
| Mean alpha per trading day in window | +9.5 bps |

All four prereg §6.3 conditions met:
- IC > 0.05 ✓
- BH-corrected p < 0.05 ✓
- Hit rate > 55% ✓
- Bootstrap CI excludes 0 (lower bound 0.063 > 0) ✓

Five ambiguous combinations (passes IC + hit_rate, fails BH or CI):

| Cat × Window | n | IC | BH-p | hit | Reason |
|---|---|---|---|---|---|
| C T+1 | 4 | 0.211 | 0.789 | 75% | BH fails + CI crosses 0 |
| C T+5 | 4 | 0.949 | 0.128 | 75% | BH fails (n too small) |
| C T+20 | 4 | 0.632 | 0.528 | 75% | BH + CI |
| C T+60 | 4 | 0.105 | 0.895 | 100% | BH + CI |
| E T+20 | 11 | 0.433 | 0.459 | 64% | BH + CI |

Per prereg §8.3 ambiguous = treated as negative for action; documented but
NOT promoted to live trading.

## Consequences

Per prereg §8.1 binding action sequence:

1. **Step 2a — Paper trading 1 month** (binding):
   - Combination: A T+60 (PEAD with |SUE| > 1.0)
   - Position sizing per trade: max 20% of cap = €0 (paper) ramping in
     prep for live cap
   - Holding window: T+1 entry, T+60 exit
   - Operational shakedown only (validate execution timing, FX,
     commission accuracy); NOT statistical re-validation
   - Tracking artifact: `paper_trading/A_T+60_<period>.csv`

2. **Step 2b — Live trading** (binding, conditioned on 2a completing):
   - Capital cap: **€5,000 binding** (prereg §10.1)
   - Allocation: 5-10 trades of €500-€1,000 each on A T+60
   - Holding window: T+1 to T+60 same as Step 1
   - Drawdown trigger: -30% per prereg §10.2 / "tesi rotta" §10.3
   - Hard stop: -50% (§10.4)
   - Time stop: 12 months from go-live (§10.5)

3. **What this ADR closes**:
   - The Step 1 research phase. The framework + decision artifact +
     report.html + manifest are the audit trail.
   - The re-curation iteration window (per ADR 0002 "one shot").

4. **What this ADR does NOT do**:
   - Authorise any modification of prereg §8 thresholds or decision
     tree.
   - Authorise capital deployment > €5,000 (any such authorisation
     requires prereg v2 per §11).
   - Skip the paper trading phase (§11 anti-pattern).

## Robustness notes

- The A T+60 winner is the same combination identified in the W3
  framework verification smoke run (commit `9f36515`). The Step 1
  ufficiale run on the extended dataset (W4 commit `0643568`,
  +12 events across B/C/E) reproduces the verdict. This is consistent
  with the cat A signal being driven by the n=178 auto-fetched
  earnings rather than the small B/C/E samples.

- The cat C and cat E ambiguous results are likely under-power
  artifacts: even after re-curation, n=4-11 per group is below what
  BH-FDR over 5 categories needs for typical effect sizes. This does
  NOT invalidate the A signal; it just confirms the original prior
  (§1.3) that A and (less likely) C might produce signal — the data
  shows A delivered, C/E remain inconclusive.

- The cat D temporal decay shows interesting patterns but per prereg
  §8 only IC + hit_rate + BH + CI matter for the binding decision.

## Status history

- 2026-05-10 — Accepted (post-re-curation Step 1 ufficiale run on
  commit `0643568`).
