#!/bin/bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if ! command -v uv >/dev/null 2>&1; then
    echo "uv was not found on PATH. Install uv and open a new terminal before installing." >&2
    exit 1
fi
exec uv run --locked --project "$project_root" python -m geekmagic_ai_monitor.macos_app \
    install --project-root "$project_root" "$@"
