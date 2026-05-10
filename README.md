# CatalystLab

Event-driven research framework per retail trading post-cost.
Settore Step 1: AI Infrastructure US.

> **Status**: Settimana 1 ✅ — Layer 1+2 complete, panel parquet end-to-end.
> **Authority**: `docs/prereg_step1_ai_infra.docx` (lockfile pre-registration).

## Quickstart

```bash
# 1. Setup (Python 3.11+, uv)
uv sync --extra dev

# 2. Run the test suite
uv run pytest

# 3. End-to-end: build the panel parquet for AI Infrastructure
uv run python -m catalystlab.cli build-panel --sector ai_infra
# → produces:
#     data/processed/panel_ai_infra.parquet
#     data/manifests/<timestamp>_ai_infra.json
```

The integration tests against live yfinance are gated by an env var:

```bash
CATALYSTLAB_RUN_INTEGRATION=1 uv run pytest
```

## Architettura

5 layer puri, sector-agnostic. I settori sono dichiarati in
`sectors/<name>.yaml` (autorità: `docs/prereg_step1_<name>.docx`).

```
Layer 1 (config)      sectors/<name>.yaml + pydantic SectorConfig
Layer 2 (ingestion)   prices · earnings · costs · panel parquet
Layer 3 (eventstudy)  AR, CAR, IC per categoria  [W2]
Layer 4 (stats)       BH-FDR, bootstrap CI, temporal CV  [W3]
Layer 5 (reporting)   HTML report + decision.json  [W3]
```

Dettagli in `CLAUDE.md`.

## Status W1 (chiusura)

- 8 ticker AI Infrastructure (VRT/ETN/GEV/PWR/CEG/VST/ANET/MOD) + benchmark XLK/SPY
- Periodo locked 2023-01-01 → 2026-04-30 (prereg §7)
- 5 categorie evento A-E (prereg §3) con event log scaffold in `data/events/ai_infra/`
- Cost model Fineco implementato (prereg §5)
- 77 test (2 integration, gated), coverage ~91% Layer 1+2
- ADR 0001 (hybrid reuse from EquiTeria)

## Disclaimer

Research personale, non consulenza finanziaria. Vedi prereg §13.
