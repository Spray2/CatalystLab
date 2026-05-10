# CatalystLab

Event-driven research framework per retail trading post-cost.
Settore Step 1: AI Infrastructure US.

> **Status**: Settimana 1 — scaffolding + Layer 1/2 in costruzione.
> **Authority**: `docs/prereg_step1_ai_infra.docx` (lockfile pre-registration).

## Quickstart

```bash
uv sync --extra dev
uv run pytest
uv run python -m catalystlab.cli build-panel --sector ai_infra   # disponibile fine W1
```

## Architettura

5 layer puri (config → ingestion → event study → stats → reporting), settori
dichiarati in `sectors/<name>.yaml`. Dettagli completi in `CLAUDE.md`.

## Disclaimer

Research personale, non consulenza finanziaria. Vedi prereg §13.
