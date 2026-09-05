import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from geekmagic_ai_monitor.geekmagic import FirmwareIdentity, FirmwareProfile
from geekmagic_ai_monitor.rendering import DashboardRenderer
from geekmagic_ai_monitor.runtime import UpdateService
from geekmagic_ai_monitor.usage import UsageInfo


class StaticProvider:
    def __init__(self, usage: UsageInfo | None = None, error: Exception | None = None) -> None:
        self.usage = usage or UsageInfo()
        self.error = error
        self.calls = 0

    async def get_usage(self) -> UsageInfo:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.usage


class FakeDevice:
    def __init__(self, *, failures_remaining: int = 0) -> None:
        self.identity = FirmwareIdentity(
            FirmwareProfile.STOCK_ULTRA,
            model="SmallTV-Ultra",
            version="Ultra-V9.0.51",
            detected_by="/v.json",
        )
        self.failures_remaining = failures_remaining
        self.probe_calls = 0
        self.upload_attempts = 0
        self.uploads: list[tuple[bytes, str, FirmwareIdentity | None]] = []

    async def probe(self) -> FirmwareIdentity:
        self.probe_calls += 1
        return self.identity

    async def upload_and_display(
        self,
        jpeg_data: bytes,
        filename: str,
        *,
        identity: FirmwareIdentity | None = None,
    ) -> FirmwareIdentity:
        self.upload_attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise OSError("temporary device failure")
        self.uploads.append((jpeg_data, filename, identity))
        return self.identity


def _fixed_clock() -> datetime:
    return datetime(2026, 9, 2, 22, 30, tzinfo=UTC)


async def test_update_once_builds_snapshot_renders_and_pushes(tmp_path: Path) -> None:
    codex = StaticProvider(UsageInfo(five_hour_used_percent=26, weekly_used_percent=31))
    claude = StaticProvider(UsageInfo(five_hour_used_percent=12, weekly_used_percent=8))
    device = FakeDevice()
    output = tmp_path / "current.jpg"

    result = await UpdateService(
        codex_provider=codex,
        claude_provider=claude,
        renderer=DashboardRenderer(),
        device=device,
        image_file_name="monitor.jpg",
        output_path=output,
        update_interval_seconds=60,
        source_device="WIN",
        logger=lambda _: None,
        clock=_fixed_clock,
    ).update_once()

    assert result.snapshot.codex.five_hour_used_percent == 26
    assert result.snapshot.claude.weekly_used_percent == 8
    assert result.snapshot.updated_at == _fixed_clock()
    assert result.snapshot.source_device == "WIN"
    assert result.output_path == output.resolve()
    assert result.identity is device.identity
    assert device.probe_calls == 1
    assert len(device.uploads) == 1
    uploaded_data, filename, identity = device.uploads[0]
    assert uploaded_data == output.read_bytes()
    assert filename == "monitor.jpg"
    assert identity is device.identity

    with Image.open(BytesIO(uploaded_data)) as image:
        assert image.size == (240, 240)


async def test_provider_failure_becomes_unavailable_without_blocking_push(
    tmp_path: Path,
) -> None:
    logs: list[str] = []
    device = FakeDevice()
    result = await UpdateService(
        codex_provider=StaticProvider(UsageInfo(five_hour_used_percent=20, weekly_used_percent=30)),
        claude_provider=StaticProvider(error=RuntimeError("Claude unavailable")),
        renderer=DashboardRenderer(),
        device=device,
        image_file_name="monitor.jpg",
        output_path=tmp_path / "current.jpg",
        update_interval_seconds=60,
        source_device="MAC",
        logger=logs.append,
        clock=_fixed_clock,
    ).update_once()

    assert result.snapshot.codex.is_available
    assert not result.snapshot.claude.is_available
    assert len(device.uploads) == 1
    assert any("Claude usage unavailable" in message for message in logs)


async def test_loop_retries_after_device_failure(tmp_path: Path) -> None:
    codex = StaticProvider(UsageInfo(five_hour_used_percent=20))
    claude = StaticProvider(UsageInfo(weekly_used_percent=30))
    device = FakeDevice(failures_remaining=1)
    logs: list[str] = []
    sleeps: list[float] = []
    times: Iterator[float] = iter((0.0, 1.0, 10.0))

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    service = UpdateService(
        codex_provider=codex,
        claude_provider=claude,
        renderer=DashboardRenderer(),
        device=device,
        image_file_name="monitor.jpg",
        output_path=tmp_path / "current.jpg",
        update_interval_seconds=10,
        source_device="WIN",
        logger=logs.append,
        clock=_fixed_clock,
        sleeper=fake_sleep,
        monotonic_clock=lambda: next(times),
    )

    await service.run(max_cycles=2)

    assert codex.calls == 2
    assert claude.calls == 2
    assert device.upload_attempts == 2
    assert len(device.uploads) == 1
    assert sleeps == [9.0]
    assert any("Update cycle failed (OSError)" in message for message in logs)
    assert any("Update completed" in message for message in logs)


async def test_immediate_update_request_wakes_scheduler(tmp_path: Path) -> None:
    codex = StaticProvider(UsageInfo(five_hour_used_percent=20))
    claude = StaticProvider(UsageInfo(weekly_used_percent=30))
    waiting = asyncio.Event()
    logs: list[str] = []

    def capture_log(message: str) -> None:
        logs.append(message)
        if message.startswith("Next update in"):
            waiting.set()

    service = UpdateService(
        codex_provider=codex,
        claude_provider=claude,
        renderer=DashboardRenderer(),
        device=FakeDevice(),
        image_file_name="monitor.jpg",
        output_path=tmp_path / "current.jpg",
        update_interval_seconds=3600,
        source_device="WIN",
        logger=capture_log,
        clock=_fixed_clock,
    )
    task = asyncio.create_task(service.run(max_cycles=2))
    await asyncio.wait_for(waiting.wait(), timeout=1)

    service.request_update()
    await asyncio.wait_for(task, timeout=1)

    assert codex.calls == 2
    assert claude.calls == 2
    assert "Immediate update requested" in logs


def test_update_interval_can_be_changed() -> None:
    service = UpdateService(
        codex_provider=StaticProvider(),
        claude_provider=StaticProvider(),
        renderer=DashboardRenderer(),
        device=FakeDevice(),
        image_file_name="monitor.jpg",
        output_path=Path("current.jpg"),
        update_interval_seconds=60,
        source_device="WIN",
    )

    service.set_update_interval_seconds(300)

    assert service.update_interval_seconds == 300
    with pytest.raises(ValueError, match="greater than zero"):
        service.set_update_interval_seconds(0)
