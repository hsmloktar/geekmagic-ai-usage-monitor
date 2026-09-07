#!/bin/bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec "$project_root/.venv/bin/python" -m geekmagic_ai_monitor.macos_app \
    uninstall --project-root "$project_root" "$@"
