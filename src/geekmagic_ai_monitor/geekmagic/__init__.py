"""GeekMagic stock firmware communication boundary."""

from .client import (
    FirmwareIdentity,
    FirmwareProfile,
    GeekMagicClient,
    GeekMagicProtocolError,
)

__all__ = [
    "FirmwareIdentity",
    "FirmwareProfile",
    "GeekMagicClient",
    "GeekMagicProtocolError",
]
