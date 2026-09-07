from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

from geekmagic_ai_monitor.rendering import DashboardRenderer
from geekmagic_ai_monitor.rendering.dashboard_renderer import (
    _format_percent_label,
    _format_reset_schedule,
)
from geekmagic_ai_monitor.usage import AiUsageSnapshot, UsageInfo


def test_dashboard_renderer_creates_240_by_240_rgb_jpeg() -> None:
    snapshot = AiUsageSnapshot(
        codex=UsageInfo(five_hour_used_percent=72, weekly_used_percent=43),
        claude=UsageInfo(five_hour_used_percent=61, weekly_used_percent=37),
        updated_at=datetime(2026, 9, 2, 21, 5, tzinfo=UTC),
        source_device="WIN",
    )

    data = DashboardRenderer().render(snapshot)

    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (240, 240)


def test_dashboard_renderer_accepts_unavailable_provider() -> None:
    snapshot = AiUsageSnapshot(
        codex=UsageInfo(five_hour_used_percent=72, weekly_used_percent=43),
        claude=UsageInfo(),
        updated_at=datetime(2026, 9, 2, 21, 5, tzinfo=UTC),
        source_device="MAC",
    )

    assert DashboardRenderer().render(snapshot).startswith(b"\xff\xd8")


def test_missing_usage_is_labeled_none_instead_of_zero_percent() -> None:
    assert _format_percent_label(None) == "None"
    assert _format_percent_label(0) == "0%"


def test_dashboard_renderer_draws_none_for_missing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn_text: list[str] = []

    def capture_right_aligned_text(
        _draw: object,
        text: str,
        _right: int,
        _y: int,
        _font: object,
        _fill: str,
    ) -> None:
        drawn_text.append(text)

    monkeypatch.setattr(
        "geekmagic_ai_monitor.rendering.dashboard_renderer._draw_right",
        capture_right_aligned_text,
    )
    snapshot = AiUsageSnapshot(
        codex=UsageInfo(),
        claude=UsageInfo(),
        updated_at=datetime(2026, 9, 4, 9, 20, tzinfo=UTC),
        source_device="WIN",
    )

    DashboardRenderer().render(snapshot)

    assert drawn_text.count("None") == 4


@pytest.mark.parametrize("value", [-0.1, 100.1, float("inf"), float("nan")])
def test_usage_info_rejects_invalid_used_percent(value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        UsageInfo(five_hour_used_percent=value)


def test_snapshot_requires_timezone_aware_updated_at() -> None:
    with pytest.raises(ValueError, match="timezone"):
        AiUsageSnapshot(
            codex=UsageInfo(),
            claude=UsageInfo(),
            updated_at=datetime(2026, 9, 2, 21, 5),
            source_device="WIN",
        )


def test_reset_schedule_is_formatted_in_dashboard_timezone() -> None:
    korea = timezone(timedelta(hours=9))
    five_hour_reset_at = datetime(2026, 9, 2, 15, 30, tzinfo=UTC)
    weekly_reset_at = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)

    assert _format_reset_schedule(five_hour_reset_at, weekly_reset_at, korea) == "00:30 · W 09/08"
    assert _format_reset_schedule(None, None, korea) == "--:-- · W --/--"
