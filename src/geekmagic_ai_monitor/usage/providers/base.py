"""Contract implemented by AI usage providers."""

from __future__ import annotations

from typing import Protocol

from geekmagic_ai_monitor.usage.models import UsageInfo


class UsageProvider(Protocol):
    """Read provider usage without coupling callers to its transport."""

    async def get_usage(self) -> UsageInfo:
        """Return the provider's current usage snapshot."""
        ...
