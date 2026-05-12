# Pre-registration — Step 1: Semiconductors US (Track 2)

> **Sorgente per il lockfile** `prereg_step1_semis.docx` v1.0.
> Una volta riportato in `.docx`, firmato e committato, questo `.md` resta
> solo come **riferimento leggibile**. Il `.docx` è l'autorità (CLAUDE.md §2).

- **Versione**: 1.0
- **Data lockfile**: TBD (al momento della firma)
- **Owner**: Prometeus
- **Decisione di apertura Track 2**: ADR 0005
- **Settore**: Semiconductors US (codice interno: `semis`)
- **Stato**: Drafting → Firmato (TBD)

---

## §0 — Note sulla pre-registration

Questo documento è il **lockfile** dello Step 1 di Track 2. Tutti i
parametri di scope, soglia di success, decision tree post-Step 1, risk
budget e anti-pattern sono **dichiarati qui prima di vedere i risultati**.
Una volta firmato:

- Modifiche post-hoc non sono ammesse. Iterazioni richiedono `prereg_step1_semis_v2.docx`.
- Il run con prereg v2 non conta come validazione statistica del run v1.
- Ogni discrepanza fra questo documento, `CLAUDE.md`, `sectors/semis.yaml`
  o il codice è risolta a favore di questo `.docx`.

Track 2 è **completamente indipendente** da Track 1 (`prereg_step1_ai_infra.docx`):
universe, statistical test, decision tree, cap binding e paper trading
sono separati per costruzione (ADR 0005 isolation rules).

---

## §1 — Statuto e obiettivo

CatalystLab Track 2 estende il framework event-driven a un secondo
settore, **Semiconductors US**, in parallelo a Track 1 (AI Infrastructure
US). L'obiettivo dello Step 1 Semis è identico, mutatis mutandis, a
quello di Track 1:

> Verificare se esiste un edge statistico **post-cost** (net-of-Fineco-95.5-bps)
> investibile da retail italiano sui semiconductor US large-cap, su
> finestre di evento T+1 / T+5 / T+20 / T+60, su 5 categorie di evento
> pre-dichiarate.

Track 2 NON è una strategia di trading produzione; è un test scientifico.
Per allocazioni reali oltre €5k binding di Track 2, è richiesto consulto
CONSOB indipendente.

---

## §2 — Universe e benchmark

### §2.1 — Universe (8 ticker, lockati)

| Ticker | Nome | Market | Sotto-tipo |
|---|---|---|---|
| NVDA | NVIDIA Corp                 | NASDAQ | gpu_ai_accelerator |
| AMD  | Advanced Micro Devices      | NASDAQ | cpu_gpu_ai |
| AVGO | Broadcom Inc                | NASDAQ | networking_custom_silicon |
| MU   | Micron Technology           | NASDAQ | memory_dram_hbm |
| TSM  | Taiwan Semiconductor ADR    | NYSE (ADR) | foundry_leading_edge |
| ASML | ASML Holding ADR            | NASDAQ (ADR) | euv_lithography |
| AMAT | Applied Materials           | NASDAQ | semi_equipment |
| LRCX | Lam Research                | NASDAQ | semi_equipment_etch |

Universe lockato. **Vietato** aggiungere/rimuovere/sostituire ticker dopo
firma (anti-pattern §11.1).

Logica di selezione (per audit trail, non rinegoziabile):
- NVDA, AMD: GPU/AI accelerator dominators
- AVGO: networking + custom AI silicon (Google TPU)
- MU: memoria HBM (input cruciale GPU AI)
- TSM: foundry leading-edge (produce per NVDA, AMD, AVGO)
- ASML: monopolio EUV lithography (input critico tutti i fab leading-edge)
- AMAT, LRCX: semiconductor equipment (deposition + etch, beneficiari capex fab)

### §2.2 — Benchmark

- **Primario**: SOXX (iShares Semiconductor ETF). Usato per AR computation
  e per `event_magnitude` di cat D (sector shock proxy).
- **Secondario**: XLK (SPDR Technology Select Sector). Usato come
  cross-check di robustezza in temporal CV ed eventualmente in stability
  check; NON sostituisce SOXX nei risultati binding (anti-pattern §11.4).

Parametri stima β rolling (per AR vs benchmark):
- `beta_window_days`: 252
- `beta_exclusion_window_days`: 30 (escludi i 30 giorni immediatamente
  precedenti l'evento per evitare contaminazione)

---

## §3 — Definizione delle 5 categorie di evento (A-E)

5 ipotesi simultanee, BH-corrected at `bh_alpha=0.05` (§6.3).

### §3.1 — Categoria A: Earnings (PEAD)

**Definizione**: annuncio earnings trimestrale di una società dell'universe.
Evento qualifica per analysi se `|SUE| > 1.0`, dove:

```
SUE_t = (actual_eps_t - estimate_consensus_t) / std(estimate over previous 8 quarters)
```

Lo std è calcolato sulla rolling window dei 8 trimestri precedenti
(current row excluded via shift, no leakage). Threshold lockato a 1.0
(top/bottom decile).

Fallback se finestra consensus < 4 estimati: `surprise_sign = sign(actual − estimate)`,
`has_consensus = False`, `sue = NaN`. Eventi senza SUE valido sono
**inclusi** nel panel ma trattati come binary (`magnitude = surprise_sign`).

**Source**: yfinance `get_earnings_dates` + manual QC su 3 ticker random
vs IR press release.

**Ipotesi binding**: drift CAR significativamente ≠ 0 in T+1..T+60 post
earnings event, con segno coerente con `surprise_sign`.

### §3.2 — Categoria B: Hyperscaler Design Win

**Definizione**: annuncio pubblico di design win / preferred supplier /
custom silicon partnership fra una società dell'universe e uno degli
**hyperscaler ufficiali**: MSFT, META, AMZN, GOOGL, ORCL.

**Magnitude**: binary (1.0). Se deal value disclosed in USD, registrato
in `deal_value_usd` per reference ma **non usato** dal panel builder
(che usa il fallback binary).

**Esempi qualificanti**:
- "NVDA selected by META for H100/H200 cluster, $X-billion"
- "Google TPU built on AVGO custom silicon, multi-year deal"
- "Microsoft Maia AI chip foundry win to TSM"

**Esempi NON qualificanti**:
- Partnership generica non hyperscaler-specific
- Joint ventures industriali non con i 5 hyperscaler

**Source**: corporate press releases + Reuters/Bloomberg curated manually.

**Ipotesi binding**: AR positivo in T+1..T+20.

### §3.3 — Categoria C: Capacity / Order Intake

**Definizione**: press release o 8-K filing che annuncia uno di:
1. **Fab announcement**: costruzione di nuova fab o espansione esistente
   con capex stimato/dichiarato.
2. **Order intake**: ordine singolo o cumulato disclosure > $1B.
3. **Backlog update**: variazione percentuale del backlog dichiarata > 10%.

Threshold di qualificazione (any_of):
- `deal_value_usd > $1.000.000.000` (1 miliardo USD), OR
- `backlog_change_pct > 0.10` (10%)

**Magnitude**: `deal_value_usd` numerico se disclosed, altrimenti
`backlog_change_pct`. Almeno uno dei due deve essere ≥ threshold.

**Source**: SEC 8-K filings + investor relations releases.

**Ipotesi binding**: AR positivo in T+1..T+20.

### §3.4 — Categoria D: Sector Shock

**Definizione**: evento macro/policy/geopolitico che impatta l'**intero
settore semis** (non singolo ticker). Tipologia ammessa:
- BIS / Commerce export controls verso Cina (es. Oct 2022, Oct 2023, Dec
  2024 HBM, Jan 2025 AI Diffusion Framework, Dec 2025 H200 reversal)
- China retaliation announcements
- Supply chain disruption a impatto industriale (es. earthquake Taiwan,
  ASML EUV machine production issue)
- Major geopolitical conflict con effetti settore (es. blocco fab
  Taiwan)

**Magnitude**: `soxx_t1_return` — return SOXX in T+1 dell'evento, calcolato
a runtime (NON da inserire manualmente). Eventi senza T+1 di mercato US
sono esclusi.

**Source**: Reuters / FT / BIS official press releases.

**Ipotesi binding**: reaction + mean-reversion patterns a livello settore.

**Nota tecnica**: cat D è broadcast a tutti gli 8 ticker dell'universe
(no `ticker` field nel CSV). Il panel builder duplica la riga su tutti i
ticker.

### §3.5 — Categoria E: Analyst Rating Tier-1

**Definizione**: rating change o target price revision da uno dei tier-1
banks ammessi:

`["Goldman Sachs", "JP Morgan", "Morgan Stanley", "Bank of America", "Citi", "UBS"]`

Threshold di qualificazione: `|target_change_pct| > 0.10` (10%).

`target_change_pct = (new_target - old_target) / old_target`

**Magnitude**: `target_change_pct` con segno (positive = bullish, negative
= bearish).

**Source**: Bloomberg consensus aggregator o Yahoo Finance recommendations,
manualmente curato (link diretto al report o alla pubblicazione di
secondary source riconosciuta).

**Ipotesi binding**: AR in T+1..T+5 con segno coerente con
`target_change_pct`.

---

## §4 — Holding windows

`holding_windows: [1, 5, 20, 60]` (giorni di borsa US).

**T+0 esplicitamente escluso** per data leakage operativo: il retail
italiano non può eseguire ordine nello stesso giorno dell'annuncio (fuso
orario, settlement, IR press release timing variabile). Anti-pattern
§11.2.

Holding windows lockate. **Vietato** aggiungere holding period
retrospettivamente (anti-pattern §11.3).

---

## §5 — Cost model (Fineco)

Identico a Sector 1 (Fineco non differenzia per settore underlying).

### §5.1 — Parametri

| Parametro | Valore | Fonte |
|---|---|---|
| Commissione per eseguito (USA fixed) | €3.65 (~$3.95) | Fineco listino 2024 |
| Spread round-trip (mid-range) | 7.5 bps | §5.2 range 5-10 bps |
| FX round-trip (multivaluta EUR/USD) | 15.0 bps | Fineco multivaluta |
| Default position size | €1.000 | worst-case commission incidence |

### §5.2 — Verifica matematica round-trip su €1000

```
Commission round-trip:   2 × €3.65 = €7.30  → 73 bps
Spread round-trip:                            7.5 bps
FX round-trip:                                15 bps
TOTALE:                                      95.5 bps
```

Range dichiarato in §5.2: **75-100 bps**. Verifica matematica entro
range: ✅.

Cost model è Interpretation B (round-trip totals), non per-execution.

---

## §6 — Soglie statistiche binding (no quasi-success)

Identiche a Sector 1, ma applicate al test indipendente Semis.

### §6.1 — Test individuali per categoria

Per ogni `(categoria, holding_window)` calcoliamo:
- **IC Spearman** fra `event_magnitude` e CAR realizzato
- **Hit rate**: % eventi con `sign(CAR) == sign(event_magnitude)`
- **Mean CAR netto**: post-cost (95.5 bps)
- **Bootstrap CI 95%** con 1000 resample (random_seed=42)

### §6.2 — Multiple testing correction

Benjamini-Hochberg FDR su 5 categorie A-E, separato per ogni
holding_window (5 test simultanei per window).

`bh_alpha = 0.05`

### §6.3 — Soglie binding di success

Una combinazione `(categoria, holding_window)` è classificata POSITIVE
**solo se** soddisfa tutte le seguenti:

1. `IC > 0.05` (Spearman, uncorrected)
2. `BH-corrected p < 0.05`
3. `hit_rate > 55%`
4. Bootstrap CI 95% **non attraversa zero**

**Quasi-success vietato** (es. IC=0.045 con BH-p=0.06, o CI [-0.01, +0.50]).
Anti-pattern §11.7.

---

## §7 — Periodo

`period: 2023-01-01 → 2026-04-30`

Identico a Sector 1 per massima comparabilità del regime macro:
- Post-ChatGPT (lancio nov 2022) → boom AI cycle
- Post-COVID supply chain stabilizzata
- Era di BIS export controls (a partire da Oct 2022)

Eventuali tickers con prezzi missing a inizio periodo (es. società quotate
dopo gennaio 2023) sono lascati NaN nel panel; Layer 3 filtra ticker per
evento a date effettive di mercato.

---

## §8 — Decision tree post-Step 1 Semis

### §8.1 — Esito POSITIVE

Se ≥ 1 combinazione `(categoria, holding_window)` passa **tutti i 4
criteri** di §6.3:

1. Paper trading 1 mese su quella combinazione, con cap €1.000/trade
   simulato. Operational shakedown (NOT statistical re-validation).
2. Se paper OK → live trading **cap €5.000 binding Track 2** (separato
   da Track 1, vedi ADR 0005).
3. Track 1 e Track 2 in live possono coesistere; esposizione totale
   teorica fino a €10.000 (cap individuali sommati).

**Paper trading Track 2 può partire in parallelo a Track 1 W5** (decisione
owner 2026-05-12, ADR 0005 §4): se Step 1 Semis chiude POSITIVE prima
che Track 1 finisca la sua W5, paper Semis parte subito.

### §8.2 — Esito NEGATIVE

Se **nessuna** combinazione passa tutti i 4 criteri:

1. Closure di Track 2 (Semis). Nessuna iterazione post-hoc su universe,
   categorie o threshold.
2. Sector 1 (AI Infra) prosegue indipendentemente in paper / live (non
   è invalidato da Negative di Semis).
3. Decisione separata su Track 3 (rare_earths, defense, biotech) — fuori
   scope di questa prereg.

### §8.3 — Esito AMBIGUOUS

Se almeno una combinazione passa **alcuni** ma non **tutti** i 4
criteri (es. passa IC ma non BH, o bootstrap CI attraversa zero):

→ Trattato come NEGATIVE per l'azione (§8.2). Nessuna iterazione, nessuna
"quasi-success".

---

## §9 — Risk budget Track 2

- Cap binding: **€5.000** indipendente da Track 1. Posizione massima per
  trade: €5.000 (intero cap).
- Default position size paper: €1.000 (testa cost incidence worst-case).
- Default position size live: TBD post-paper, comunque ≤ €5.000.
- Drawdown trigger (binding, identico Track 1):
  - **-30%** sul cap Track 2 → review obbligatoria con eventuale stop
    temporaneo
  - **-50%** sul cap Track 2 → hard stop, closure Track 2 in attesa
    di analisi post-mortem
- Anti-pattern §11.10: **vietato modificare drawdown trigger una volta
  in drawdown**.

---

## §10 — Reproducibility

- `random_seed: 42` (identico Track 1, per coerenza di bootstrap/CV
  random draws fra Track diversi)
- Manifest JSON generato per ogni run con: timestamp, git commit hash,
  SHA256 hash dello YAML settore (lockfile audit anchor), hash dei dati
  input, parametri runtime
- Idempotenza: re-run con stessi dati e stessa config → output identici

---

## §11 — Anti-pattern (binding nel codice e nelle decisioni)

Lista identica a Sector 1 + 1 punto aggiuntivo specifico Track 2.

1. NON aggiungere ticker all'universe dopo aver iniziato la raccolta dati.
2. NON modificare le definizioni di evento (categorie, threshold) dopo
   aver iniziato la raccolta dati.
3. NON aggiungere holding periods retrospettivamente.
4. NON cambiare benchmark se SOXX non produce il risultato sperato.
5. NON usare sentiment LLM o social media nello Step 1.
6. NON usare T+0 come holding period.
7. NON considerare "quasi-success" (es. IC=0.045 con BH-corrected p=0.06)
   come success.
8. NON saltare il paper trading di 1 mese anche se Step 1 è fortemente
   positivo.
9. NON superare €5.000 cap binding Track 2 senza pre-registration v2.
10. NON modificare il drawdown trigger una volta in drawdown.
11. **NON poolare statisticamente Sector 1 e Sector 2**: ogni Step 1 è
    test indipendente con propria BH correction sui suoi 5 test interni.
    Cross-sector pooling (es. 10 test simultanei BH-corrected unificati)
    è espressamente vietato e richiederebbe re-firma di **entrambe** le
    prereg.

---

## §12 — Open questions (risolte a implementation time, tracked qui)

| Domanda | Status | Risoluzione tentativa |
|---|---|---|
| `overlapping_events_same_window` | Inherit Sector 1 policy | priority A→E first-match wins nel `build_panel`; `enumerate_all_events` bypassa il dedup per IC indipendente per categoria |
| `earnings_vs_design_win_same_day` (cat A vs cat B coincidenza) | Open | TBD; per ora priority A→E come Sector 1 |
| `adr_timing_handling` (TSM/ASML earnings asincroni) | Closed | yfinance ancora le date a US trading day; verifica IR manuale richiesta per primi 3 ticker random in QC |
| `nvda_split_handling` (10-for-1 2024-06-10) | Closed | yfinance `adj_close` gestisce; cat D scan per false-shock attorno alla data |
| `cross_listing_volume` (ADR thinner US volume) | Closed | cost model Fineco è US-execution-only; volume liquidity ADR verificata empiricamente in QC |
| `cat B counterparty list extension` | Closed | hyperscalers list identica Sector 1 (MSFT, META, AMZN, GOOGL, ORCL); aggiungere Apple richiederebbe v2 |

---

## §13 — Disclaimer

Track 2 produce dati di research, non segnali di acquisto. L'autore non
è consulente CONSOB. Per allocazioni reali oltre €5k binding Track 2,
l'intento dichiarato è consulto CONSOB indipendente.

Track 1 e Track 2 in coesistenza possono comportare esposizione fino a
€10.000 totali (cap individuali sommati). Owner riconosce e accetta il
rischio aggregato.

---

## §14 — Firma

| Item | Valore |
|---|---|
| Prereg version | 1.0 |
| Date firma | TBD (al momento del .docx) |
| Owner | Prometeus |
| Sector | semis |
| YAML hash SHA256 (audit anchor) | `be3b7cd6eb49f255...` (verificare al momento del lockfile, può essere diverso se YAML viene modificato prima della firma) |
| Git commit hash al momento della firma | TBD |

---

*Fine del documento. Tradurre in `.docx` con stile coerente alla
`prereg_step1_ai_infra.docx` v1.0 originale e committare come
`docs/prereg_step1_semis.docx`.*
