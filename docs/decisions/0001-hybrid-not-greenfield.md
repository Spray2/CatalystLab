# ADR 0001 — Hybrid approach (not greenfield, not continuation) per il riuso da EquiTeria

- **Status**: Accepted
- **Date**: 2026-05-10
- **Authors**: Prometeus
- **Supersedes**: —

## Context

CatalystLab nasce dopo la chiusura di EquiTeria. Le opzioni discusse per il
trattamento della codebase legacy erano tre:

1. **Full continuation** — fork di EquiTeria, evoluzione incrementale.
2. **Greenfield** — riscrittura totale, zero riferimenti a EquiTeria.
3. **Hybrid** — riuso selettivo di moduli infrastrutturali, riscrittura della
   logica di research.

Il problema: EquiTeria implementa una doctrina **cross-sectional rank scoring
multifactor** (CLAUDE.md di EquiTeria §3, scoring/) che era esplicitamente
data-leak prone all'audit, mentre CatalystLab adotta una doctrina **event
study post-cost** (vedi `docs/prereg_step1_ai_infra.docx` §1, §6). Le due
doctrine non sono compatibili: continuation eredita debito tecnico e
metodologico, greenfield perde lavoro infrastrutturale già testato.

CLAUDE.md §4 di CatalystLab dichiarava il riuso di tre file specifici:
`data_fetch_yfinance.py`, `cost_model_fineco.py`, `plotting_utils.py`.
Ispezione diretta del repo `Spray2/EquiTeria` (clonato in
`/home/user/EquiTeria_ref/` come reference read-only, fuori dal working tree)
ha rilevato che **nessuno dei tre esiste con quei nomi**:

| File atteso (CLAUDE.md §4) | Stato in EquiTeria | Analogo |
|---|---|---|
| `data_fetch_yfinance.py` | assente | `src/equiteria/providers/yfinance_provider.py` + `src/equiteria/collectors/prices.py` |
| `cost_model_fineco.py` | assente | nessun match per "fineco"/"cost_model"/"commission" |
| `plotting_utils.py` | assente | nessun import matplotlib/seaborn |

EquiTeria stesso è in stato "Pre-implementation, W1 scaffolding only" (cit.
README), quindi anche i moduli analoghi sono stub o early-stage. Non c'è
"backlog di codice testato" da riusare quanto i pattern decisionali già
risolti dall'autore (semantica yfinance, NaN handling, anti-look-ahead).

## Decision

**Hybrid con riuso minimale di soli pattern, non di codice eseguibile.**

- ✅ **Riuso permesso**: pattern documentati di EquiTeria su yfinance (lette
  come reference, riscritte in `src/catalystlab/ingestion/prices.py`):
  - `auto_adjust=False` + uso esplicito di `Adj Close` per total-return AR
  - `actions=False` per non mischiare dividends/splits in OHLCV
  - bump `+1 day` sull'`end` (yfinance lo tratta exclusive)
  - tz-strip e `normalize()` su `DatetimeIndex`
  - Exception → empty DataFrame, never raise (caller-controlled)
  - schema `get_earnings_dates(limit=24)` per categoria A (PEAD)
- ❌ **Riuso vietato**: import diretto da `equiteria.*`, copia letterale di
  file, qualsiasi dipendenza filesystem da `/home/user/EquiTeria_ref/`. Il
  manifest di run (CLAUDE.md "reproducibility") non può dipendere da uno
  stato locale non versionato.
- ✅ **Scrittura ex novo richiesta**: `cost_model_fineco.py` (parametri
  prereg §5 binding — Fineco-specifici, non in EquiTeria) e
  `plotting_utils.py` (nessun analogo in EquiTeria; quando servirà in Layer
  5 sarà jinja2 + eventualmente matplotlib leggero).

## Consequences

**Positive**

- Indipendenza dal lifecycle di EquiTeria: se il repo upstream cambia o si
  rompe, CatalystLab non ne risente.
- Doctrina pulita: nessun residuo cross-sectional o sentiment-LLM (entrambi
  vietati dalla prereg §11).
- Manifest di run riproducibile: tutti gli input sono dentro il repo.

**Negative / accettato**

- Re-implementation cost: ~25-40 minuti aggiuntivi su Layer 2 vs
  copy-paste (incluso in T5 plan).
- Possibile duplicazione di edge case già risolti in EquiTeria che non
  abbiamo letto. Mitigato dal fatto che i file core di EquiTeria sono stati
  letti integralmente in fase di onboarding e i pattern rilevanti
  documentati sopra.

**Aperto**

- CLAUDE.md §4 elenca tre nomi-file che non corrispondono alla realtà
  EquiTeria. Update di CLAUDE.md §4 lasciato a una decisione separata
  (eventuale T2bis o aggiornamento contestuale al primo commit di Layer 2).
  Questa ADR è la fonte autoritativa fino ad allora.

## Status history

- 2026-05-10 — Accepted (sessione di onboarding W1 T2).
