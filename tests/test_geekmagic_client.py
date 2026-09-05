import httpx
import pytest

from geekmagic_ai_monitor.configuration import GeekMagicSettings
from geekmagic_ai_monitor.geekmagic import (
    FirmwareIdentity,
    FirmwareProfile,
    GeekMagicClient,
    GeekMagicProtocolError,
)
from geekmagic_ai_monitor.rendering import TestImageRenderer


@pytest.mark.asyncio
async def test_probe_and_push_use_stock_ultra_protocol() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v.json":
            return httpx.Response(
                200,
                json={"m": "SmallTV-Ultra", "v": "Ultra-V9.0.51"},
            )
        return httpx.Response(200, text="OK")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://192.168.0.144",
    ) as http_client:
        client = GeekMagicClient(GeekMagicSettings("192.168.0.144"), http_client)
        identity = await client.probe()
        await client.upload_and_display(
            TestImageRenderer().render(source_device="WIN"),
            "phase1.jpg",
            identity=identity,
        )

    assert identity.profile is FirmwareProfile.STOCK_ULTRA
    assert identity.version == "Ultra-V9.0.51"
    assert [(request.method, request.url.path, request.url.query) for request in requests] == [
        ("GET", "/v.json", b""),
        ("POST", "/doUpload", b"dir=/image/"),
        ("GET", "/set", b"theme=3"),
        ("GET", "/set", b"img=/image/phase1.jpg"),
    ]
    upload_body = await requests[1].aread()
    assert b'name="file"' in upload_body
    assert b'filename="phase1.jpg"' in upload_body
    assert b"Content-Type: image/jpeg" in upload_body


@pytest.mark.asyncio
async def test_push_refuses_unknown_firmware() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text="OK"))
    async with httpx.AsyncClient(transport=transport, base_url="http://device") as http_client:
        client = GeekMagicClient(GeekMagicSettings("device"), http_client)

        with pytest.raises(GeekMagicProtocolError, match="Refusing to push"):
            await client.upload_and_display(
                TestImageRenderer().render(),
                "phase1.jpg",
                identity=FirmwareIdentity(FirmwareProfile.UNKNOWN),
            )
