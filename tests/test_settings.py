import json
from pathlib import Path

import pytest

from geekmagic_ai_monitor.configuration import ConfigurationError, load_app_settings


def test_local_settings_override_base_settings(tmp_path: Path) -> None:
    (tmp_path / "appsettings.json").write_text(
        json.dumps(
            {
                "GeekMagic": {
                    "Host": "",
                    "ImageFileName": "base.jpg",
                    "RequestTimeoutSeconds": 10,
                },
                "Codex": {
                    "Executable": "codex-custom",
                    "RequestTimeoutSeconds": 20,
                },
                "Claude": {
                    "Executable": "claude-custom",
                    "RequestTimeoutSeconds": 25,
                },
                "UpdateIntervalSeconds": 60,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "appsettings.local.json").write_text(
        json.dumps({"GeekMagic": {"Host": "192.168.0.144"}}),
        encoding="utf-8",
    )

    settings = load_app_settings(tmp_path)

    assert settings.geekmagic.host == "192.168.0.144"
    assert settings.geekmagic.base_url == "http://192.168.0.144"
    assert settings.geekmagic.image_file_name == "base.jpg"
    assert settings.codex.executable == "codex-custom"
    assert settings.codex.request_timeout_seconds == 20
    assert settings.claude.executable == "claude-custom"
    assert settings.claude.request_timeout_seconds == 25
    assert settings.update_interval_seconds == 60


def test_empty_host_is_rejected_when_base_url_is_used(tmp_path: Path) -> None:
    (tmp_path / "appsettings.json").write_text(
        json.dumps({"GeekMagic": {"Host": ""}}),
        encoding="utf-8",
    )

    settings = load_app_settings(tmp_path)

    with pytest.raises(ConfigurationError, match="Host is empty"):
        _ = settings.geekmagic.base_url


def test_codex_settings_have_backward_compatible_defaults(tmp_path: Path) -> None:
    (tmp_path / "appsettings.json").write_text(
        json.dumps({"GeekMagic": {"Host": "192.168.0.144"}}),
        encoding="utf-8",
    )

    settings = load_app_settings(tmp_path)

    assert settings.codex.executable == "codex"
    assert settings.codex.request_timeout_seconds == 15
    assert settings.claude.executable == "claude"
    assert settings.claude.request_timeout_seconds == 20


@pytest.mark.parametrize(
    ("codex_settings", "message"),
    [
        ({"Executable": "   "}, "Executable"),
        ({"RequestTimeoutSeconds": 0}, "RequestTimeoutSeconds"),
    ],
)
def test_invalid_codex_settings_are_rejected(
    tmp_path: Path,
    codex_settings: dict[str, object],
    message: str,
) -> None:
    (tmp_path / "appsettings.json").write_text(
        json.dumps(
            {
                "GeekMagic": {"Host": "192.168.0.144"},
                "Codex": codex_settings,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_app_settings(tmp_path)


@pytest.mark.parametrize(
    ("claude_settings", "message"),
    [
        ({"Executable": "   "}, "Executable"),
        ({"RequestTimeoutSeconds": 0}, "RequestTimeoutSeconds"),
    ],
)
def test_invalid_claude_settings_are_rejected(
    tmp_path: Path,
    claude_settings: dict[str, object],
    message: str,
) -> None:
    (tmp_path / "appsettings.json").write_text(
        json.dumps(
            {
                "GeekMagic": {"Host": "192.168.0.144"},
                "Claude": claude_settings,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_app_settings(tmp_path)
