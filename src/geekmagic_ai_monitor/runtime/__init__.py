"""Application update-loop and unattended-runtime boundary."""

from .runtime_logger import RuntimeLogger
from .single_instance import AlreadyRunningError, SingleInstanceLock
from .update_service import GeekMagicPusher, UpdateCycleResult, UpdateService

__all__ = [
    "AlreadyRunningError",
    "GeekMagicPusher",
    "RuntimeLogger",
    "SingleInstanceLock",
    "UpdateCycleResult",
    "UpdateService",
]
