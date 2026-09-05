"""Resilient periodic usage-to-device update pipeline."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from geekmagic_ai_monitor.geekmagic import FirmwareIdentity
from geekmagic_ai_monitor.rendering import DashboardRenderer
from geekmagic_ai_monitor.usage import AiUsageSnapshot, UsageInfo, UsageProvider

Logger = Callable[[str], None]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]
MonotonicClock = Callable[[], float]


class GeekMagicPusher(Protocol):
    """Small device contract needed by the update loop."""

    async def probe(self) -> FirmwareIdentity:
        """Return the current firmware identity."""
        ...

    async def upload_and_display(
        self,
        jpeg_data: bytes,
        filename: str,
        *,
        identity: FirmwareIdentity | None = None,
    ) -> FirmwareIdentity:
        """Upload and select one rendered dashboard."""
        ...


@dataclass(frozen=True, slots=True)
class UpdateCycleResult:
    """Successful output from one complete update cycle."""

    snapshot: AiUsageSnapshot
    output_path: Path
    identity: FirmwareIdentity


class UpdateService:
    """Collect, render, and push usage immediately and then at a fixed cadence."""

    def __init__(
        self,
        *,
        codex_provider: UsageProvider,
        claude_provider: UsageProvider,
        renderer: DashboardRenderer,
        device: GeekMagicPusher,
        image_file_name: str,
        output_path: Path,
        update_interval_seconds: float,
        source_device: str,
        logger: Logger = print,
        clock: Clock | None = None,
        sleeper: Sleeper = asyncio.sleep,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        if update_interval_seconds <= 0:
            raise ValueError("update_interval_seconds must be greater than zero.")
        if not source_device.strip():
            raise ValueError("source_device must not be empty.")

        self._codex_provider = codex_provider
        self._claude_provider = claude_provider
        self._renderer = renderer
        self._device = device
        self._image_file_name = image_file_name
        self._output_path = output_path
        self._update_interval_seconds = update_interval_seconds
        self._source_device = source_device
        self._logger = logger
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._sleeper = sleeper
        self._monotonic_clock = monotonic_clock
        self._schedule_event = asyncio.Event()
        self._immediate_update_requested = False

    @property
    def update_interval_seconds(self) -> float:
        """Return the currently selected interval."""
        return self._update_interval_seconds

    def set_update_interval_seconds(self, value: float) -> None:
        """Change the interval and wake the scheduler to recalculate its delay."""
        if value <= 0:
            raise ValueError("update interval must be greater than zero.")
        self._update_interval_seconds = value
        self._schedule_event.set()

    def request_update(self) -> None:
        """Request one update as soon as any in-progress cycle finishes."""
        self._immediate_update_requested = True
        self._schedule_event.set()

    async def update_once(self) -> UpdateCycleResult:
        """Run one complete cycle, isolating provider failures from each other."""
        self._aware_now()
        self._logger("Update started")

        codex, claude = await asyncio.gather(
            self._read_provider("Codex", self._codex_provider),
            self._read_provider("Claude", self._claude_provider),
        )
        snapshot = AiUsageSnapshot(
            codex=codex,
            claude=claude,
            updated_at=self._aware_now(),
            source_device=self._source_device,
        )
        image_data = self._renderer.render(snapshot)
        output_path = self._write_image(image_data)

        identity = await self._device.probe()
        self._logger(
            "Device detected: "
            f"profile={identity.profile}, model={identity.model or 'unknown'}, "
            f"version={identity.version or 'unknown'}"
        )
        await self._device.upload_and_display(
            image_data,
            self._image_file_name,
            identity=identity,
        )
        self._logger(f"Update completed: /image/{self._image_file_name} from {self._source_device}")
        return UpdateCycleResult(snapshot, output_path, identity)

    async def run(self, *, max_cycles: int | None = None) -> None:
        """Run immediately, then retry every configured interval until cancelled."""
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be greater than zero when provided.")

        completed_cycles = 0
        while True:
            cycle_started = self._monotonic_clock()
            try:
                await self.update_once()
            except Exception as error:
                # The long-running boundary must survive device, rendering, and file errors.
                self._logger(
                    f"Update cycle failed ({type(error).__name__}): {_compact_error(error)}"
                )

            completed_cycles += 1
            if max_cycles is not None and completed_cycles >= max_cycles:
                return

            await self._wait_until_next_cycle(cycle_started)

    async def _wait_until_next_cycle(self, cycle_started: float) -> None:
        while True:
            elapsed = self._monotonic_clock() - cycle_started
            delay = max(0.0, self._update_interval_seconds - elapsed)
            self._logger(f"Next update in {delay:.1f}s")
            if delay <= 0:
                return

            schedule_changed = await self._wait_for_schedule_change(delay)
            if not schedule_changed:
                return

            self._schedule_event.clear()
            if self._immediate_update_requested:
                self._immediate_update_requested = False
                self._logger("Immediate update requested")
                return

    async def _wait_for_schedule_change(self, delay: float) -> bool:
        sleep_task = asyncio.create_task(self._sleep(delay))
        schedule_task = asyncio.create_task(self._schedule_event.wait())
        tasks = (sleep_task, schedule_task)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if schedule_task in done:
                await schedule_task
                return True
            await sleep_task
            return False
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _sleep(self, delay: float) -> None:
        await self._sleeper(delay)

    async def _read_provider(self, name: str, provider: UsageProvider) -> UsageInfo:
        try:
            usage = await provider.get_usage()
        except Exception as error:
            # Providers are explicit isolation boundaries; one failure becomes Unavailable.
            self._logger(
                f"{name} usage unavailable ({type(error).__name__}): {_compact_error(error)}"
            )
            return UsageInfo()

        self._logger(
            f"{name} usage: 5H={_format_percent(usage.five_hour_used_percent)}, "
            f"WK={_format_percent(usage.weekly_used_percent)}"
        )
        return usage

    def _write_image(self, image_data: bytes) -> Path:
        output = self._output_path.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image_data)
        return output

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UpdateService clock must include timezone information.")
        return value


def _format_percent(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "None"


def _compact_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240] or "unknown error"
