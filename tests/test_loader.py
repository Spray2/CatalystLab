"""Tests for catalystlab.config.loader."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from catalystlab.config.loader import (
    MANIFEST_SCHEMA_VERSION,
    _git_commit_hash,
    compute_manifest,
    load_sector,
)

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
REAL_SECTORS_DIR: Path = REPO_ROOT / "sectors"


def test_load_real_ai_infra() -> None:
    cfg, sha = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)

    assert cfg.sector == "ai_infra"
    assert len(cfg.universe) == 8
    assert cfg.benchmarks.primary == "XLK"
    assert cfg.benchmarks.secondary == "SPY"

    # Prereg §4 invariant: T+0 cannot be in holding_windows.
    assert 0 not in cfg.holding_windows
    assert cfg.holding_windows == [1, 5, 20, 60]

    # Prereg §3 invariant: exactly five categories A-E.
    assert sorted(cfg.categories.keys()) == ["A", "B", "C", "D", "E"]

    # Hash is a 64-char lowercase hex string.
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_hash_determinism() -> None:
    _, sha1 = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    _, sha2 = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    assert sha1 == sha2


def test_hash_matches_file_bytes() -> None:
    expected = hashlib.sha256(
        (REAL_SECTORS_DIR / "ai_infra.yaml").read_bytes()
    ).hexdigest()
    _, sha = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    assert sha == expected


def test_missing_sector_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="sector config not found"):
        load_sector("nonexistent_sector", sectors_dir=tmp_path)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    # Unclosed flow sequence — pyyaml emits YAMLError on this.
    bad.write_text("foo: [unclosed\nbar: value\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_sector("bad", sectors_dir=tmp_path)


def test_invalid_schema_t0_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load((REAL_SECTORS_DIR / "ai_infra.yaml").read_text())
    base["holding_windows"] = [0, 1, 5]  # T+0 violates prereg §4
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(ValidationError, match="T\\+0"):
        load_sector("bad", sectors_dir=tmp_path)


def test_compute_manifest_shape() -> None:
    _, sha = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    m = compute_manifest(
        "ai_infra",
        sha,
        runtime_params={"input_prices_sha": "abcd1234"},
        repo_dir=REPO_ROOT,
    )

    assert m["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert m["sector"] == "ai_infra"
    assert m["sector_yaml_sha256"] == sha
    assert m["runtime_params"] == {"input_prices_sha": "abcd1234"}
    assert "timestamp_utc" in m
    # We're inside a git repo here; commit hash should be a 40-char SHA1.
    assert m["git_commit"] is not None
    assert len(m["git_commit"]) == 40


def test_git_commit_hash_outside_repo(tmp_path: Path) -> None:
    # tmp_path is not a git repo → returns None.
    assert _git_commit_hash(repo_dir=tmp_path) is None


def test_git_commit_hash_inside_repo() -> None:
    sha = _git_commit_hash(repo_dir=REPO_ROOT)
    assert sha is not None
    assert len(sha) == 40
    # Cross-check against `git rev-parse HEAD`.
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert sha == expected


def test_runtime_params_none_yields_empty_dict() -> None:
    _, sha = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    m = compute_manifest("ai_infra", sha, runtime_params=None)
    assert m["runtime_params"] == {}


def test_runtime_params_is_copied_not_aliased() -> None:
    _, sha = load_sector("ai_infra", sectors_dir=REAL_SECTORS_DIR)
    params = {"x": 1}
    m = compute_manifest("ai_infra", sha, runtime_params=params)
    params["x"] = 999
    assert m["runtime_params"]["x"] == 1
