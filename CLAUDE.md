# CatalystLab

> Event-driven research framework per retail trading post-cost (Italia, Fineco/Revolut). Multi-sector estendibile. Step 1 in corso: AI Infrastructure US.

---

## Always read first — vincoli non-negoziabili

### 1. Statuto del progetto

CatalystLab è un **framework di research personale**, non un sistema di trading produzione. Owner: Prometeus. Lingua di lavoro: italiano. Ambiente operativo: macOS + Python 3.11+ + Node 20+.

Il framework è **estendibile per design**: nessun layer del codice "core" sa di un settore specifico. I settori sono dichiarati in file YAML `sectors/<name>.yaml`. Aggiungere un nuovo settore = nuovo YAML, niente cambi al core.

### 2. Pre-registration come autorità unica

Il file `docs/prereg_step1_ai_infra.docx` è il **lockfile pre-registrato** del primo run (settore: AI Infrastructure). Tutte le decisioni di scope, soglia di success, decision tree post-Step 1, risk budget, e anti-pattern sono dichiarate lì.

**Regole d'oro**:

- Il `.docx` è l'autorità. Se questo `CLAUDE.md` o il codice contraddicono la pre-registration, la pre-registration vince.
- La pre-registration NON va modificata in funzione di risultati osservati. Iterazioni post-hoc sono permesse ma marcate come `prereg_step1_ai_infra_v2.docx` (nuovo file, nuovo timestamp), e il run successivo non conta come validazione statistica del primo.
- Prima di iniziare qualsiasi lavoro su Step 1, leggi `docs/prereg_step1_ai_infra.docx` per intero (tool: `extract-text` da skill `docx`).

### 3. Anti-pattern dichiarati (cosa NON fare)

Tratti dalla §11 della pre-registration. Sono binding nel codice e nelle decisioni:

- NON aggiungere ticker all'universe dopo aver iniziato la raccolta dati.
- NON modificare le definizioni di evento dopo aver iniziato la raccolta dati.
- NON aggiungere holding periods retrospettivamente.
- NON cambiare benchmark se XLK non produce il risultato sperato.
- NON usare sentiment LLM o social media nello Step 1.
- NON usare T+0 come holding period (data leakage operativo per fuso orario).
- NON considerare "quasi-success" (es. IC=0.045 con BH-corrected p=0.06) come success.
- NON saltare il paper trading di 1 mese anche se Step 1 è fortemente positivo.
- NON superare €5,000 cap binding senza pre-registration v2.
- NON modificare il drawdown trigger una volta in drawdown.

### 4. Riuso da EquiTeria — solo questi moduli

Approccio architetturale scelto: **ibrido**. Da EquiTeria si riusano solo i moduli infrastrutturali, **non** la logica di research:

- `data_fetch_yfinance.py` — fetch prezzi giornalieri (OK)
- `cost_model_fineco.py` — modello commissioni e spread (OK, con verifiche §5 prereg)
- `plotting_utils.py` — plot di base (OK)

**NON riusare**:

- Logica cross-sectional rank score (era data-leak prone)
- Sentiment LLM aggregator (bocciato dall'audit)
- Backtest harness (la logica event-time è fondamentalmente diversa)

In dubbio → riscrivi. EquiTeria è chiusa, non in continuation.

### 5. Decision tree post-Step 1

Sintetico, autorità completa nella prereg §8:

- **Positivo** (≥1 combinazione con IC>0.05, BH-corrected p<0.05, hit_rate>55%) → paper trading 1 mese (operational shakedown) → live €5k cap.
- **Negativo** (nessuna combinazione passa) → closure di AI Infra → nuovo progetto separato `sectors/rare_earths.yaml` con propria pre-registration.
- **Ambiguo** (passa IC ma non BH, o bootstrap CI attraversa zero) → trattato come negativo. Niente iterazioni.

### 6. Soglie statistiche binding

- Soglia IC base: > 0.05
- Multiple testing correction: Benjamini-Hochberg sui 5 test simultanei (categorie A/B/C/D/E)
- Hit rate threshold: > 55%
- Bootstrap CI 95% con 1000 resample, deve non attraversare zero

### 7. Disclaimer

Il progetto produce dati di research, non segnali di acquisto. L'autore non è consulente CONSOB. Per allocazioni reali oltre €5k binding, l'intento dichiarato è consulto CONSOB indipendente.

---

## Architettura

5 layer, ognuno con responsabilità chiara. Nessun layer downstream conosce dettagli upstream se non via interfaccia dichiarata.

```
┌────────────────────────────────────────────────────┐
│ Layer 1 — Config & registry                        │
│ sectors/<name>.yaml — universe, eventi, ipotesi    │
└────────────────────────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ Layer 2 — Data ingestion (sector-agnostic)         │
│ prezzi · earnings · news curated · cost model      │
│ → Output: panel dataset (parquet)                  │
└────────────────────────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ Layer 3 — Event study engine                       │
│ AR · CAR · IC per categoria · drift T+1..T+60      │
│ → Output: per-event metrics + per-category aggreg. │
└────────────────────────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ Layer 4 — Statistical validation                   │
│ BH correction · bootstrap CI · temporal CV         │
│ → Output: corrected p-values, decision flags       │
└────────────────────────────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ Layer 5 — Reporting & decision                     │
│ HTML report per settore · cross-sector compare     │
│ → Output: report.html + decision.json              │
└────────────────────────────────────────────────────┘
```

### Struttura del repo

```
catalystlab/
├── CLAUDE.md                       # questo file
├── README.md                       # one-pager pubblico
├── pyproject.toml                  # deps Python (uv o poetry)
├── docs/
│   ├── prereg_step1_ai_infra.docx  # AUTORITÀ — non modificare
│   ├── architecture.md             # dettagli architetturali
│   └── decisions/                  # ADR (Architecture Decision Records)
│       └── 0001-hybrid-not-greenfield.md
├── sectors/
│   └── ai_infra.yaml               # primo settore — Step 1 attuale
├── src/
│   └── catalystlab/
│       ├── __init__.py
│       ├── config/                 # Layer 1
│       │   ├── loader.py           # parse YAML + validation
│       │   └── schemas.py          # pydantic models
│       ├── ingestion/              # Layer 2
│       │   ├── prices.py           # yfinance wrapper
│       │   ├── earnings.py         # earnings dates
│       │   ├── news.py             # curated event ingestion
│       │   └── costs.py            # cost model Fineco
│       ├── eventstudy/             # Layer 3
│       │   ├── abnormal_returns.py
│       │   ├── aggregation.py
│       │   └── ic.py
│       ├── stats/                  # Layer 4
│       │   ├── bh_correction.py
│       │   ├── bootstrap.py
│       │   └── temporal_cv.py
│       └── reporting/              # Layer 5
│           ├── html_report.py
│           └── decision.py
├── data/
│   ├── raw/                        # dati grezzi (gitignored)
│   ├── processed/                  # panel dataset (parquet, gitignored)
│   └── events/                     # event log curato (committato)
│       └── ai_infra/
│           ├── earnings.csv        # auto-generato
│           ├── ppa.csv             # curato manualmente
│           ├── orders.csv          # curato manualmente
│           ├── shocks.csv          # curato manualmente
│           └── analyst.csv         # auto/curato
├── tests/                          # pytest, coverage > 80% sui Layer 3-4
└── notebooks/                      # exploration, NON in pipeline
```

### Principi di design

- **Layer purity**: nessun layer downstream chiama upstream direttamente. Tutto passa per i file di output dichiarati.
- **Reproducibility**: ogni run produce un manifest JSON con: timestamp, git commit hash, hash del YAML settore, hash dei dati input, parametri runtime.
- **Determinismo**: random seed dichiarato nel YAML settore. Bootstrap e CV usano lo stesso seed.
- **Idempotenza**: re-running lo stesso settore con gli stessi dati produce identici output. Cambi solo se cambiano dati o config.

---

## Stack tecnico

- **Python 3.11+** (vincolante: pandas 2+, type hints estesi)
- **uv** per dependency management (preferito a poetry per velocità). Fallback: poetry.
- **Librerie chiave**:
  - `pandas`, `numpy`, `scipy.stats` — core data + stats
  - `yfinance` — prezzi (con sanity check manuale)
  - `pydantic v2` — config validation
  - `statsmodels` — OLS per beta estimation
  - `pytest` + `pytest-cov` — testing
  - `jinja2` — HTML report
- **No-no**: scikit-learn (overkill per Layer 3), TensorFlow/PyTorch (zero ML in Step 1), pandas-ta (TA non rilevante), Streamlit (no UI).

---

## Current focus — Settimana 4 (paper trading prep o closure)

> Settimana 3 chiusa. Riepilogo W3 in `## Settimana 3 — riepilogo (chiusa)` qui sotto.

### Obiettivo W4

A fine W3, sul panel smoke-data il framework restituisce `verdict=POSITIVE`
con A T+60 (IC=0.319 BH-p=0.048 hit=62.5% CI=[0.063, 0.546]). Per prereg
§8.1 questo dovrebbe far partire **paper trading 1 mese → live €5k cap**.

**Decisione W4 (binding)**:

1. **Re-curation event logs** (per Step 1 reale, non smoke): aumentare
   B/C/E sopra n=10 ciascuno per portare BH-p su solid ground (W2 smoke
   ha n=2-4 → tutte ambigue). Earnings (cat A) sono auto e già a n=178.
2. **Validation manuale 3 ticker random** earnings dates contro Yahoo
   Finance web (prereg §3.1 quality gate).
3. **Decisione** se il run smoke vale come Step 1 ufficiale o se serve
   re-run con event logs estesi.
4. **Eventualmente**: paper trading set-up (cap €0 reale, 1 mese
   tracking della combinazione vincente A T+60).

### Deliverable W4 (provisorio)

- `docs/decisions/0002-step1-final-run.md` — ADR che documenta se il run
  smoke vale o se serve re-run.
- `paper_trading/<combinazione>_<period>.csv` — log di paper trading
  (mese 1).
- Report finale Step 1 (HTML) con decisione binding.

### Task list W4 (sketched, finalize at start of W4 session)

1. Estendere event logs C/E (target ≥10 per cat).
2. Re-run `event-study` + `decide` con event logs aggiornati.
3. Verifica manuale 3 random earnings dates.
4. Decision: smoke run vale o re-run? ADR 0002.
5. Se POSITIVO: setup paper trading 1 mese.
6. Se NEGATIVO/AMBIGUO: closure documentata + sketch Rare Earths sector.

---

## Settimana 3 — riepilogo (chiusa)

Layer 4 (stats) + Layer 5 (reporting) completi. Pipeline `build-panel
→ event-study → decide` end-to-end verde. Smoke verdict: **POSITIVE**
con A T+60.

| # | Task | Deliverable |
|---|---|---|
| 2 | BH-FDR correction | `stats/bh_correction.py::bh_correct_pvalues + apply_bh_per_holding_window`, n_tests=5 enforced |
| 3 | Bootstrap CI 95% | `stats/bootstrap.py::bootstrap_ic_ci + apply_bootstrap_to_summary`, deterministic seed=42 (random_seed YAML) |
| 4 | Temporal CV (pre/post 2025) | `stats/temporal_cv.py::compute_temporal_decay`, decay = ic_post - ic_pre |
| 5 | Stability check (top-5 |CAR|) | `stats/stability.py::compute_stability` |
| 7 | Decision logic | `reporting/decision.py::decide`, verdict positive/negative/ambiguous + winning/ambiguous_combinations |
| 6 | HTML report | `reporting/html_report.py::render_report` + `templates/report.html.j2` |
| 7 | CLI `decide` | `catalystlab decide --sector ai_infra` orchestra Layer 4+5 → decision.json + report.html |
| 8 | Test coverage gate | 223 tests cumulativi (~91%); Layer 4 stats 100% per modulo |
| 9 | End-to-end smoke | Verdict POSITIVE confermato su panel reale |

**Smoke run W3 (decide su panel + 235 eventi W2)**:

| Cat × Window | n_valid | IC | BH-p | hit_rate | CI 95% | Status |
|---|---|---|---|---|---|---|
| **A × 60** | **65** | **0.319** | **0.0483** | **62.5%** | **[0.063, 0.546]** | **WIN** |
| C × 1 | 3 | 1.000 | NaN | 100% | NaN (n<2 valid bootstrap) | ambig (BH NaN) |
| C × 5 | 3 | 1.000 | NaN | 100% | NaN | ambig (BH NaN) |
| E × 60 | 4 | 0.738 | 0.437 | 75% | [-0.65, +0.95] | ambig (BH+CI fail) |

**Verdict: POSITIVE per prereg §8.1**. ADR 0002 in W4 deciderà se questo
smoke conta come Step 1 ufficiale o se serve re-run con event logs C/E
estesi (n=2-4 sono comunque sotto-poteri).

**Issues note (per W4)**:

- Cat C / E hanno n troppo piccolo per BH solido → re-curation
  necessaria prima della dichiarazione di Step 1 ufficiale
- earnings.csv auto-overwritten conflitta col committed scaffold —
  outstanding architectural cleanup
- HTML report ha colonne ma nessun grafico (matplotlib/plotly fuori
  scope W3) — vedere se utile in W4
- Cat D `xlk_t1_return` runtime fill (T1 W3 deferred) funziona ma il
  layering è messy (CLI lo fa) — refactoring possibile

---

## Settimana 2 — riepilogo (chiusa)

Layer 3 (event study) completo. Pipeline `build-panel → event-study` end-to-end verde su dati reali.

| # | Task | Deliverable |
|---|---|---|
| 1 | Curate event logs B/C/D/E | 15 eventi pubblici curati con audit trail |
| 2 | Beta estimation rolling | `eventstudy/abnormal_returns.py::estimate_beta` per-evento, finestra 252gg con esclusione 30gg |
| 3 | AR / CAR vectorized | `compute_ar_car` + `compute_event_metrics`, schema long `[ticker, event_date, event_type, event_magnitude, holding_window, beta, n_obs, car]` |
| 4 | Aggregation per cat × window | `eventstudy/aggregation.py::aggregate_event_metrics`, mean_car_gross/net, hit_rate, std, costo round-trip 95.5 bps |
| 5 | IC Spearman + p-value | `eventstudy/ic.py::compute_ic`, scipy spearmanr, BH applicato in W3 |
| 6 | Overlapping events policy | `enumerate_all_events` bypassa il dedup di `build_panel`, `events_override` parameter in compute_event_metrics |
| 7 | CLI event-study | `catalystlab event-study --sector ai_infra` → `event_metrics_<sector>.parquet` + `event_summary_<sector>.parquet` + manifest |
| 8 | Hypothesis property tests | scale invariance, IC monotone-transform, hit_rate ∈ [0,1], cost additivity (~10 hypothesis tests cumulativi) |
| 9 | Sanity check end-to-end | `tests/test_e2e_sanity.py` null-event IC < 0.2 su panel reale |

**Smoke run W2 (235 eventi su panel 2023-2026)**:

| Cat | Window | n_valid | IC | p-value | hit_rate | mean_car_net (bps) |
|---|---|---|---|---|---|---|
| A | 60 | 65 | 0.319 | 0.010 | 62.5% | +573 |
| D | 1 | 37 | -0.428 | 0.008 | 30% | -14 |
| D | 5 | 37 | 0.339 | 0.040 | 51% | +243 |
| D | 20 | 37 | -0.338 | 0.041 | 38% | -23 |
| D | 60 | 37 | -0.356 | 0.031 | 54% | +1230 |

**Una sola combinazione passa la soglia uncorrected (cat A, T+60)**: IC=0.319 p=0.010 hit_rate=62.5%. **NON è il run Step 1**: la BH correction su 5 test (W3) è ancora da applicare. Inoltre eventi B/C/E con n=2-4 sono underpowered.

**Issues note (per W3)**:

- Cat D mostra IC negativi consistenti su 3/4 windows → mean-reversion pattern? Worth investigating in W3 via bootstrap CI
- earnings.csv auto-overwritten da build-panel conflitta con il committed state header-only → architectural cleanup deferito
- IC di cat B/C/E ha p-value NaN per n<5 → smoke statistical inadequato, serve curation più estesa per Step 1 vero (probabilmente >30 eventi per cat per BH significance)
- `_fill_d_magnitudes` runtime nel CLI funziona ma potrebbe spostarsi in `enumerate_all_events` (cleaner design)

---

## Settimana 1 — riepilogo (chiusa)

Layer 1+2 completi. Tag `v0.1.0-step1-w1`.

| # | Task | Commit | Notes |
|---|---|---|---|
| 1 | Init repo + scaffolding | `5a76da1` | `uv` + struttura 5 layer |
| 2 | Pre-reg + ADR 0001 | `54f44a1` | hybrid (not greenfield) reuse from EquiTeria |
| 3 | YAML + pydantic schemas | `bb45cc8` | T+0 enforced, 5 cat A-E enforced, frozen models |
| 4 | YAML loader + manifest | `cd254be` | sha256 audit anchor + git commit hash |
| 5 | Prices fetcher (yfinance) | `f379f1e` | parquet cache, NaN drop, tz-strip, end-bump |
| 6 | Earnings + SUE | `6516483` | prereg §3.1 formula verbatim, fallback binario |
| 7 | Cost model Fineco | `ea34345` | Interpretation B (round-trip totals), 95.5 bps su €1k |
| 8 | Event log scaffolds | `ae5f26e` | 5 CSV + README curatela |
| 9 | Panel builder + CLI | `538e418` | end-to-end run verde, 6363 righe panel |
| 10 | Test consolidation | _W1 closure_ | conftest fixture, hypothesis estesa, 77 test, 91% cov |

**DoD W1 raggiunta**:

- [x] `uv run python -m catalystlab.cli build-panel --sector ai_infra` produce `data/processed/panel_ai_infra.parquet` (6363 righe verificate end-to-end)
- [x] Coverage Layer 1+2: 91% (target >70%)
- [x] README aggiornato con quickstart funzionante
- [x] Manifest JSON generato in `data/manifests/<timestamp>_ai_infra.json` (gitignored come da convenzione runtime)
- [x] CLAUDE.md "Current focus" aggiornata a W2 (questo blocco)

**Note operative emerse in W1** (per W2 e oltre):

- yfinance earnings_dates è scrape-based e intermittently rate-limited → integration test difensivo (skip on empty), pipeline robusto a 0 righe
- GEV (GE Vernova) IPO Apr 2024 → 309 giorni di gap nel periodo prereg pre-IPO; gap detection lo rileva. Decisione: il panel li lascia NaN, Layer 3 deve filtrare per ticker effettivamente tradato alla data dell'evento
- Overlapping events policy attuale: priority A→E, first-match wins. Da rivedere in W2 (prereg §12 q.1)
- `ar_vs_xlk_proxy` nel panel è simple diff (non beta-adjusted); Layer 3 sostituirà con AR β-corretto

---

## Convenzioni di lavoro

### Git

- Branch model: trunk-based, lavori su `main`
- Commit message: `<type>: <subject>` con type ∈ {feat, fix, docs, refactor, test, chore}
- **Mai committare**: dati raw/processed (eccetto event logs curati), API keys, file > 10MB
- Tag: `v0.1.0-step1-w1`, `v0.1.0-step1-w2`, ecc.

### Code style

- Type hints **obbligatorie** su tutte le funzioni public. Pydantic per i data model.
- Docstring stile Google
- Linter: `ruff check` + `ruff format` (no black, no isort)
- Niente magic numbers — costanti in modulo `constants.py` o nel YAML settore
- Niente `print()` in codice di pipeline — usa `logging` con livelli appropriati

### Testing

- `pytest` per unit, `pytest-cov` per coverage
- I test su `eventstudy/` e `stats/` (Layer 3-4) sono **non-negoziabili**: questi sono i moduli dove un bug invalida la prereg
- Property-based testing con `hypothesis` per le funzioni statistiche dove ha senso (es. AR computation)

### Decisioni architetturali

Ogni decisione non banale → ADR in `docs/decisions/000N-<title>.md`. Formato:
- Context (cosa c'è in gioco)
- Decision (cosa abbiamo scelto)
- Consequences (cosa cambia, cosa accettiamo)
- Status (proposed | accepted | superseded)

Esempio già presente: `0001-hybrid-not-greenfield.md`.

---

## Workflow operativo con Claude Code

### Prima di ogni sessione

1. Leggi questo file (`CLAUDE.md`)
2. Leggi `docs/prereg_step1_ai_infra.docx` se non già in contesto recente
3. Verifica branch git, status, ultimo commit
4. Verifica che la sezione "Current focus" sia aggiornata

### Durante una sessione

- Ogni task significativo → branch o commit atomico
- Ogni dubbio architetturale → ADR
- Ogni deviazione dai principi sopra → segnalare esplicitamente all'owner prima di procedere
- Se incontri qualcosa che contraddice la pre-registration → **fermati e chiedi**, non procedere

### Fine sessione

- Aggiorna "Current focus" se necessario
- Aggiorna eventuali ADR in stato `proposed` → `accepted` o vice versa
- Commit finale con riassunto progress

### Cosa fare se Claude Code suggerisce qualcosa che non è in linea

- Esempi: aggiungere indicatori tecnici al panel, sentiment scoring, ML model, hyperparameter tuning
- Risposta: ricorda il vincolo della pre-registration. Lo Step 1 è event study, non quant trading. Non aggiungere feature non pre-registrate.

---

## Riferimenti esterni utili (per Claude Code)

- MacKinlay, A. C. (1997). *Event Studies in Economics and Finance*. JEL — riferimento metodologico per Layer 3
- Benjamini, Y., & Hochberg, Y. (1995). *Controlling the False Discovery Rate*. JRSS — riferimento per Layer 4
- yfinance docs: https://github.com/ranaroussi/yfinance
- Pandas-DataReader fallback: https://pandas-datareader.readthedocs.io

---

## Stato del progetto

| Item | Status |
|------|--------|
| Pre-registration v1.0 | ✅ firmata, lockfile committato |
| Repo init | ✅ W1 T1 (`5a76da1`) |
| Layer 1 (config) | ✅ W1 T3-T4 |
| Layer 2 (ingestion) | ✅ W1 T5-T9 (panel parquet end-to-end) |
| Layer 3 (event study) | ✅ W2 T2-T9 (event metrics + summary parquet end-to-end) |
| Layer 4 (stats) | ✅ W3 T2-T5 (BH + bootstrap + temporal CV + stability) |
| Layer 5 (reporting) | ✅ W3 T6-T7 (HTML report + decision.py + CLI decide) |
| Step 1 run smoke | ✅ verdict POSITIVE su A T+60 (smoke data) |
| Decision (positivo/negativo/ambiguo) | ⏳ W4 — re-curation o paper trading? |

---

*Ultimo aggiornamento: 2026-05-10 — chiusura Settimana 3*
