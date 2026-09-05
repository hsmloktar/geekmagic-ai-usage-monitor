"""Claude usage provider backed by the official local Claude Code CLI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geekmagic_ai_monitor.configuration import ClaudeSettings
from geekmagic_ai_monitor.usage.models import UsageInfo

UsageCommandReader = Callable[[], Awaitable[Mapping[str, object]]]
Clock = Callable[[], datetime]

_SESSION_PATTERN = re.compile(
    r"^Current session:\s*(?P<percent>\d+(?:\.\d+)?)% used"
    r"(?:\s*·\s*resets\s+(?P<reset>.+))?$",
    re.MULTILINE,
)
_WEEK_PATTERN = re.compile(
    r"^Current week(?:\s*\([^)]*\))?:\s*(?P<percent>\d+(?:\.\d+)?)% used"
    r"(?:\s*·\s*resets\s+(?P<reset>.+))?$",
    re.MULTILINE,
)
_RESET_PATTERN = re.compile(
    r"^(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2}),\s+"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
    r"(?P<meridiem>am|pm)\s+\((?P<timezone>[^)]+)\)$",
    re.IGNORECASE,
)


class ClaudeUsageError(RuntimeError):
    """Raised when Claude usage cannot be read or decoded safely."""


class ClaudeUsageProvider:
    """Read Claude.ai subscription usage through Claude Code's local /usage command."""

    def __init__(
        self,
        settings: ClaudeSettings,
        *,
        usage_command_reader: UsageCommandReader | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._usage_command_reader = usage_command_reader
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def get_usage(self) -> UsageInfo:
        """Fetch and map Claude's 5-hour and weekly subscription windows."""
        payload = (
            await self._usage_command_reader()
            if self._usage_command_reader is not None
            else await self._read_from_claude_cli()
        )
        return self._parse_usage(payload)

    async def _read_from_claude_cli(self) -> Mapping[str, object]:
        executable = shutil.which(self._settings.executable)
        if executable is None:
            raise ClaudeUsageError(
                f"Claude executable was not found: {self._settings.executable!r}. "
                "Install Claude Code and sign in first."
            )

        try:
            process = await self._start_claude(executable)
        except OSError as error:
            raise ClaudeUsageError(f"Could not start Claude Code: {error}") from error

        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.request_timeout_seconds,
            )
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise ClaudeUsageError("Timed out while waiting for Claude usage data.") from error

        if process.returncode != 0:
            raise ClaudeUsageError(
                "Claude Code usage command failed. Confirm `claude auth status` and "
                "update Claude Code before retrying."
            )

        try:
            value: object = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClaudeUsageError("Claude Code returned invalid JSON.") from error
        if not isinstance(value, Mapping):
            raise ClaudeUsageError("Claude Code returned an invalid usage result.")
        return cast(Mapping[str, object], value)

    @staticmethod
    async def _start_claude(executable: str) -> asyncio.subprocess.Process:
        arguments = (
            "-p",
            "--safe-mode",
            "--output-format",
            "json",
            "--max-budget-usd",
            "0.000001",
            "--tools",
            "",
            "--no-session-persistence",
            "/usage",
        )
        if os.name == "nt":
            return await asyncio.create_subprocess_exec(
                executable,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        return await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def _parse_usage(self, payload: Mapping[str, object]) -> UsageInfo:
        _validate_zero_model_usage(payload)

        result = payload.get("result")
        if payload.get("is_error") is True or not isinstance(result, str):
            raise ClaudeUsageError("Claude Code did not return subscription usage text.")

        session = _match_window(_SESSION_PATTERN, result)
        week = _match_window(_WEEK_PATTERN, result)
        if session is None and week is None and not _is_recognized_usage_result(result):
            raise ClaudeUsageError(
                "Claude /usage output did not contain recognizable subscription usage data."
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ClaudeUsageError("Claude provider clock must include timezone information.")

        try:
            return UsageInfo(
                five_hour_used_percent=session.percent if session is not None else None,
                weekly_used_percent=week.percent if week is not None else None,
                five_hour_reset_at=(
                    _parse_reset_at(session.reset_text, now) if session is not None else None
                ),
                weekly_reset_at=(
                    _parse_reset_at(week.reset_text, now) if week is not None else None
                ),
            )
        except ValueError as error:
            raise ClaudeUsageError(f"Claude returned invalid usage values: {error}") from error


@dataclass(frozen=True, slots=True)
class _TextWindow:
    percent: float
    reset_text: str | None


def _match_window(pattern: re.Pattern[str], text: str) -> _TextWindow | None:
    match = pattern.search(text)
    if match is None:
        return None
    return _TextWindow(
        percent=float(match.group("percent")),
        reset_text=match.group("reset"),
    )


def _is_recognized_usage_result(text: str) -> bool:
    normalized = text.casefold()
    return (
        "you are currently using your subscription" in normalized
        or "what's contributing to your limits usage?" in normalized
    )


def _parse_reset_at(value: str | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    match = _RESET_PATTERN.fullmatch(value.strip())
    if match is None:
        return None

    try:
        timezone = ZoneInfo(match.group("timezone"))
        month = datetime.strptime(match.group("month"), "%b").month
    except (ValueError, ZoneInfoNotFoundError):
        return None

    hour = int(match.group("hour")) % 12
    if match.group("meridiem").lower() == "pm":
        hour += 12
    minute = int(match.group("minute") or 0)
    local_now = now.astimezone(timezone)

    candidates = tuple(
        datetime(
            year,
            month,
            int(match.group("day")),
            hour,
            minute,
            tzinfo=timezone,
        )
        for year in (local_now.year, local_now.year + 1)
    )
    future = tuple(candidate for candidate in candidates if candidate >= local_now)
    return min(future or candidates, key=lambda candidate: abs(candidate - local_now))


def _validate_zero_model_usage(payload: Mapping[str, object]) -> None:
    cost = payload.get("total_cost_usd", 0)
    if isinstance(cost, bool) or not isinstance(cost, int | float) or float(cost) != 0:
        raise ClaudeUsageError(
            "Claude /usage unexpectedly incurred model cost; refusing to use the result."
        )

    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise ClaudeUsageError("Claude Code did not report command token usage.")
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    for field in token_fields:
        value = usage.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int | float) or float(value) != 0:
            raise ClaudeUsageError(
                "Claude /usage unexpectedly invoked the model; refusing to use the result."
            )
