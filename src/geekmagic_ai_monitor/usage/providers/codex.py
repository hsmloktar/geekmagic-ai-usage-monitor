"""Codex usage provider backed by the official local Codex app-server."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from geekmagic_ai_monitor.configuration import CodexSettings
from geekmagic_ai_monitor.usage.models import UsageInfo

RateLimitsReader = Callable[[], Awaitable[Mapping[str, object]]]


class CodexUsageError(RuntimeError):
    """Raised when Codex usage cannot be read or decoded safely."""


@dataclass(frozen=True, slots=True)
class _RateLimitWindow:
    used_percent: float | None
    duration_minutes: int | None
    reset_at: datetime | None


class CodexUsageProvider:
    """Read the current ChatGPT Codex rate-limit windows."""

    _FIVE_HOURS_MINUTES = 5 * 60
    _WEEK_MINUTES = 7 * 24 * 60

    def __init__(
        self,
        settings: CodexSettings,
        *,
        rate_limits_reader: RateLimitsReader | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limits_reader = rate_limits_reader

    async def get_usage(self) -> UsageInfo:
        """Fetch and map the Codex 5-hour and weekly usage windows."""
        payload = (
            await self._rate_limits_reader()
            if self._rate_limits_reader is not None
            else await self._read_from_app_server()
        )
        return self._parse_usage(payload)

    async def _read_from_app_server(self) -> Mapping[str, object]:
        executable = shutil.which(self._settings.executable)
        if executable is None:
            raise CodexUsageError(
                f"Codex executable was not found: {self._settings.executable!r}. "
                "Install Codex CLI and sign in first."
            )

        try:
            process = await self._start_app_server(executable)
        except OSError as error:
            raise CodexUsageError(f"Could not start Codex app-server: {error}") from error

        try:
            return await asyncio.wait_for(
                self._exchange_messages(process),
                timeout=self._settings.request_timeout_seconds,
            )
        except TimeoutError as error:
            raise CodexUsageError(
                "Timed out while waiting for Codex app-server usage data."
            ) from error
        finally:
            await _stop_process(process)

    @staticmethod
    async def _start_app_server(executable: str) -> asyncio.subprocess.Process:
        if os.name == "nt":
            return await asyncio.create_subprocess_exec(
                executable,
                "app-server",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )

        return await asyncio.create_subprocess_exec(
            executable,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _exchange_messages(
        self,
        process: asyncio.subprocess.Process,
    ) -> Mapping[str, object]:
        await _send_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "geekmagic-ai-monitor",
                        "version": "0.1.0",
                    }
                },
            },
        )
        _raise_for_response_error(await _read_response(process, request_id=1))

        await _send_message(process, {"method": "initialized"})
        await _send_message(process, {"id": 2, "method": "account/rateLimits/read"})
        response = await _read_response(process, request_id=2)
        _raise_for_response_error(response)

        result = response.get("result")
        if not isinstance(result, Mapping):
            raise CodexUsageError("Codex app-server returned no rate-limit result.")
        return cast(Mapping[str, object], result)

    @classmethod
    def _parse_usage(cls, payload: Mapping[str, object]) -> UsageInfo:
        snapshot = _select_codex_snapshot(payload)
        primary = _parse_window(snapshot.get("primary"), name="primary")
        secondary = _parse_window(snapshot.get("secondary"), name="secondary")
        windows = tuple(window for window in (primary, secondary) if window is not None)

        five_hour = _find_duration(windows, cls._FIVE_HOURS_MINUTES)
        weekly = _find_duration(windows, cls._WEEK_MINUTES)

        # Older app-server responses may omit windowDurationMins. In that shape,
        # primary is the short window and secondary is the long window.
        if five_hour is None and primary is not weekly:
            five_hour = primary
        if weekly is None and secondary is not five_hour:
            weekly = secondary

        if five_hour is None and weekly is None:
            raise CodexUsageError("Codex returned no usable rate-limit windows.")

        try:
            return UsageInfo(
                five_hour_used_percent=(five_hour.used_percent if five_hour is not None else None),
                weekly_used_percent=weekly.used_percent if weekly is not None else None,
                five_hour_reset_at=five_hour.reset_at if five_hour is not None else None,
                weekly_reset_at=weekly.reset_at if weekly is not None else None,
            )
        except ValueError as error:
            raise CodexUsageError(f"Codex returned invalid rate-limit values: {error}") from error


async def _send_message(
    process: asyncio.subprocess.Process,
    message: Mapping[str, object],
) -> None:
    if process.stdin is None:
        raise CodexUsageError("Codex app-server stdin is unavailable.")
    encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode()
    process.stdin.write(encoded)
    await process.stdin.drain()


async def _read_response(
    process: asyncio.subprocess.Process,
    *,
    request_id: int,
) -> Mapping[str, object]:
    if process.stdout is None:
        raise CodexUsageError("Codex app-server stdout is unavailable.")

    while True:
        line = await process.stdout.readline()
        if not line:
            raise CodexUsageError(
                "Codex app-server stopped before returning the requested usage data."
            )
        try:
            value: object = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CodexUsageError("Codex app-server returned invalid JSON.") from error
        if isinstance(value, Mapping) and value.get("id") == request_id:
            return cast(Mapping[str, object], value)


def _raise_for_response_error(response: Mapping[str, object]) -> None:
    error = response.get("error")
    if error is None:
        return

    code: object = "unknown"
    message = "request failed"
    if isinstance(error, Mapping):
        code = error.get("code", code)
        raw_message = error.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            message = " ".join(raw_message.split())[:240]
    raise CodexUsageError(f"Codex app-server error {code}: {message}")


def _select_codex_snapshot(payload: Mapping[str, object]) -> Mapping[str, object]:
    by_limit_id = payload.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, Mapping):
        codex = by_limit_id.get("codex")
        if isinstance(codex, Mapping):
            return cast(Mapping[str, object], codex)

    legacy = payload.get("rateLimits")
    if isinstance(legacy, Mapping):
        return cast(Mapping[str, object], legacy)
    raise CodexUsageError("Codex response did not contain a Codex rate-limit bucket.")


def _parse_window(value: object, *, name: str) -> _RateLimitWindow | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CodexUsageError(f"Codex {name} rate-limit window is invalid.")

    used_percent = _optional_number(value.get("usedPercent"), field="usedPercent")
    duration = _optional_integer(value.get("windowDurationMins"), field="windowDurationMins")
    reset_timestamp = _optional_integer(value.get("resetsAt"), field="resetsAt")
    try:
        reset_at = (
            datetime.fromtimestamp(reset_timestamp, tz=UTC) if reset_timestamp is not None else None
        )
    except (OSError, OverflowError, ValueError) as error:
        raise CodexUsageError("Codex resetsAt timestamp is invalid.") from error
    return _RateLimitWindow(used_percent, duration, reset_at)


def _optional_number(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CodexUsageError(f"Codex {field} must be numeric.")
    return float(value)


def _optional_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodexUsageError(f"Codex {field} must be an integer.")
    return value


def _find_duration(
    windows: tuple[_RateLimitWindow, ...],
    duration_minutes: int,
) -> _RateLimitWindow | None:
    return next(
        (window for window in windows if window.duration_minutes == duration_minutes),
        None,
    )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.stdin is not None:
        process.stdin.close()

    if process.returncode is not None:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
        return
    except TimeoutError:
        process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except TimeoutError:
        process.kill()
        await process.wait()
