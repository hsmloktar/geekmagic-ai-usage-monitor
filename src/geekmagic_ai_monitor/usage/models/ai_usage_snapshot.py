"""Complete provider snapshot consumed by the dashboard renderer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .usage_info import UsageInfo


@dataclass(frozen=True, slots=True)
class AiUsageSnapshot:
    """Usage state for all providers at one update time."""

    codex: UsageInfo
    claude: UsageInfo
    updated_at: datetime
    source_device: str

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must include timezone information.")
        if not self.source_device.strip():
            raise ValueError("source_device must not be empty.")
