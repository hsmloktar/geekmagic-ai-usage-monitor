"""Cross-platform process lock used to prevent duplicate monitor loops."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from filelock import FileLock, Timeout


class AlreadyRunningError(RuntimeError):
    """Raised when another monitor process already owns the runtime lock."""


class SingleInstanceLock:
    """Hold an OS-backed non-blocking file lock for the process lifetime."""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._lock = FileLock(self._path)
        self._acquired = False

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> SingleInstanceLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock.acquire(timeout=0)
        except Timeout as error:
            raise AlreadyRunningError(
                f"Another GeekMagic monitor is already running (lock: {self._path})."
            ) from error
        self._acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._acquired:
            self._lock.release()
            self._acquired = False
