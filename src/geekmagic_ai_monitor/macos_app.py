"""Install a local macOS app that runs this checkout's virtual environment."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

from geekmagic_ai_monitor.runtime import AlreadyRunningError, SingleInstanceLock

APP_NAME = "GeekMagic AI Monitor.app"
APP_EXECUTABLE = "geekmagic-monitor"
BUNDLE_ID = APP_EXECUTABLE
LEGACY_BUNDLE_IDS = frozenset({"local.geekmagic.ai-usage-monitor"})


def _is_our_app(path: Path) -> bool:
    try:
        with (path / "Contents" / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
            return isinstance(info, dict) and info.get("CFBundleIdentifier") in {
                BUNDLE_ID,
                *LEGACY_BUNDLE_IDS,
            }
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def _build_launcher(project: Path, executable_path: str) -> bytes:
    library = Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY")
    if not library.is_file():
        raise RuntimeError(f"Python shared library is missing: {library}")
    args = [
        str(project / ".venv/bin/python"),
        "-m",
        "geekmagic_ai_monitor.tray",
        "--settings-dir",
        str(project),
        "--output",
        str(project / "artifacts/geekmagic-current.jpg"),
        "--log-file",
        str(project / "artifacts/logs/monitor.log"),
        "--lock-file",
        str(project / "artifacts/geekmagic-monitor.lock"),
    ]
    definitions = {
        "PROJECT_ROOT": str(project),
        "PROVIDER_PATH": executable_path,
        "PYTHON_LIBRARY": str(library),
    }
    header = "".join(
        f"#define {key} {json.dumps(value, ensure_ascii=False)}\n"
        for key, value in definitions.items()
    )
    header += (
        "#define PYTHON_ARGUMENTS {"
        + ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
        + ", NULL}\n"
    )
    with tempfile.TemporaryDirectory(prefix="geekmagic-build-") as temporary:
        root = Path(temporary)
        config = root / "config.h"
        config.write_text(header, encoding="utf-8")
        executable = root / APP_EXECUTABLE
        result = subprocess.run(
            [
                "/usr/bin/clang",
                "-Os",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-include",
                str(config),
                str(project / "macos/launcher.c"),
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                "Could not build the app launcher. Install Xcode Command Line Tools.\n"
                + result.stderr
            )
        return executable.read_bytes()


def _provider_path() -> str:
    # Finder has a minimal PATH. Record executable directories, never shell setup or tokens.
    paths = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    for command in ("codex", "claude", "node"):
        executable = shutil.which(command)
        if executable:
            paths.insert(0, str(Path(executable).parent))
    paths.extend(("/usr/bin", "/bin", "/usr/sbin", "/sbin"))
    return os.pathsep.join(dict.fromkeys(paths))


def _sign_app(app: Path) -> None:
    result = subprocess.run(
        [
            "/usr/bin/codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--identifier",
            BUNDLE_ID,
            str(app),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Could not sign the macOS app: {result.stderr.strip()}")


def install_app(project: Path, applications: Path, desktop: Path) -> Path:
    """Install only our app and shortcut; preserve any unrelated files with the same name."""
    project = project.resolve()
    app = applications / APP_NAME
    shortcut = desktop / APP_NAME
    if not (project / ".venv/bin/python").is_file():
        raise RuntimeError("Run uv sync --locked in the project before installing the app.")
    if app.is_symlink() or (app.exists() and not _is_our_app(app)):
        raise RuntimeError(f"Refusing to replace an unrelated app: {app}")
    if os.path.lexists(shortcut) and not (shortcut.is_symlink() and shortcut.readlink() == app):
        raise RuntimeError(f"Refusing to replace an unrelated desktop item: {shortcut}")

    from geekmagic_ai_monitor.tray import create_tray_image

    executable_data = _build_launcher(project, _provider_path())
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    launcher = macos / APP_EXECUTABLE
    launcher.write_bytes(executable_data)
    launcher.chmod(0o755)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleName": "GeekMagic AI Monitor",
                "CFBundleDisplayName": "GeekMagic AI Monitor",
                "CFBundleExecutable": launcher.name,
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleIconFile": "monitor.icns",
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
                "NSLocalNetworkUsageDescription": (
                    "같은 네트워크의 GeekMagic에 사용량 화면을 전송합니다."
                ),
            },
            stream,
        )
    create_tray_image().resize((1024, 1024)).save(resources / "monitor.icns")
    _sign_app(app)
    desktop.mkdir(parents=True, exist_ok=True)
    if not shortcut.is_symlink():
        shortcut.symlink_to(app, target_is_directory=True)
    return app


def uninstall_app(applications: Path, desktop: Path) -> None:
    """Remove our app and its shortcut while keeping project settings and logs."""
    app = applications / APP_NAME
    shortcut = desktop / APP_NAME
    if app.is_symlink() or (app.exists() and not _is_our_app(app)):
        raise RuntimeError(f"Refusing to remove an unrelated app: {app}")
    if shortcut.is_symlink() and shortcut.readlink() == app:
        shortcut.unlink()
    if app.exists():
        shutil.rmtree(app)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "uninstall"))
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("This installer supports macOS only.", file=sys.stderr)
        return 1
    project = args.project_root.resolve()
    try:
        with SingleInstanceLock(project / "artifacts/geekmagic-monitor.lock"):
            applications = Path.home() / "Applications"
            desktop = Path.home() / "Desktop"
            if args.command == "install":
                print(f"Installed: {install_app(project, applications, desktop)}")
                print(f"Desktop shortcut: {desktop / APP_NAME}")
            else:
                uninstall_app(applications, desktop)
                print("Removed the app and its desktop shortcut. Project files were preserved.")
    except (AlreadyRunningError, OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
