from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from geekmagic_ai_monitor.configuration import CodexSettings
from geekmagic_ai_monitor.usage import CodexUsageError, CodexUsageProvider


async def test_codex_provider_selects_codex_bucket_and_matches_window_durations() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {
            "rateLimits": {
                "primary": {"usedPercent": 99, "windowDurationMins": 300},
            },
            "rateLimitsByLimitId": {
                "codex_other": {
                    "primary": {"usedPercent": 88, "windowDurationMins": 300},
                },
                "codex": {
                    "primary": {
                        "usedPercent": 27,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788858478,
                    },
                    "secondary": {
                        "usedPercent": 2,
                        "windowDurationMins": 300,
                        "resetsAt": 1788371371,
                    },
                },
            },
        }

    usage = await CodexUsageProvider(
        CodexSettings(), rate_limits_reader=read_rate_limits
    ).get_usage()

    assert usage.five_hour_used_percent == 2
    assert usage.weekly_used_percent == 27
    assert usage.five_hour_reset_at == datetime.fromtimestamp(1788371371, tz=UTC)
    assert usage.weekly_reset_at == datetime.fromtimestamp(1788858478, tz=UTC)
    assert usage.five_hour_reset_at is not None
    assert usage.five_hour_reset_at.utcoffset() is not None


async def test_codex_provider_falls_back_to_legacy_primary_and_secondary() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {
            "rateLimits": {
                "primary": {"usedPercent": 12},
                "secondary": {"usedPercent": 34},
            }
        }

    usage = await CodexUsageProvider(
        CodexSettings(), rate_limits_reader=read_rate_limits
    ).get_usage()

    assert usage.five_hour_used_percent == 12
    assert usage.weekly_used_percent == 34


async def test_codex_provider_allows_missing_five_hour_window() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 73,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788858478,
                    },
                    "secondary": None,
                }
            }
        }

    usage = await CodexUsageProvider(
        CodexSettings(), rate_limits_reader=read_rate_limits
    ).get_usage()

    assert usage.five_hour_used_percent is None
    assert usage.five_hour_reset_at is None
    assert usage.weekly_used_percent == 73


async def test_codex_provider_rejects_missing_rate_limit_bucket() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {"rateLimitsByLimitId": {"codex_other": {}}}

    provider = CodexUsageProvider(CodexSettings(), rate_limits_reader=read_rate_limits)

    with pytest.raises(CodexUsageError, match="Codex rate-limit bucket"):
        await provider.get_usage()


async def test_codex_provider_rejects_empty_windows() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {"rateLimits": {"primary": None, "secondary": None}}

    provider = CodexUsageProvider(CodexSettings(), rate_limits_reader=read_rate_limits)

    with pytest.raises(CodexUsageError, match="no usable"):
        await provider.get_usage()


async def test_codex_provider_rejects_out_of_range_percentage() -> None:
    async def read_rate_limits() -> Mapping[str, object]:
        return {
            "rateLimits": {
                "primary": {"usedPercent": 101, "windowDurationMins": 300},
            }
        }

    provider = CodexUsageProvider(CodexSettings(), rate_limits_reader=read_rate_limits)

    with pytest.raises(CodexUsageError, match="invalid rate-limit values"):
        await provider.get_usage()
