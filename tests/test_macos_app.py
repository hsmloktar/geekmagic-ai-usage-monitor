import plistlib
import sys
from pathlib import Path

import pytest

from geekmagic_ai_monitor import macos_app

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS app installation")


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "프로젝트 with spaces"
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(macos_app, "_build_launcher", lambda *_: b"native launcher")
    monkeypatch.setattr(macos_app, "_sign_app", lambda *_: None)
    return project


def test_install_reinstall_and_uninstall_preserve_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    applications = tmp_path / "Applications"
    desktop = tmp_path / "Desktop"
    settings = project / "appsettings.local.json"
    settings.write_text('{"GeekMagic": {"Host": "device.local"}}', encoding="utf-8")

    app = macos_app.install_app(project, applications, desktop)
    shortcut = desktop / macos_app.APP_NAME
    assert shortcut.resolve() == app
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["LSUIElement"] is True
    assert macos_app.BUNDLE_ID == "geekmagic-monitor"
    assert info["CFBundleIdentifier"] == macos_app.BUNDLE_ID
    assert info["CFBundleExecutable"] == macos_app.BUNDLE_ID
    assert (app / "Contents/MacOS" / info["CFBundleExecutable"]).stat().st_mode & 0o111
    assert (app / "Contents/Resources/monitor.icns").is_file()

    assert macos_app.install_app(project, applications, desktop) == app
    macos_app.uninstall_app(applications, desktop)
    macos_app.uninstall_app(applications, desktop)
    assert not app.exists()
    assert not shortcut.is_symlink()
    assert settings.is_file()


def test_install_migrates_legacy_bundle_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    applications = tmp_path / "Applications"
    desktop = tmp_path / "Desktop"
    app = applications / macos_app.APP_NAME
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "local.geekmagic.ai-usage-monitor"}, stream)

    assert macos_app.install_app(project, applications, desktop) == app
    with (contents / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleIdentifier"] == "geekmagic-monitor"


def test_install_and_uninstall_reject_unrelated_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    applications = tmp_path / "Applications"
    desktop = tmp_path / "Desktop"
    app = applications / macos_app.APP_NAME
    app.mkdir(parents=True)
    marker = app / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unrelated app"):
        macos_app.install_app(project, applications, desktop)
    with pytest.raises(RuntimeError, match="unrelated app"):
        macos_app.uninstall_app(applications, desktop)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_install_preserves_unrelated_desktop_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    applications = tmp_path / "Applications"
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    shortcut = desktop / macos_app.APP_NAME
    shortcut.write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unrelated desktop item"):
        macos_app.install_app(project, applications, desktop)
    assert shortcut.read_text(encoding="utf-8") == "keep"
    assert not (applications / macos_app.APP_NAME).exists()
