from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from geekmagic_ai_monitor.configuration import ClaudeSettings
from geekmagic_ai_monitor.usage import ClaudeUsageError, ClaudeUsageProvider


def _command_payload(result: str, *, input_tokens: int = 0) -> dict[str, object]:
    return {
        "is_error": False,
        "total_cost_usd": 0,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "result": result,
    }


async def test_claude_provider_maps_usage_and_reset_times() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "You are currently using your subscription\n\n"
            "Current session: 12% used · resets Sep 3, 12:30am (Asia/Seoul)\n"
            "Current week (all models): 8% used · resets Sep 5, 12am (Asia/Seoul)"
        )

    provider = ClaudeUsageProvider(
        ClaudeSettings(),
        usage_command_reader=read_usage,
        clock=lambda: datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    )

    usage = await provider.get_usage()

    assert usage.five_hour_used_percent == 12
    assert usage.weekly_used_percent == 8
    assert usage.five_hour_reset_at == datetime(2026, 9, 2, 15, 30, tzinfo=UTC)
    assert usage.weekly_reset_at == datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


async def test_claude_provider_allows_missing_reset_times() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload("Current session: 1.5% used\nCurrent week: 2% used")

    usage = await ClaudeUsageProvider(ClaudeSettings(), usage_command_reader=read_usage).get_usage()

    assert usage.five_hour_used_percent == 1.5
    assert usage.weekly_used_percent == 2
    assert usage.five_hour_reset_at is None
    assert usage.weekly_reset_at is None


async def test_claude_provider_maps_macos_reset_text_and_all_models_week() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "You are currently using your subscription to power your Claude Code usage\n\n"
            "Current session: 2% used · resets Sep 6 at 9:59pm (Asia/Seoul)\n"
            "Current week (all models): 6% used · resets Sep 11 at 11:59pm (Asia/Seoul)\n"
            "Current week (Fable): 8% used · resets Sep 11 at 11:59pm (Asia/Seoul)"
        )

    usage = await ClaudeUsageProvider(
        ClaudeSettings(),
        usage_command_reader=read_usage,
        clock=lambda: datetime(2026, 9, 6, 8, 0, tzinfo=UTC),
    ).get_usage()

    assert usage.five_hour_used_percent == 2
    assert usage.weekly_used_percent == 6
    assert usage.five_hour_reset_at == datetime(2026, 9, 6, 12, 59, tzinfo=UTC)
    assert usage.weekly_reset_at == datetime(2026, 9, 11, 14, 59, tzinfo=UTC)


async def test_claude_provider_allows_missing_five_hour_limit() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "You are currently using your subscription\n\n"
            "Current week: 27% used · resets Sep 5, 12am (Asia/Seoul)"
        )

    usage = await ClaudeUsageProvider(
        ClaudeSettings(),
        usage_command_reader=read_usage,
        clock=lambda: datetime(2026, 9, 4, 0, 0, tzinfo=UTC),
    ).get_usage()

    assert usage.five_hour_used_percent is None
    assert usage.five_hour_reset_at is None
    assert usage.weekly_used_percent == 27


async def test_claude_provider_accepts_qualitative_only_usage_result() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "You are currently using your subscription to power your Claude Code usage\n\n"
            "What's contributing to your limits usage?\n"
            "Last 24h · 587 requests · 6 sessions"
        )

    usage = await ClaudeUsageProvider(ClaudeSettings(), usage_command_reader=read_usage).get_usage()

    assert usage.five_hour_used_percent is None
    assert usage.weekly_used_percent is None
    assert not usage.is_available


async def test_claude_provider_rolls_reset_into_next_year() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "Current session: 3% used · resets Jan 1, 1am (Asia/Seoul)\n"
            "Current week: 4% used · resets Jan 2, 12pm (Asia/Seoul)"
        )

    provider = ClaudeUsageProvider(
        ClaudeSettings(),
        usage_command_reader=read_usage,
        clock=lambda: datetime(2026, 12, 31, 12, 0, tzinfo=UTC),
    )

    usage = await provider.get_usage()

    assert usage.five_hour_reset_at == datetime(2026, 12, 31, 16, 0, tzinfo=UTC)
    assert usage.weekly_reset_at == datetime(2027, 1, 2, 3, 0, tzinfo=UTC)


async def test_claude_provider_rejects_model_token_usage() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload(
            "Current session: 3% used\nCurrent week: 4% used",
            input_tokens=1,
        )

    provider = ClaudeUsageProvider(ClaudeSettings(), usage_command_reader=read_usage)

    with pytest.raises(ClaudeUsageError, match="unexpectedly invoked the model"):
        await provider.get_usage()


async def test_claude_provider_rejects_malformed_usage_text() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload("No subscription limits here")

    provider = ClaudeUsageProvider(ClaudeSettings(), usage_command_reader=read_usage)

    with pytest.raises(ClaudeUsageError, match="recognizable subscription usage data"):
        await provider.get_usage()


async def test_claude_provider_rejects_out_of_range_percentage() -> None:
    async def read_usage() -> Mapping[str, object]:
        return _command_payload("Current session: 101% used\nCurrent week: 4% used")

    provider = ClaudeUsageProvider(ClaudeSettings(), usage_command_reader=read_usage)

    with pytest.raises(ClaudeUsageError, match="invalid usage values"):
        await provider.get_usage()
