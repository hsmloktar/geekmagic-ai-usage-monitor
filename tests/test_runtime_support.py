from datetime import date
from pathlib import Path

import pytest

from geekmagic_ai_monitor.runtime import (
    AlreadyRunningError,
    RuntimeLogger,
    SingleInstanceLock,
)
from geekmagic_ai_monitor.tray import (
    _load_tray_interval_minutes,
    _save_tray_interval_minutes,
    create_tray_image,
)


def test_single_instance_lock_rejects_duplicate_and_releases(tmp_path: Path) -> None:
    lock_path = tmp_path / "monitor.lock"

    with SingleInstanceLock(lock_path):
        with pytest.raises(AlreadyRunningError, match="already running"):
            with SingleInstanceLock(lock_path):
                pytest.fail("duplicate lock unexpectedly acquired")

    with SingleInstanceLock(lock_path) as acquired:
        assert acquired.path == lock_path.resolve()


def test_runtime_logger_writes_and_rotates_files(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "monitor.log"

    with RuntimeLogger(
        log_path,
        max_bytes=180,
        backup_count=2,
        console=False,
    ) as runtime_log:
        for index in range(20):
            runtime_log(f"update message {index:02d} with enough text to rotate")

    assert log_path.exists()
    assert (log_path.parent / "monitor.log.1").exists()
    assert len(list(log_path.parent.glob("monitor.log*"))) <= 3
    combined = "".join(
        path.read_text(encoding="utf-8") for path in log_path.parent.glob("monitor.log*")
    )
    assert "update message 19" in combined


def test_runtime_logger_keeps_only_today_when_starting(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "monitor.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "2026-09-03 23:59:59 INFO previous day\n"
        "2026-09-04 08:00:00 INFO today current\n"
        "damaged line\n",
        encoding="utf-8",
    )
    Path(f"{log_path}.1").write_text(
        "2026-09-03 20:00:00 INFO previous backup\n"
        "2026-09-04 07:00:00 INFO today backup\n",
        encoding="utf-8",
    )

    with RuntimeLogger(
        log_path,
        backup_count=2,
        console=False,
        today=date(2026, 9, 4),
    ):
        pass

    contents = log_path.read_text(encoding="utf-8")
    assert "previous day" not in contents
    assert "previous backup" not in contents
    assert "damaged line" not in contents
    assert contents.splitlines() == [
        "2026-09-04 07:00:00 INFO today backup",
        "2026-09-04 08:00:00 INFO today current",
    ]
    assert not Path(f"{log_path}.1").exists()


def test_windows_launcher_is_present() -> None:
    launcher = Path(__file__).parents[1] / "windows" / "run-monitor.ps1"

    assert launcher.is_file()
    content = launcher.read_text(encoding="utf-8")
    assert "--project $projectRoot" in content
    assert "--settings-dir $projectRoot" in content


def test_tray_icon_is_64_pixel_rgba_image() -> None:
    image = create_tray_image()

    assert image.mode == "RGBA"
    assert image.size == (64, 64)
    pixel = image.getpixel((20, 20))
    assert isinstance(pixel, tuple)
    assert pixel[:3] == (34, 211, 238)


def test_tray_update_interval_is_persisted(tmp_path: Path) -> None:
    state_path = tmp_path / "tray-settings.json"

    assert _load_tray_interval_minutes(state_path, default_minutes=5) == 5

    _save_tray_interval_minutes(state_path, 10)

    assert _load_tray_interval_minutes(state_path, default_minutes=1) == 10
    with pytest.raises(ValueError, match="Unsupported"):
        _save_tray_interval_minutes(state_path, 2)


def test_windows_tray_and_shortcut_scripts_are_present() -> None:
    windows_dir = Path(__file__).parents[1] / "windows"
    start_tray = (windows_dir / "start-tray.ps1").read_text(encoding="utf-8")
    install_shortcut = (windows_dir / "install-desktop-shortcut.ps1").read_text(encoding="utf-8")
    uninstall_shortcut = (windows_dir / "uninstall-desktop-shortcut.ps1").read_text(
        encoding="utf-8"
    )

    assert "geekmagic-ai-monitor-tray" in start_tray
    assert "GetEnvironmentVariable('Path', 'User')" in start_tray
    assert "Start-Process" in start_tray
    assert "-WindowStyle Hidden" in start_tray
    assert "& uv run" not in start_tray
    assert "-WindowStyle Hidden" in install_shortcut
    assert "GeekMagic AI Monitor.lnk" in install_shortcut
    assert "Remove-Item -LiteralPath" in uninstall_shortcut
