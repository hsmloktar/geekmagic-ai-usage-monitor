import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from geekmagic_ai_monitor import tray


def test_exit_waits_for_async_cleanup_before_stopping_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "appsettings.json").write_text(
        '{"GeekMagic": {"Host": "device.local"}}', encoding="utf-8"
    )
    icon = MagicMock()
    monkeypatch.setattr(tray, "Icon", MagicMock(return_value=icon))
    pending_ui: list[Callable[[], None]] = []
    monkeypatch.setattr(tray, "_dispatch_ui", pending_ui.append)
    app = tray.TrayApplication(
        settings_dir=tmp_path,
        output_path=tmp_path / "current.jpg",
        log_path=tmp_path / "monitor.log",
        runtime_log=MagicMock(),
    )
    started = threading.Event()
    cleaned_up = threading.Event()

    async def monitor() -> None:
        app._event_loop = asyncio.get_running_loop()
        app._monitor_task = asyncio.create_task(asyncio.sleep(60))
        started.set()
        try:
            await app._monitor_task
        except asyncio.CancelledError:
            pass
        finally:
            # Model asynchronous provider and HTTP cleanup before leaving the worker.
            await asyncio.sleep(0)
            cleaned_up.set()

    monkeypatch.setattr(app, "_run_monitor", monitor)
    worker = threading.Thread(target=app._setup, args=(icon,))
    worker.start()
    try:
        assert started.wait(timeout=2)
        app._request_exit(icon, MagicMock())
        icon.stop.assert_not_called()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert cleaned_up.is_set()
        for callback in pending_ui:
            callback()
        icon.stop.assert_called_once()
    finally:
        if worker.is_alive():
            app._request_exit(icon, MagicMock())
            worker.join(timeout=2)


def test_status_update_dispatches_ui_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "appsettings.json").write_text(
        '{"GeekMagic": {"Host": "device.local"}}', encoding="utf-8"
    )
    icon = MagicMock()
    monkeypatch.setattr(tray, "Icon", MagicMock(return_value=icon))
    pending_ui: list[Callable[[], None]] = []
    monkeypatch.setattr(tray, "_dispatch_ui", pending_ui.append)
    app = tray.TrayApplication(
        settings_dir=tmp_path,
        output_path=tmp_path / "current.jpg",
        log_path=tmp_path / "monitor.log",
        runtime_log=MagicMock(),
    )
    app._set_status("정상")
    icon.update_menu.assert_not_called()
    pending_ui.pop()()
    assert icon.title == "GeekMagic AI Monitor · 정상"
    icon.update_menu.assert_called_once()
