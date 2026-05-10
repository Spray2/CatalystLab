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

## Current focus — Settimana 2 (Layer 3 event study)

> Settimana 1 chiusa. Riepilogo W1 in `## Settimana 1 — riepilogo (chiusa)` qui sotto.

### Obiettivo W2

Implementare **Layer 3 — event study engine** sopra il panel parquet prodotto da W1. A fine W2 il framework deve calcolare, per il settore `ai_infra`, le metriche statistiche per ogni (categoria × holding window) come dichiarato in prereg §6.

### Deliverable W2

1. `eventstudy/abnormal_returns.py` — calcolo AR(i, t+k) e CAR(i, [a,b]) per ogni evento, con beta i.e. **β-adjusted AR** sostituendo il proxy `r_i - r_xlk` di W1. Beta stimato su rolling 252gg con esclusione finestra 30gg pre-evento (prereg §6.1).
2. `eventstudy/aggregation.py` — per (categoria, holding window): mean_CAR, hit_rate, count, std. Risoluzione overlapping events (prereg §12 q.1).
3. `eventstudy/ic.py` — IC Spearman tra magnitude evento e CAR risultante.
4. Schema output: `data/processed/event_metrics_<sector>.parquet` con `(category, holding_window, n_events, mean_car, hit_rate, ic, ic_pvalue)`.
5. CLI subcommand: `catalystlab event-study --sector ai_infra` legge `panel_<sector>.parquet`, produce `event_metrics_<sector>.parquet` + manifest.
6. Test coverage Layer 3 ≥ **80%** (CLAUDE.md "Tests" — Layer 3-4 non-negoziabili). Property-based test su AR computation (hypothesis).

### Task list W2 (in ordine di esecuzione)

1. **Curare event logs B/C/D/E** (manuale, ≥10-15 eventi totali per consentire smoke statistical test).
2. **Beta estimation rolling**: helper in `eventstudy/abnormal_returns.py`, test contro statsmodels OLS.
3. **AR / CAR per evento**: vectorized su panel parquet.
4. **Aggregazione per categoria × window**: mean_CAR, hit_rate.
5. **IC Spearman + p-value uncorrected**: `eventstudy/ic.py`.
6. **Overlapping events policy**: documentata + test edge case.
7. **CLI event-study**: subcommand + manifest.
8. **Hypothesis tests** su AR vectorisation invariants.
9. **Sanity check end-to-end**: smoke run su panel reale, verifica IC≈0 su categoria con eventi random (null check).

### Definition of Done — Settimana 2

- [ ] `uv run python -m catalystlab.cli event-study --sector ai_infra` produce `data/processed/event_metrics_ai_infra.parquet`
- [ ] Test coverage Layer 3 ≥ 80%
- [ ] AR/CAR computation ha invariant tests (hypothesis) + sanity check sui dati reali
- [ ] CLAUDE.md "Current focus" aggiornata per Settimana 3 (Layer 4 + Layer 5)

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
| Layer 3 (event study) | ⏳ Settimana 2 (in corso) |
| Layer 4 (stats) | 🔒 Settimana 3 |
| Layer 5 (reporting) | 🔒 Settimana 3 |
| Step 1 run completo | 🔒 fine Settimana 3 |
| Decision (positivo/negativo/ambiguo) | 🔒 inizio Settimana 4 |

---

*Ultimo aggiornamento: 2026-05-10 — chiusura Settimana 1*
