"""Provider-independent usage values."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UsageInfo:
    """Used quota percentages and optional reset times for one AI provider."""

    five_hour_used_percent: float | None = None
    weekly_used_percent: float | None = None
    five_hour_reset_at: datetime | None = None
    weekly_reset_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_percent("five_hour_used_percent", self.five_hour_used_percent)
        _validate_percent("weekly_used_percent", self.weekly_used_percent)
        _validate_optional_aware_datetime("five_hour_reset_at", self.five_hour_reset_at)
        _validate_optional_aware_datetime("weekly_reset_at", self.weekly_reset_at)

    @property
    def is_available(self) -> bool:
        """Return whether the provider supplied at least one usage value."""
        return self.five_hour_used_percent is not None or self.weekly_used_percent is not None


def _validate_percent(name: str, value: float | None) -> None:
    if value is None:
        return
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100.")


def _validate_optional_aware_datetime(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must include timezone information.")
