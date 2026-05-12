# ADR 0005 — Track 2: Semiconductors sector expansion (parallel to Sector 1)

- **Status**: Proposed
- **Date**: 2026-05-12
- **Authors**: Prometeus
- **Supersedes**: —
- **Related**: ADR 0003 (Step 1 Sector 1 POSITIVE), prereg `docs/prereg_step1_semis.docx` v1.0 (pending firma)

## Context

Step 1 ufficiale su AI Infrastructure US è chiuso POSITIVE (ADR 0003) e
W5 paper trading è in corso (2026-05-12 → ~2026-06-12). Durante W5 day 1
si è osservato che il volume di segnali validi su Sector 1 è strutturalmente
basso:

- Universe: 8 ticker × 4 earnings/anno = 32 eventi cat A potenziali
- Filtro `|SUE| > 1.0` riduce a ~5-8 segnali validi/anno
- Cat B/C/E sono underpowered (Step 1 ufficiale ADR 0003 ha trovato solo
  cat A × T+60 sopra soglia BH)
- Cap binding €5k per Sector 1, mediamente 1-2 trade aperti contemporaneamente

Risultato: edge statisticamente solido ma utilizzo di capitale e
frequenza di trade scarsi. Il framework CatalystLab è esplicitamente
estendibile per design (CLAUDE.md §1): nessun layer core conosce
dettagli di settore. La pre-registration §8 prevede `sectors/rare_earths.yaml`
come fallback del decision tree negativo; non è prescrittiva sul caso positivo,
che resta agnostico rispetto al settore di espansione.

Verifica del codebase (Explore agent, 2026-05-12) conferma:

- `src/catalystlab/config/loader.py:25-55` — `load_sector(name)` accetta
  qualsiasi YAML, nessuna whitelist
- `src/catalystlab/config/schemas.py:117-167` — `SectorConfig` valida
  invarianti prereg in modo generico (5 categorie A-E, no T+0, etc.)
- `src/catalystlab/cli.py` (build-panel, event-study, decide, paper-tick,
  today) — tutti accettano `--sector <name>` arbitrario
- `data/events/<sector>/` — auto-creato dal CLI al primo run

Nessuna modifica al codice è necessaria per attivare un secondo settore;
è puramente lavoro di contenuti (YAML + prereg + curation).

## Decision

**Aprire Track 2 sul settore Semiconductors US**, in parallelo a Track 1
(AI Infrastructure US), come test statistico **completamente indipendente**.

### Sector 2 scope (locked at signature time)

- **Universe** (8 ticker, US-listed o ADR US): NVDA, AMD, AVGO, MU, TSM,
  ASML, AMAT, LRCX. Selezione motivata: top-of-mind per AI cycle (capex
  hyperscaler, compute, memoria HBM, equipment, EUV).
- **Benchmark primario**: SOXX (iShares Semiconductor ETF, sector-native).
  Secondario: XLK (cross-check / coerenza con Sector 1).
- **Period**: 2023-01-01 → 2026-04-30 (identico a Sector 1 per
  comparabilità di regime macro: post-ChatGPT AI boom, post-COVID supply
  chain stabilizzata).
- **Categorie A-E**: mirror di Sector 1 con adattamenti:
  - A earnings PEAD (identica, |SUE|>1.0)
  - B hyperscaler design win (analogo del PPA per AI Infra)
  - C capacity / order intake / fab announcement > $1B (threshold scaled
    rispetto a Sector 1 dove era $100M, perché semis hanno deal size più
    grandi)
  - D sector shock (export controls, supply disruption)
  - E analyst rating tier-1 (identica)
- **Stats**: thresholds identici (IC>0.05, hit_rate>0.55, BH alpha=0.05,
  bootstrap CI 95% / n=1000).
- **Cost model**: identico Fineco (95.5 bps round-trip su €1k).

### Isolation rules from Track 1 (binding)

1. **Cap binding indipendente**: Track 1 e Track 2 hanno **ciascuno cap
   €5k** (esposizione potenziale massima cumulata €10k). NON è cap totale
   condiviso.
2. **Test statistici indipendenti**: Step 1 di Sector 2 fa propria BH
   correction sui suoi 5 test interni (A-E × hold window pre-registrato).
   NON si fa BH unificata cross-sector (sarebbero 10 test simultanei e
   romperebbe la pre-registration di Sector 1 a posteriori).
3. **Decision tree separato**: il verdict di Sector 2 (positive/negative)
   non influenza Sector 1 e viceversa. Closure di un sector non implica
   closure dell'altro.
4. **Paper trading separato**: `paper_trading/A_T+60_<YYYY-MM>_semis.csv`
   indipendente da quello di Sector 1. Dashboard separato
   `data/processed/dashboard_semis.html`. Decisione owner: paper trading
   Semis parte in parallelo a quello di Sector 1 appena Step 1 Semis
   chiude POSITIVE, anche se Sector 1 è ancora in W5.
5. **Drawdown trigger separato**: -30% review, -50% hard stop sul cap
   €5k del singolo Track. Non si sommano le perdite.

### Track 2 roadmap (informativa, non binding)

| Fase | Deliverable | Tempistica indicativa |
|---|---|---|
| W5b — `prereg_step1_semis.docx` v1.0 firmato + ADR 0005 accepted | docs/ | entro 2026-05-19 |
| W5b — `sectors/semis.yaml` validato pydantic | sectors/ | done (2026-05-12, hash `be3b7cd6...`) |
| W5b — event log scaffold `data/events/semis/` | data/events/semis/ | entro 2026-05-15 |
| W5b — `build-panel --sector semis` end-to-end verde | data/processed/panel_semis.parquet | entro 2026-05-19 |
| W6 — curation eventi B/C/D/E (target ≥10 eventi per categoria) | data/events/semis/ {ppa, orders, shocks, analyst}.csv | entro 2026-05-31 |
| W6 — Step 1 ufficiale Semis: event-study + decide | data/processed/event_metrics_semis.parquet + decision.json | entro 2026-06-07 |
| W6 — ADR 0006: verdict Semis | docs/decisions/ | entro 2026-06-07 |
| W7+ — paper trading Semis (se POSITIVE) | paper_trading/ + dashboard | da 2026-06-07 in poi |

Il rischio di "fishing" è mitigato dal fatto che la prereg viene firmata
**prima** di vedere i risultati event-study Semis. Nessuna iterazione
post-hoc sulla scelta universe/categorie.

## Consequences

### Positive

- **Frequenza segnali raddoppiata** (atteso): ~10-16 segnali/anno
  combinati (Sector 1 + Sector 2), con esposizione fino a €10k.
- **Validazione cross-sector** del framework: se l'edge PEAD net-of-cost
  esiste su due settori indipendenti, il pattern è meno specifico
  (meno overfit) e più generalizzabile.
- **Path concreto a Track 3+**: rare_earths, defense, biotech.
- **Zero modifiche al codice core**: tutto il lavoro è in contenuti.

### Negative / accettato

- **Concentrazione AI cycle**: semis è correlato con AI Infra. La
  diversificazione di rischio è parziale, non piena. Track 1 + Track 2
  insieme restano un bet concentrato sul ciclo AI. Diversificazione vera
  richiede settori non-tech (Track 3+).
- **Doppio overhead operativo**: curation manuale settimanale B/C/D/E
  raddoppiata; due paper log da monitorare; due dashboard da consultare.
  Stima +50% tempo settimanale dedicato al progetto.
- **Doppio costo cognitivo**: due prereg da rispettare, due decision tree
  separati, due ADR future per i verdict (0006 Semis, 0007 …).
- **TSM/ASML come ADR**: timing earnings asincrono (Taiwan/Olanda hanno
  fuso orario e calendari diversi); yfinance gestisce ma la verifica IR
  manuale è leggermente più complessa.

### Aperto

- Cross-sector hedging in fase live (W7+): se Sector 1 lungo NVDA e
  Sector 2 corto TSM (esempio ipotetico), la posizione netta è
  ambigua. La prereg Semis dovrà chiarire la policy.
- Re-evaluation di Sector 1 dopo accumulo di dati Sector 2: l'opzione
  di pooling Bayesiano cross-sector è esplicitamente vietata da questo
  ADR. Future evoluzioni richiederanno prereg v2 di **entrambi** i
  settori.

## Status history

- 2026-05-12 — Proposed (sessione W5 day 1, post-validation YAML semis)
- TBD — Accepted (al momento della firma del prereg_step1_semis.docx)
