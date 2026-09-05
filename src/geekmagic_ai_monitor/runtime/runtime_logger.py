"""Console and rotating-file logger for unattended monitor execution."""

from __future__ import annotations

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType


class RuntimeLogger:
    """Callable logger that owns and closes its handlers deterministically."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 1_000_000,
        backup_count: int = 5,
        console: bool = True,
        today: date | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero.")
        if backup_count < 0:
            raise ValueError("backup_count must not be negative.")

        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _retain_today_entries(
            self.path,
            today=today or date.today(),
            backup_count=backup_count,
        )
        self._logger = logging.Logger(
            f"geekmagic_ai_monitor.runtime.{id(self)}",
            level=logging.INFO,
        )
        self._logger.propagate = False
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            self.path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)

    def __call__(self, message: str) -> None:
        self._logger.info(message)

    def close(self) -> None:
        for handler in tuple(self._logger.handlers):
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)

    def __enter__(self) -> RuntimeLogger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _retain_today_entries(path: Path, *, today: date, backup_count: int) -> None:
    """Consolidate today's log lines and discard entries from earlier dates."""
    backups = tuple(Path(f"{path}.{index}") for index in range(backup_count, 0, -1))
    sources = (*backups, path)
    if not any(source.is_file() for source in sources):
        return

    date_prefix = f"{today:%Y-%m-%d} "
    retained_lines: list[str] = []
    for source in sources:
        if not source.is_file():
            continue
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(date_prefix):
                retained_lines.append(f"{line}\n")

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(retained_lines), encoding="utf-8")
    temporary.replace(path)
    for backup in backups:
        backup.unlink(missing_ok=True)
