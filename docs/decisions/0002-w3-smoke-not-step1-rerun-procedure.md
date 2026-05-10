# ADR 0002 — W3 smoke run is framework verification, not Step 1; re-run procedure for Step 1 ufficiale

- **Status**: Accepted
- **Date**: 2026-05-10
- **Authors**: Prometeus
- **Supersedes**: —

## Context

End-of-W3 the framework produces a `decide` verdict of **POSITIVE** for
sector `ai_infra`, with one winning combination at category A holding
window T+60 (IC=0.319, BH-corrected p=0.0483, hit_rate=62.5%, bootstrap
CI=[0.063, 0.546], mean CAR net = +573 bps over 65 events).

Per prereg §8.1 a positive verdict triggers paper trading (1 month) →
live €5k cap. **However**, the run that produced this verdict is not
prereg-compliant as a Step 1 ufficiale, for two binding reasons:

1. **Curation incompleteness**: the W2 T1 commit (`4771e6e`) curated only
   15 events for categories B/C/D/E — far below the implicit "all events
   meeting prereg §3 thresholds in the period" coverage that the
   §6.3 BH-FDR test assumes. Categories B (n=2), C (n=3), and E (n=4)
   have BH-p = NaN or > 0.05 simply because the test cannot resolve a
   signal at those sample sizes. The "winning" cat A signal is robust to
   this (n=65 from auto-fetched earnings), but the overall multi-test
   correction is biased by the under-curation.

2. **Post-observation iteration risk**: per prereg §0,
   *"nessuna delle decisioni qui pre-registrate può essere modificata in
   funzione di risultati osservati"*, and §11 *"NON aggiungere ticker
   all'universe dopo aver visto risultati parziali"*. Adding events to
   B/C/E now, after seeing W3 outputs, would create exactly the
   data-fishing pattern §0 explicitly forbids. The framework cannot
   "iteratively improve" the dataset toward a desired verdict.

The W3 smoke run is therefore best understood as the **framework
verification milestone**: it proved that `build-panel → event-study →
decide` is a working pipeline that produces a valid decision artifact.
It is not a statistical Step 1 result.

## Decision

The W3 smoke run is reclassified as **framework verification**, not
Step 1. The Step 1 ufficiale is performed exactly once, after one
re-curation pass executed under the procedure below.

### Re-curation procedure (binding)

1. **Categories in scope**: B (hyperscaler PPA), C (order intake), E
   (analyst rating). Cat A (earnings) is auto-fetched by `fetch_earnings`
   and already at n=178; D (sector shock) at n=6 for sector-wide events
   is sufficient (broadcast to 8 tickers ⇒ 48 panel rows, already past
   any reasonable BH threshold).

2. **Coverage rule**: include every event meeting the prereg §3
   definition for the universe in `[2023-01-01, 2026-04-30]`. NOT a
   curated subset; NOT cherry-picked by expected impact.

   - **Cat B (§3.2)**: corporate press release of Microsoft / Meta /
     Amazon / Google (GOOGL) / Oracle announcing a PPA or data-center
     deal with a universe ticker (direct or via controlled subsidiary).
   - **Cat C (§3.3)**: corporate press release announcing a new
     contract / backlog update / capacity expansion, where deal value
     > $100M OR backlog change > 10%.
   - **Cat E (§3.5)**: rating action by a tier-1 investment bank
     (Goldman Sachs, JP Morgan, Morgan Stanley, Bank of America, Citi,
     UBS) with |target price change| > 10%.

3. **Search procedure**: for each (category × ticker) combination, run
   structured WebSearch queries against the prereg-defined sources
   (corporate IR press releases, SEC 8-K, Reuters/Bloomberg/FT, BIS
   notices). Record EVERY hit that meets the §3 threshold; no
   subjective filtering.

4. **Stopping criterion**: structured search exhausted (no new events
   found in 3 consecutive queries per (category × ticker)).

5. **Audit trail**: every committed event row carries `source_url` and
   the curation date. Commit message lists per-row rationale.

6. **One shot**: after re-curation, the pipeline is run exactly once.
   The verdict of that run is the Step 1 ufficiale, binding per
   prereg §8 regardless of outcome. No further iteration on the event
   log dataset for this prereg version.

### Quality gate (prereg §3.1, §7)

Independently of the re-curation:

- 3 random earnings dates × ticker manually verified vs Yahoo Finance
  web (prereg §3.1).
- 5 random ticker-date OHLCV verified vs Yahoo Finance web (prereg §7).

Documented in the run manifest as `quality_gate: passed/failed`.

### What this ADR does NOT do

- Modify any prereg §6.3 threshold (IC, hit_rate, BH alpha — all stay
  binding at 0.05 / 0.55 / 0.05).
- Modify the universe (still 8 tickers).
- Modify event definitions (§3 unchanged).
- Modify holding windows (still {1, 5, 20, 60}).
- Authorise a "v2 prereg" — the lockfile remains
  `prereg_step1_ai_infra.docx` v1.0 with the same SHA-256.

## Consequences

**Positive**

- Step 1 is conducted on a fully-curated, prereg-coverage-compliant
  dataset, addressing the under-power of W3 smoke for categories B/C/E.
- Re-curation procedure is executed BEFORE seeing the new run's
  verdict, restoring the pre-registration's statistical guarantees.
- W3 smoke output is preserved as the framework verification milestone
  (artifact: `data/processed/decision_ai_infra.json` from W3, kept for
  audit) — not destroyed.

**Negative / accepted**

- Discards the W3 POSITIVE verdict from any decision authority. The
  Step 1 ufficiale may yield a different verdict.
- Re-curation is a substantial manual effort (estimated 3-5 hours of
  WebSearch + verification).
- One-shot constraint means the Step 1 result is final; no fallback if
  the dataset is still imperfect.

**Risk**

- The W3 verdict is potentially "leaked" knowledge that biases this
  ADR or the re-curation procedure. Mitigation: the procedure above
  is deterministic (mechanical search queries, no impact-based
  filtering). The author commits to executing the procedure as written
  even if hits suggest the new dataset will move the verdict away from
  POSITIVE.

## Status history

- 2026-05-10 — Accepted (post-W3 closure session, pre-W4 execution).
