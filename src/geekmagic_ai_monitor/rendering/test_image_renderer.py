"""Render a deterministic Phase 1 device test image."""

from __future__ import annotations

import platform
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


class TestImageRenderer:
    """Create a simple 240x240 JPEG used to validate the device pipeline."""

    width = 240
    height = 240

    def render(
        self,
        *,
        updated_at: datetime | None = None,
        source_device: str | None = None,
    ) -> bytes:
        timestamp = updated_at or datetime.now().astimezone()
        source = source_device or _source_device()

        image = Image.new("RGB", (self.width, self.height), "#08111f")
        draw = ImageDraw.Draw(image)
        title_font = ImageFont.load_default(size=23)
        body_font = ImageFont.load_default(size=18)
        small_font = ImageFont.load_default(size=14)

        draw.rounded_rectangle((12, 12, 227, 227), radius=14, outline="#2dd4bf", width=2)
        draw.rectangle((13, 13, 226, 52), fill="#0f2942")
        _draw_centered(draw, "GEEKMAGIC", 25, title_font, "#f8fafc")
        _draw_centered(draw, "PHASE 1", 78, title_font, "#2dd4bf")
        _draw_centered(draw, "240 x 240 JPEG", 119, body_font, "#cbd5e1")
        _draw_centered(draw, "UPLOAD TEST", 151, body_font, "#fbbf24")
        _draw_centered(
            draw,
            f"{source}  Updated {timestamp:%H:%M}",
            199,
            small_font,
            "#94a3b8",
        )

        output = BytesIO()
        image.save(output, format="JPEG", quality=90, subsampling=0, optimize=True)
        return output.getvalue()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=font)
    text_width = bounds[2] - bounds[0]
    draw.text(((240 - text_width) / 2, y), text, font=font, fill=fill)


def _source_device() -> str:
    system = platform.system()
    if system == "Windows":
        return "WIN"
    if system == "Darwin":
        return "MAC"
    return system.upper()[:6] or "UNKNOWN"
