"""Load and validate application settings from JSON files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when application settings are missing or invalid."""


@dataclass(frozen=True, slots=True)
class GeekMagicSettings:
    """Settings used to communicate with a GeekMagic device."""

    host: str
    image_file_name: str = "geekmagic-ai-monitor.jpg"
    request_timeout_seconds: float = 10.0

    @property
    def base_url(self) -> str:
        """Return a validated HTTP base URL for the configured device."""
        value = self.host.strip().rstrip("/")
        if not value:
            raise ConfigurationError("GeekMagic.Host is empty. Set it in appsettings.local.json.")

        if "://" not in value:
            value = f"http://{value}"

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError(
                "GeekMagic.Host must be an IP address, host name, or HTTP URL."
            )
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ConfigurationError("GeekMagic.Host must not contain a path, query, or fragment.")

        return value


@dataclass(frozen=True, slots=True)
class CodexSettings:
    """Settings used to query the locally authenticated Codex CLI."""

    executable: str = "codex"
    request_timeout_seconds: float = 15.0


@dataclass(frozen=True, slots=True)
class ClaudeSettings:
    """Settings used to query the locally authenticated Claude Code CLI."""

    executable: str = "claude"
    request_timeout_seconds: float = 20.0


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Root application settings."""

    geekmagic: GeekMagicSettings
    codex: CodexSettings = field(default_factory=CodexSettings)
    claude: ClaudeSettings = field(default_factory=ClaudeSettings)
    update_interval_seconds: int = 60


def load_app_settings(settings_dir: Path | None = None) -> AppSettings:
    """Load base settings and apply the optional per-machine override."""
    root = (settings_dir or Path.cwd()).resolve()
    base_path = root / "appsettings.json"
    local_path = root / "appsettings.local.json"

    data = _read_json_object(base_path, required=True)
    if local_path.exists():
        data = _merge_mappings(data, _read_json_object(local_path, required=False))

    geekmagic_data = _mapping_value(data, "GeekMagic")
    host = _string_value(geekmagic_data, "Host", default="")
    image_file_name = _string_value(
        geekmagic_data,
        "ImageFileName",
        default="geekmagic-ai-monitor.jpg",
    )
    timeout = _number_value(geekmagic_data, "RequestTimeoutSeconds", default=10.0)

    codex_data = _optional_mapping_value(data, "Codex")
    codex_executable = _string_value(codex_data, "Executable", default="codex").strip()
    codex_timeout = _number_value(codex_data, "RequestTimeoutSeconds", default=15.0)

    claude_data = _optional_mapping_value(data, "Claude")
    claude_executable = _string_value(claude_data, "Executable", default="claude").strip()
    claude_timeout = _number_value(claude_data, "RequestTimeoutSeconds", default=20.0)
    update_interval = _integer_value(data, "UpdateIntervalSeconds", default=60)

    if timeout <= 0:
        raise ConfigurationError("GeekMagic.RequestTimeoutSeconds must be greater than zero.")
    if not codex_executable:
        raise ConfigurationError("Codex.Executable must not be empty.")
    if codex_timeout <= 0:
        raise ConfigurationError("Codex.RequestTimeoutSeconds must be greater than zero.")
    if not claude_executable:
        raise ConfigurationError("Claude.Executable must not be empty.")
    if claude_timeout <= 0:
        raise ConfigurationError("Claude.RequestTimeoutSeconds must be greater than zero.")
    if update_interval <= 0:
        raise ConfigurationError("UpdateIntervalSeconds must be greater than zero.")

    return AppSettings(
        geekmagic=GeekMagicSettings(
            host=host,
            image_file_name=image_file_name,
            request_timeout_seconds=timeout,
        ),
        codex=CodexSettings(
            executable=codex_executable,
            request_timeout_seconds=codex_timeout,
        ),
        claude=ClaudeSettings(
            executable=claude_executable,
            request_timeout_seconds=claude_timeout,
        ),
        update_interval_seconds=update_interval,
    )


def _read_json_object(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigurationError(f"Settings file not found: {path}")
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Could not read settings file {path}: {error}") from error

    if not isinstance(value, dict):
        raise ConfigurationError(f"Settings file must contain a JSON object: {path}")
    return value


def _merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_mappings(existing, value)
        else:
            merged[key] = value
    return merged


def _mapping_value(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{key} must be a JSON object.")
    return value


def _optional_mapping_value(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{key} must be a JSON object.")
    return value


def _string_value(data: Mapping[str, Any], key: str, *, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigurationError(f"{key} must be a string.")
    return value


def _number_value(data: Mapping[str, Any], key: str, *, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigurationError(f"{key} must be a number.")
    return float(value)


def _integer_value(data: Mapping[str, Any], key: str, *, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer.")
    return int(value)
