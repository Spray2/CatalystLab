"""Layer 1 — sector YAML loader + run manifest builder.

The loader returns the validated `SectorConfig` together with the SHA256 of
the YAML file bytes. The hash is the lockfile-style audit anchor required by
the manifest (CLAUDE.md "Reproducibility"): a run is reproducible iff the
{sector_yaml_sha256, git_commit, input_data_hashes} tuple is fixed.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from catalystlab.config.schemas import SectorConfig

DEFAULT_SECTORS_DIR = Path("sectors")
MANIFEST_SCHEMA_VERSION = 1


def load_sector(
    name: str,
    sectors_dir: Path | None = None,
) -> tuple[SectorConfig, str]:
    """Load and validate a sector YAML, returning (config, sha256_hex).

    Args:
        name: sector name without extension (e.g. ``"ai_infra"`` resolves
            to ``<sectors_dir>/ai_infra.yaml``).
        sectors_dir: directory containing sector YAML files; defaults to
            ``./sectors`` relative to the current working directory.

    Returns:
        Tuple of the validated ``SectorConfig`` and the lower-case hex
        SHA256 digest of the raw YAML file bytes.

    Raises:
        FileNotFoundError: if the sector YAML does not exist.
        yaml.YAMLError: if the YAML is malformed.
        pydantic.ValidationError: if the YAML fails schema validation.
    """
    base = sectors_dir if sectors_dir is not None else DEFAULT_SECTORS_DIR
    path = base / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"sector config not found: {path}")

    raw_bytes = path.read_bytes()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    data = yaml.safe_load(raw_bytes.decode("utf-8"))
    config = SectorConfig.model_validate(data)
    return config, sha


def _git_commit_hash(repo_dir: Path | None = None) -> str | None:
    """Return current ``git rev-parse HEAD`` SHA, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir if repo_dir is not None else Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    sha = out.stdout.strip()
    return sha or None


def compute_manifest(
    sector_name: str,
    sector_yaml_sha256: str,
    runtime_params: dict[str, Any] | None = None,
    repo_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a run manifest dict for `data/manifests/<timestamp>.json`.

    The manifest is the audit trail per CLAUDE.md "Reproducibility":
    timestamp UTC, git commit hash, sector YAML hash, and arbitrary runtime
    parameters (e.g. input data hashes from Layer 2).
    """
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "sector": sector_name,
        "sector_yaml_sha256": sector_yaml_sha256,
        "git_commit": _git_commit_hash(repo_dir),
        "runtime_params": dict(runtime_params or {}),
    }
