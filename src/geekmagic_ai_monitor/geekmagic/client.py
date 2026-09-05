"""HTTP client for the GeekMagic SmallTV Ultra stock firmware."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import httpx

from geekmagic_ai_monitor.configuration import GeekMagicSettings


class GeekMagicProtocolError(RuntimeError):
    """Raised when a device response or operation violates the expected protocol."""


class FirmwareProfile(StrEnum):
    """Firmware profiles relevant to the stock Ultra upload flow."""

    STOCK_ULTRA = "stock-ultra"
    STOCK_ULTRA_COMPATIBLE = "stock-ultra-compatible"
    STOCK_PRO = "stock-pro"
    SD_PRO_COMMUNITY = "sd-pro-community"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FirmwareIdentity:
    """Result of a read-only firmware probe."""

    profile: FirmwareProfile
    model: str | None = None
    version: str | None = None
    detected_by: str | None = None

    @property
    def supports_stock_ultra_push(self) -> bool:
        return self.profile in {
            FirmwareProfile.STOCK_ULTRA,
            FirmwareProfile.STOCK_ULTRA_COMPATIBLE,
        }


class GeekMagicClient:
    """Minimal, guarded client for uploading a JPEG to stock Ultra firmware."""

    _SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:jpg|jpeg)$", re.IGNORECASE)

    def __init__(
        self,
        settings: GeekMagicSettings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )

    async def __aenter__(self) -> GeekMagicClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def probe(self) -> FirmwareIdentity:
        """Identify known firmware profiles using read-only endpoints."""
        version_data = await self._get_optional_json("/v.json")
        if version_data is not None:
            model = _optional_string(version_data.get("m"))
            version = _optional_string(version_data.get("v"))
            model_key = (model or "").lower()
            if "ultra" in model_key:
                return FirmwareIdentity(
                    FirmwareProfile.STOCK_ULTRA,
                    model=model,
                    version=version,
                    detected_by="/v.json",
                )
            if "pro" in model_key:
                return FirmwareIdentity(
                    FirmwareProfile.STOCK_PRO,
                    model=model,
                    version=version,
                    detected_by="/v.json",
                )

        if await self._get_optional_json("/.sys/app.json") is not None:
            return FirmwareIdentity(
                FirmwareProfile.STOCK_PRO,
                model="SmallTV Pro",
                detected_by="/.sys/app.json",
            )

        if await self._get_optional_json("/app.json") is not None:
            return FirmwareIdentity(
                FirmwareProfile.STOCK_ULTRA_COMPATIBLE,
                model="SmallTV Ultra compatible",
                detected_by="/app.json",
            )

        theme_data = await self._get_optional_json("/theme/list")
        if theme_data is not None and isinstance(theme_data.get("themes"), list):
            return FirmwareIdentity(
                FirmwareProfile.SD_PRO_COMMUNITY,
                model="SD_PRO community firmware",
                detected_by="/theme/list",
            )

        return FirmwareIdentity(FirmwareProfile.UNKNOWN)

    async def upload_and_display(
        self,
        jpeg_data: bytes,
        filename: str,
        *,
        identity: FirmwareIdentity | None = None,
    ) -> FirmwareIdentity:
        """Upload and display a JPEG only after stock Ultra has been identified."""
        current_identity = identity or await self.probe()
        if not current_identity.supports_stock_ultra_push:
            raise GeekMagicProtocolError(
                "Refusing to push: the device was not identified as stock SmallTV Ultra "
                f"(detected profile: {current_identity.profile})."
            )

        self._validate_image(jpeg_data, filename)
        response = await self._http_client.post(
            "/doUpload?dir=/image/",
            files={"file": (filename, jpeg_data, "image/jpeg")},
        )
        self._check_response(response, "image upload")

        await self._get_checked("/set?theme=3", "Photo Album theme selection")
        await self._get_checked(
            f"/set?img=/image/{filename}",
            f"image selection for {filename}",
        )
        return current_identity

    async def _get_optional_json(self, path: str) -> dict[str, object] | None:
        response = await self._http_client.get(path)
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        try:
            value = response.json()
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    async def _get_checked(self, path: str, action: str) -> None:
        response = await self._http_client.get(path)
        self._check_response(response, action)

    @staticmethod
    def _check_response(response: httpx.Response, action: str) -> None:
        response.raise_for_status()
        if response.text.strip().upper() == "FAIL":
            raise GeekMagicProtocolError(f"Device rejected {action}: FAIL")

    @classmethod
    def _validate_image(cls, jpeg_data: bytes, filename: str) -> None:
        if not cls._SAFE_FILE_NAME.fullmatch(filename):
            raise GeekMagicProtocolError(
                "Image filename must be a path-free ASCII .jpg or .jpeg filename."
            )
        if (
            len(jpeg_data) < 4
            or not jpeg_data.startswith(b"\xff\xd8")
            or not jpeg_data.endswith(b"\xff\xd9")
        ):
            raise GeekMagicProtocolError("Image data is not a complete JPEG file.")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
