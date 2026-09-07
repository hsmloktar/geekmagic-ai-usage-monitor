"""Windows tray and macOS menu-bar host for the update service."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from importlib import import_module
from pathlib import Path

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem  # type: ignore[import-untyped]

from geekmagic_ai_monitor.configuration import ConfigurationError, load_app_settings
from geekmagic_ai_monitor.geekmagic import GeekMagicClient
from geekmagic_ai_monitor.rendering import DashboardRenderer
from geekmagic_ai_monitor.runtime import (
    AlreadyRunningError,
    RuntimeLogger,
    SingleInstanceLock,
    UpdateService,
)
from geekmagic_ai_monitor.usage import ClaudeUsageProvider, CodexUsageProvider

DEFAULT_OUTPUT = Path("artifacts/geekmagic-current.jpg")
DEFAULT_LOG_FILE = Path("artifacts/logs/monitor.log")
DEFAULT_LOCK_FILE = Path("artifacts/geekmagic-monitor.lock")
TRAY_INTERVAL_MINUTES = (1, 5, 10)


class TrayApplication:
    """Own the tray UI and run the asyncio monitor loop in its setup thread."""

    def __init__(
        self,
        *,
        settings_dir: Path,
        output_path: Path,
        log_path: Path,
        runtime_log: RuntimeLogger,
    ) -> None:
        self._settings = load_app_settings(settings_dir)
        self._output_path = output_path
        self._log_path = log_path
        self._runtime_log = runtime_log
        self._status_lock = threading.Lock()
        self._interval_lock = threading.Lock()
        self._status = "시작 중"
        self._tray_state_path = output_path.parent / "tray-settings.json"
        configured_minutes = self._settings.update_interval_seconds // 60
        self._update_interval_minutes = _load_tray_interval_minutes(
            self._tray_state_path,
            default_minutes=configured_minutes,
        )
        self._exit_requested = threading.Event()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._update_service: UpdateService | None = None
        self._monitor_task: asyncio.Task[None] | None = None

        interval_menu = Menu(
            *(self._create_interval_menu_item(value) for value in TRAY_INTERVAL_MINUTES)
        )
        self._icon = Icon(
            "geekmagic-ai-monitor",
            icon=create_tray_image(),
            title="GeekMagic AI Monitor · 시작 중",
            menu=Menu(
                MenuItem(
                    self._status_menu_text,
                    self._show_status,
                    default=sys.platform == "win32",
                    enabled=sys.platform == "win32",
                ),
                Menu.SEPARATOR,
                MenuItem("지금 갱신", self._request_update),
                MenuItem("갱신 주기", interval_menu),
                Menu.SEPARATOR,
                MenuItem("로그 열기", self._open_log),
                MenuItem("종료", self._request_exit),
            ),
        )

    def run(self) -> None:
        """Block in the native main-thread message loop until Exit is selected."""
        self._icon.run(setup=self._setup)

    def _setup(self, icon: Icon) -> None:
        _dispatch_ui(lambda: setattr(icon, "visible", True))
        try:
            asyncio.run(self._run_monitor())
        except Exception as error:
            self._runtime_log(
                f"Tray monitor failed ({type(error).__name__}): {_compact_error(error)}"
            )
            self._set_status("오류 · 로그 확인")
        finally:
            # Stop the UI only after asyncio has closed providers and the HTTP client.
            _dispatch_ui(icon.stop)

    async def _run_monitor(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        if self._exit_requested.is_set():
            return

        async with GeekMagicClient(self._settings.geekmagic) as client:
            with self._interval_lock:
                interval_seconds = self._update_interval_minutes * 60
            service = UpdateService(
                codex_provider=CodexUsageProvider(self._settings.codex),
                claude_provider=ClaudeUsageProvider(self._settings.claude),
                renderer=DashboardRenderer(),
                device=client,
                image_file_name=self._settings.geekmagic.image_file_name,
                output_path=self._output_path,
                update_interval_seconds=interval_seconds,
                source_device="MAC" if sys.platform == "darwin" else "WIN",
                logger=self._monitor_log,
            )
            self._update_service = service
            self._runtime_log(f"Tray update interval: {interval_seconds // 60}m")
            self._monitor_task = asyncio.create_task(service.run())
            if self._exit_requested.is_set():
                self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                self._runtime_log("Tray update loop stopped.")
            finally:
                self._monitor_task = None
                self._update_service = None
                self._event_loop = None

    def _monitor_log(self, message: str) -> None:
        self._runtime_log(message)
        if message == "Update started":
            self._set_status("업데이트 중")
        elif message.startswith("Update completed:"):
            self._set_status(f"정상 · 마지막 업데이트 {datetime.now().astimezone():%H:%M}")
        elif message.startswith("Update cycle failed"):
            self._set_status("오류 · 다음 주기 재시도")

    def _set_status(self, value: str) -> None:
        with self._status_lock:
            self._status = value
        _dispatch_ui(self._refresh_status)

    def _refresh_status(self) -> None:
        with self._status_lock:
            value = self._status
        self._icon.title = f"GeekMagic AI Monitor · {value}"
        self._icon.update_menu()

    def _status_menu_text(self, _: MenuItem) -> str:
        with self._status_lock:
            return f"상태: {self._status}"

    def _show_status(self, icon: Icon, _: MenuItem) -> None:
        with self._status_lock:
            status = self._status
        try:
            icon.notify(status, "GeekMagic AI Monitor")
        except Exception:
            pass

    def _create_interval_menu_item(self, minutes: int) -> MenuItem:
        return MenuItem(
            f"{minutes}분",
            lambda icon, _: self._select_interval(icon, minutes),
            checked=lambda _: self._is_interval_selected(minutes),
            radio=True,
        )

    def _is_interval_selected(self, minutes: int) -> bool:
        with self._interval_lock:
            return self._update_interval_minutes == minutes

    def _select_interval(self, icon: Icon, minutes: int) -> None:
        with self._interval_lock:
            if self._update_interval_minutes == minutes:
                return
            self._update_interval_minutes = minutes

        try:
            _save_tray_interval_minutes(self._tray_state_path, minutes)
        except OSError as error:
            self._runtime_log(
                f"Could not save tray update interval ({type(error).__name__}): "
                f"{_compact_error(error)}"
            )

        self._runtime_log(f"Tray update interval selected: {minutes}m")
        icon.update_menu()
        loop = self._event_loop
        if loop is not None:
            loop.call_soon_threadsafe(self._apply_selected_interval)

    def _apply_selected_interval(self) -> None:
        service = self._update_service
        if service is None:
            return
        with self._interval_lock:
            interval_seconds = self._update_interval_minutes * 60
        service.set_update_interval_seconds(interval_seconds)

    def _request_update(self, _: Icon, __: MenuItem) -> None:
        self._runtime_log("Tray immediate update requested.")
        self._set_status("업데이트 요청됨")
        loop = self._event_loop
        if loop is not None:
            loop.call_soon_threadsafe(self._apply_update_request)

    def _apply_update_request(self) -> None:
        service = self._update_service
        if service is not None:
            service.request_update()

    def _open_log(self, _: Icon, __: MenuItem) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.touch(exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", "-a", "TextEdit", str(self._log_path.resolve())])
        else:
            subprocess.Popen(
                ["notepad.exe", str(self._log_path.resolve())],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )

    def _request_exit(self, icon: Icon, _: MenuItem) -> None:
        self._runtime_log("Tray exit requested by user.")
        self._exit_requested.set()
        loop = self._event_loop
        task = self._monitor_task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)


def _dispatch_ui(callback: Callable[[], None]) -> None:
    """Cocoa UI objects must only be changed on the main thread."""
    if sys.platform == "darwin" and threading.current_thread() is not threading.main_thread():
        app_helper = import_module("PyObjCTools.AppHelper")
        app_helper.callAfter(callback)
    else:
        callback()


def _configure_macos_app() -> None:
    appkit = import_module("AppKit")
    appkit.NSApplication.sharedApplication().setActivationPolicy_(
        appkit.NSApplicationActivationPolicyAccessory
    )


def create_tray_image() -> Image.Image:
    """Create a compact AI usage icon without an external binary asset."""
    image = Image.new("RGBA", (64, 64), "#07101d")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 61, 61), radius=13, outline="#1e3a52", width=3)
    draw.rounded_rectangle((13, 17, 51, 25), radius=4, fill="#1e293b")
    draw.rounded_rectangle((13, 17, 42, 25), radius=4, fill="#22d3ee")
    draw.rounded_rectangle((13, 38, 51, 46), radius=4, fill="#1e293b")
    draw.rounded_rectangle((13, 38, 32, 46), radius=4, fill="#f59e0b")
    return image


def _load_tray_interval_minutes(path: Path, *, default_minutes: int) -> int:
    fallback = default_minutes if default_minutes in TRAY_INTERVAL_MINUTES else 1
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(value, dict):
        return fallback

    minutes = value.get("update_interval_minutes")
    if type(minutes) is int and minutes in TRAY_INTERVAL_MINUTES:
        return minutes
    return fallback


def _save_tray_interval_minutes(path: Path, minutes: int) -> None:
    if minutes not in TRAY_INTERVAL_MINUTES:
        raise ValueError(f"Unsupported tray update interval: {minutes}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"update_interval_minutes": minutes}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GeekMagic AI Monitor tray / menu-bar host")
    parser.add_argument("--settings-dir", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if sys.platform not in {"win32", "darwin"}:
        print("The tray host supports Windows and macOS only.", file=sys.stderr)
        return 1

    try:
        with (
            SingleInstanceLock(args.lock_file),
            RuntimeLogger(args.log_file, console=False) as runtime_log,
        ):
            if sys.platform == "darwin":
                _configure_macos_app()
            system = "macOS" if sys.platform == "darwin" else "Windows"
            runtime_log(f"{system} tray monitor starting.")
            TrayApplication(
                settings_dir=args.settings_dir,
                output_path=args.output,
                log_path=args.log_file,
                runtime_log=runtime_log,
            ).run()
            runtime_log("Tray monitor stopped.")
        return 0
    except AlreadyRunningError:
        return 0
    except (ConfigurationError, OSError, RuntimeError) as error:
        _show_startup_error(_compact_error(error))
        return 1


def _show_startup_error(message: str) -> None:
    if sys.platform == "darwin":
        appkit = import_module("AppKit")
        alert = appkit.NSAlert.alloc().init()
        alert.setMessageText_("GeekMagic AI Monitor를 시작하지 못했습니다.")
        alert.setInformativeText_(message)
        alert.runModal()
        return

    if sys.platform != "win32":
        print(f"Error: {message}", file=sys.stderr)
        return

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            f"GeekMagic AI Monitor를 시작하지 못했습니다.\n\n{message}",
            "GeekMagic AI Monitor",
            0x10,
        )
    except Exception:
        print(f"Error: {message}", file=sys.stderr)


def _compact_error(error: Exception) -> str:
    return " ".join(str(error).split())[:240] or "unknown error"


if __name__ == "__main__":
    raise SystemExit(main())
