"""Command-line entry point for device and dashboard validation."""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
from datetime import datetime
from pathlib import Path

import httpx

from geekmagic_ai_monitor.configuration import AppSettings, ConfigurationError, load_app_settings
from geekmagic_ai_monitor.geekmagic import (
    FirmwareIdentity,
    GeekMagicClient,
    GeekMagicProtocolError,
)
from geekmagic_ai_monitor.rendering import DashboardRenderer, TestImageRenderer
from geekmagic_ai_monitor.runtime import (
    AlreadyRunningError,
    RuntimeLogger,
    SingleInstanceLock,
    UpdateService,
)
from geekmagic_ai_monitor.usage import (
    AiUsageSnapshot,
    ClaudeUsageError,
    ClaudeUsageProvider,
    CodexUsageError,
    CodexUsageProvider,
    UsageInfo,
    UsageProvider,
)

PHASE1_OUTPUT = Path("artifacts/geekmagic-phase1-test.jpg")
DASHBOARD_OUTPUT = Path("artifacts/geekmagic-dashboard-test.jpg")
CODEX_DASHBOARD_OUTPUT = Path("artifacts/geekmagic-codex-usage.jpg")
LIVE_DASHBOARD_OUTPUT = Path("artifacts/geekmagic-live-usage.jpg")
CURRENT_DASHBOARD_OUTPUT = Path("artifacts/geekmagic-current.jpg")
DEFAULT_LOG_FILE = Path("artifacts/logs/monitor.log")
DEFAULT_LOCK_FILE = Path("artifacts/geekmagic-monitor.lock")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GeekMagic AI Usage Monitor tools")
    parser.add_argument(
        "--settings-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing appsettings.json (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("probe", help="Read device identity without changing its state")

    render_parser = subparsers.add_parser(
        "render-test",
        help="Generate a local 240x240 test JPEG without contacting the device",
    )
    render_parser.add_argument("--output", type=Path, default=PHASE1_OUTPUT)

    push_parser = subparsers.add_parser(
        "push-test",
        help="Probe stock Ultra, then render, upload, and display a test JPEG",
    )
    push_parser.add_argument("--output", type=Path, default=PHASE1_OUTPUT)

    dashboard_parser = subparsers.add_parser(
        "render-dashboard-test",
        help="Render the Phase 2 dashboard with sample usage data",
    )
    dashboard_parser.add_argument("--output", type=Path, default=DASHBOARD_OUTPUT)

    push_dashboard_parser = subparsers.add_parser(
        "push-dashboard-test",
        help="Render sample usage data and push the dashboard to stock Ultra",
    )
    push_dashboard_parser.add_argument("--output", type=Path, default=DASHBOARD_OUTPUT)

    subparsers.add_parser(
        "codex-usage",
        help="Read current Codex usage from the locally authenticated Codex CLI",
    )

    render_codex_parser = subparsers.add_parser(
        "render-codex-usage",
        help="Read Codex usage and render a local dashboard (Claude is unavailable)",
    )
    render_codex_parser.add_argument("--output", type=Path, default=CODEX_DASHBOARD_OUTPUT)

    push_codex_parser = subparsers.add_parser(
        "push-codex-usage",
        help="Read Codex usage and push the dashboard to stock Ultra",
    )
    push_codex_parser.add_argument("--output", type=Path, default=CODEX_DASHBOARD_OUTPUT)

    subparsers.add_parser(
        "claude-usage",
        help="Read current Claude usage from the locally authenticated Claude Code CLI",
    )

    render_live_parser = subparsers.add_parser(
        "render-live-usage",
        help="Read Codex and Claude usage and render a local dashboard",
    )
    render_live_parser.add_argument("--output", type=Path, default=LIVE_DASHBOARD_OUTPUT)

    push_live_parser = subparsers.add_parser(
        "push-live-usage",
        help="Read Codex and Claude usage and push the dashboard to stock Ultra",
    )
    push_live_parser.add_argument("--output", type=Path, default=LIVE_DASHBOARD_OUTPUT)

    run_once_parser = subparsers.add_parser(
        "run-once",
        help="Run one complete provider, render, and device-push cycle",
    )
    run_once_parser.add_argument("--output", type=Path, default=CURRENT_DASHBOARD_OUTPUT)
    run_once_parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    run_once_parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the complete update cycle continuously at the configured interval",
    )
    run_parser.add_argument("--output", type=Path, default=CURRENT_DASHBOARD_OUTPUT)
    run_parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    run_parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 130
    except (
        ClaudeUsageError,
        CodexUsageError,
        ConfigurationError,
        GeekMagicProtocolError,
        AlreadyRunningError,
        httpx.HTTPError,
        OSError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


async def _run(args: argparse.Namespace) -> int:
    if args.command in {"render-test", "render-dashboard-test"}:
        image_data = _render_image(args.command)
        output = _write_image(args.output, image_data)
        print(f"Created 240x240 JPEG: {output}")
        return 0

    settings = load_app_settings(args.settings_dir)

    if args.command in {"codex-usage", "render-codex-usage", "push-codex-usage"}:
        usage = await CodexUsageProvider(settings.codex).get_usage()
        _print_codex_usage(usage)
        if args.command == "codex-usage":
            return 0

        image_data = DashboardRenderer().render(_codex_snapshot(usage))
        output = _write_image(args.output, image_data)
        if args.command == "render-codex-usage":
            print(f"Created 240x240 Codex dashboard: {output}")
            return 0

        await _push_image(settings, image_data, output)
        return 0

    if args.command == "claude-usage":
        usage = await ClaudeUsageProvider(settings.claude).get_usage()
        _print_provider_usage("Claude", usage)
        return 0

    if args.command in {"render-live-usage", "push-live-usage"}:
        codex, claude = await asyncio.gather(
            _read_provider_safely("Codex", CodexUsageProvider(settings.codex)),
            _read_provider_safely("Claude", ClaudeUsageProvider(settings.claude)),
        )
        image_data = DashboardRenderer().render(_live_snapshot(codex, claude))
        output = _write_image(args.output, image_data)
        if args.command == "render-live-usage":
            print(f"Created 240x240 live dashboard: {output}")
            return 0

        await _push_image(settings, image_data, output)
        return 0

    if args.command in {"run-once", "run"}:
        with SingleInstanceLock(args.lock_file), RuntimeLogger(args.log_file) as runtime_log:
            async with GeekMagicClient(settings.geekmagic) as client:
                service = UpdateService(
                    codex_provider=CodexUsageProvider(settings.codex),
                    claude_provider=ClaudeUsageProvider(settings.claude),
                    renderer=DashboardRenderer(),
                    device=client,
                    image_file_name=settings.geekmagic.image_file_name,
                    output_path=args.output,
                    update_interval_seconds=settings.update_interval_seconds,
                    source_device=_source_device(),
                    logger=runtime_log,
                )
                if args.command == "run-once":
                    await service.update_once()
                    return 0

                runtime_log(
                    f"Starting update loop every {settings.update_interval_seconds}s. "
                    "Press Ctrl+C to stop."
                )
                try:
                    await service.run()
                except asyncio.CancelledError:
                    runtime_log("Update loop stopping by user request.")
                    raise
                return 0

    async with GeekMagicClient(settings.geekmagic) as client:
        identity = await client.probe()
        _print_identity(identity)

        if args.command == "probe":
            return 0 if identity.supports_stock_ultra_push else 2

        image_data = _render_image(args.command)
        output = _write_image(args.output, image_data)
        image_data = output.read_bytes()
        await client.upload_and_display(
            image_data,
            settings.geekmagic.image_file_name,
            identity=identity,
        )
        print(f"Uploaded and selected /image/{settings.geekmagic.image_file_name}")
        print(f"Local test image: {output}")
        return 0


async def _push_image(settings: AppSettings, image_data: bytes, output: Path) -> None:
    async with GeekMagicClient(settings.geekmagic) as client:
        identity = await client.probe()
        _print_identity(identity)
        await client.upload_and_display(
            image_data,
            settings.geekmagic.image_file_name,
            identity=identity,
        )
    print(f"Uploaded and selected /image/{settings.geekmagic.image_file_name}")
    print(f"Local dashboard image: {output}")


async def _read_provider_safely(name: str, provider: UsageProvider) -> UsageInfo:
    try:
        usage = await provider.get_usage()
    except (ClaudeUsageError, CodexUsageError, OSError) as error:
        print(f"Warning: {name} usage is unavailable: {error}", file=sys.stderr)
        return UsageInfo()
    _print_provider_usage(name, usage)
    return usage


def _print_identity(identity: FirmwareIdentity) -> None:
    profile = identity.profile
    model = identity.model or "unknown"
    version = identity.version or "unknown"
    detected_by = identity.detected_by or "none"
    print(f"Detected profile={profile}, model={model}, version={version}, via={detected_by}")


def _render_image(command: str) -> bytes:
    if command in {"render-test", "push-test"}:
        return TestImageRenderer().render()
    return DashboardRenderer().render(_sample_snapshot())


def _write_image(output: Path, image_data: bytes) -> Path:
    resolved = output.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(image_data)
    return resolved


def _sample_snapshot() -> AiUsageSnapshot:
    return AiUsageSnapshot(
        codex=UsageInfo(five_hour_used_percent=72, weekly_used_percent=43),
        claude=UsageInfo(five_hour_used_percent=61, weekly_used_percent=37),
        updated_at=datetime.now().astimezone(),
        source_device=_source_device(),
    )


def _codex_snapshot(usage: UsageInfo) -> AiUsageSnapshot:
    return AiUsageSnapshot(
        codex=usage,
        claude=UsageInfo(),
        updated_at=datetime.now().astimezone(),
        source_device=_source_device(),
    )


def _live_snapshot(codex: UsageInfo, claude: UsageInfo) -> AiUsageSnapshot:
    return AiUsageSnapshot(
        codex=codex,
        claude=claude,
        updated_at=datetime.now().astimezone(),
        source_device=_source_device(),
    )


def _print_codex_usage(usage: UsageInfo) -> None:
    _print_provider_usage("Codex", usage)


def _print_provider_usage(name: str, usage: UsageInfo) -> None:
    print(
        f"{name} 5H: "
        f"{_format_percent(usage.five_hour_used_percent)}, "
        f"resets {_format_reset(usage.five_hour_reset_at)}"
    )
    print(
        f"{name} WK: "
        f"{_format_percent(usage.weekly_used_percent)}, "
        f"resets {_format_reset(usage.weekly_reset_at)}"
    )


def _format_percent(value: float | None) -> str:
    return f"{value:.0f}% used" if value is not None else "None"


def _format_reset(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M %z") if value is not None else "unknown"


def _source_device() -> str:
    system = platform.system()
    if system == "Windows":
        return "WIN"
    if system == "Darwin":
        return "MAC"
    return system.upper()[:6] or "UNKNOWN"


if __name__ == "__main__":
    raise SystemExit(main())
