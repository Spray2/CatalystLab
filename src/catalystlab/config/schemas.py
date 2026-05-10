"""Pydantic v2 schemas for sector YAML configs.

The lockfile semantics of `docs/prereg_step1_ai_infra.docx` flow through these
schemas: models are frozen, `extra="forbid"`, and validators enforce
non-negotiable invariants of the pre-registration (prereg §4 T+0 exclusion,
§3 five categories A-E, §6.3 binding thresholds).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_REQUIRED_CATEGORIES: frozenset[str] = frozenset({"A", "B", "C", "D", "E"})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TickerEntry(_Frozen):
    ticker: str = Field(min_length=1, max_length=8)
    name: str
    market: Literal["NYSE", "NASDAQ"]
    type: str


class Period(_Frozen):
    start: date
    end: date

    @model_validator(mode="after")
    def end_after_start(self) -> Period:
        if self.end < self.start:
            raise ValueError(f"period.end ({self.end}) must be >= start ({self.start})")
        return self


class Benchmarks(_Frozen):
    primary: str = Field(min_length=1)
    secondary: str = Field(min_length=1)
    beta_window_days: int = Field(gt=0)
    beta_exclusion_window_days: int = Field(ge=0)

    @model_validator(mode="after")
    def exclusion_lt_window(self) -> Benchmarks:
        if self.beta_exclusion_window_days >= self.beta_window_days:
            raise ValueError(
                f"beta_exclusion_window_days ({self.beta_exclusion_window_days}) must be < "
                f"beta_window_days ({self.beta_window_days})"
            )
        return self


class ThresholdCondition(_Frozen):
    field: str
    op: Literal["gt", "lt", "ge", "le", "eq"]
    value: float


class Threshold(_Frozen):
    type: Literal["abs_gt", "gt", "lt", "any_of"]
    value: float | None = None
    conditions: list[ThresholdCondition] | None = None

    @model_validator(mode="after")
    def shape_matches_type(self) -> Threshold:
        if self.type == "any_of":
            if not self.conditions:
                raise ValueError("threshold type=any_of requires non-empty conditions")
            if self.value is not None:
                raise ValueError("threshold type=any_of must not set scalar value")
        else:
            if self.value is None:
                raise ValueError(f"threshold type={self.type} requires scalar value")
            if self.conditions is not None:
                raise ValueError(f"threshold type={self.type} must not set conditions")
        return self


class EventCategory(_Frozen):
    name: str
    description: str
    hypothesis: str
    magnitude_metric: str
    source: str
    threshold: Threshold | None = None
    hyperscalers: list[str] | None = None
    tier1_banks: list[str] | None = None


class CostModel(_Frozen):
    """Prereg §5 cost model (Interpretation B: round-trip totals).

    Computed round-trip cost in bps on `default_position_size_eur` must land
    in §5.2 declared range 75-100 bps; verified by `tests/test_costs.py`.
    """

    commission_per_execution_eur: float = Field(gt=0)
    spread_round_trip_bps: float = Field(ge=0)
    fx_round_trip_bps: float = Field(ge=0)
    default_position_size_eur: float = Field(gt=0)


class StatsConfig(_Frozen):
    """Prereg §6.3 binding thresholds. No quasi-success (prereg §11)."""

    ic_threshold: float
    hit_rate_threshold: float = Field(gt=0, lt=1)
    bh_alpha: float = Field(gt=0, lt=1)
    bootstrap_n: int = Field(ge=100)
    bootstrap_ci: float = Field(gt=0, lt=1)


class SectorConfig(_Frozen):
    """Top-level sector spec mirroring prereg §2-§7 + open questions §12."""

    sector: str = Field(min_length=1)
    display_name: str
    prereg_version: str
    prereg_lockfile_date: date
    random_seed: int
    period: Period
    universe: list[TickerEntry] = Field(min_length=1)
    benchmarks: Benchmarks
    holding_windows: list[int]
    categories: dict[str, EventCategory]
    costs: CostModel
    stats: StatsConfig
    open_questions: dict[str, str] = Field(default_factory=dict)

    @field_validator("holding_windows")
    @classmethod
    def no_t0_and_unique(cls, v: list[int]) -> list[int]:
        # Prereg §4 + §11: T+0 explicitly excluded for data leakage operativo.
        if 0 in v:
            raise ValueError("T+0 is excluded by pre-registration §4 (data leakage operativo)")
        if any(d < 1 for d in v):
            raise ValueError("holding_windows must be >= 1 (T+1 minimum)")
        if len(v) != len(set(v)):
            raise ValueError("holding_windows must be unique")
        return sorted(v)

    @field_validator("universe")
    @classmethod
    def unique_tickers(cls, v: list[TickerEntry]) -> list[TickerEntry]:
        tickers = [t.ticker for t in v]
        if len(tickers) != len(set(tickers)):
            raise ValueError("universe tickers must be unique")
        return v

    @field_validator("categories")
    @classmethod
    def required_five_categories(
        cls, v: dict[str, EventCategory]
    ) -> dict[str, EventCategory]:
        keys = frozenset(v.keys())
        if keys != _REQUIRED_CATEGORIES:
            missing = _REQUIRED_CATEGORIES - keys
            extra = keys - _REQUIRED_CATEGORIES
            raise ValueError(
                f"categories must be exactly {sorted(_REQUIRED_CATEGORIES)}; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        return v
