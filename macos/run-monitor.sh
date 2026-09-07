#!/bin/bash
# Resolve every runtime path relative to this checkout, including when launched elsewhere.
set -euo pipefail

command_name=run
case "${1:-}" in
    --once) command_name=run-once ;;
    --help|-h)
        echo "Usage: $0 [--once]"
        echo "Run continuously (Ctrl+C to stop), or perform one update with --once."
        exit 0
        ;;
    "") ;;
    *) echo "Unknown argument: $1. Use --help for usage." >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    echo "Too many arguments. Use --help for usage." >&2
    exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv was not found on PATH. Install uv and open a new terminal before starting." >&2
    exit 1
fi

# Keep provider subprocesses in the project too, independent of the caller's directory.
cd -- "$project_root"
exec uv run --locked --project "$project_root" geekmagic-ai-monitor \
    --settings-dir "$project_root" \
    "$command_name" \
    --output "$project_root/artifacts/geekmagic-current.jpg" \
    --log-file "$project_root/artifacts/logs/monitor.log" \
    --lock-file "$project_root/artifacts/geekmagic-monitor.lock"
