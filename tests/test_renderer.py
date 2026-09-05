from io import BytesIO

from PIL import Image

from geekmagic_ai_monitor.rendering import TestImageRenderer


def test_renderer_creates_240_by_240_rgb_jpeg() -> None:
    data = TestImageRenderer().render(source_device="WIN")

    with Image.open(BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (240, 240)
