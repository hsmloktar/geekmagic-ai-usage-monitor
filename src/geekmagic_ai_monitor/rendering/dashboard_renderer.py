"""Render an AI usage snapshot as a 240x240 JPEG dashboard."""

from __future__ import annotations

from datetime import datetime, tzinfo
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from geekmagic_ai_monitor.usage import AiUsageSnapshot, UsageInfo


class DashboardRenderer:
    """Pure renderer: its only input is an AiUsageSnapshot."""

    width = 240
    height = 240

    def render(self, snapshot: AiUsageSnapshot) -> bytes:
        image = Image.new("RGB", (self.width, self.height), "#07101d")
        draw = ImageDraw.Draw(image)

        header_font = ImageFont.load_default(size=18)
        section_font = ImageFont.load_default(size=16)
        label_font = ImageFont.load_default(size=13)
        value_font = ImageFont.load_default(size=15)
        footer_font = ImageFont.load_default(size=12)

        draw.text((12, 10), "AI USAGE", font=header_font, fill="#f8fafc")
        _draw_right(draw, "USED", 178, 13, label_font, "#64748b")
        _draw_right(
            draw,
            snapshot.source_device.upper()[:6],
            228,
            10,
            header_font,
            "#2dd4bf",
        )
        draw.line((12, 36, 228, 36), fill="#1e3a52", width=1)
        display_timezone = snapshot.updated_at.tzinfo
        assert display_timezone is not None

        self._draw_provider(
            draw,
            name="CODEX",
            usage=snapshot.codex,
            top=43,
            accent="#22d3ee",
            section_font=section_font,
            label_font=label_font,
            value_font=value_font,
            display_timezone=display_timezone,
        )
        self._draw_provider(
            draw,
            name="CLAUDE",
            usage=snapshot.claude,
            top=124,
            accent="#f59e0b",
            section_font=section_font,
            label_font=label_font,
            value_font=value_font,
            display_timezone=display_timezone,
        )

        draw.line((12, 208, 228, 208), fill="#1e3a52", width=1)
        footer_text = f"Updated {snapshot.updated_at.astimezone():%H:%M}"
        draw.text((12, 216), footer_text, font=footer_font, fill="#94a3b8")
        _draw_right(draw, "Last push wins", 228, 216, footer_font, "#475569")

        output = BytesIO()
        image.save(output, format="JPEG", quality=90, subsampling=0, optimize=True)
        return output.getvalue()

    def _draw_provider(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        name: str,
        usage: UsageInfo,
        top: int,
        accent: str,
        section_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
        label_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
        value_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
        display_timezone: tzinfo,
    ) -> None:
        draw.rounded_rectangle(
            (8, top - 3, 232, top + 72),
            radius=9,
            fill="#0b1929",
            outline="#162b3f",
            width=1,
        )
        draw.rectangle((14, top + 3, 17, top + 17), fill=accent)
        draw.text((23, top), name, font=section_font, fill="#e2e8f0")
        _draw_right(
            draw,
            _format_reset_schedule(
                usage.five_hour_reset_at,
                usage.weekly_reset_at,
                display_timezone,
            ),
            222,
            top + 2,
            label_font,
            "#94a3b8",
        )

        _draw_usage_row(
            draw,
            label="5H",
            percent=usage.five_hour_used_percent,
            y=top + 29,
            accent=accent,
            label_font=label_font,
            value_font=value_font,
        )
        _draw_usage_row(
            draw,
            label="WK",
            percent=usage.weekly_used_percent,
            y=top + 52,
            accent=accent,
            label_font=label_font,
            value_font=value_font,
        )


def _draw_usage_row(
    draw: ImageDraw.ImageDraw,
    *,
    label: str,
    percent: float | None,
    y: int,
    accent: str,
    label_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    value_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    draw.text((17, y - 3), label, font=label_font, fill="#94a3b8")
    bar_left = 48
    bar_top = y
    bar_width = 125
    bar_height = 10
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_left + bar_width, bar_top + bar_height),
        radius=5,
        fill="#1e293b",
    )

    if percent is None:
        _draw_right(draw, _format_percent_label(percent), 222, y - 5, value_font, "#64748b")
        return

    fill_width = round(bar_width * percent / 100)
    if fill_width > 0:
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_left + fill_width, bar_top + bar_height),
            radius=min(5, max(1, fill_width // 2)),
            fill=accent,
        )
    _draw_right(draw, _format_percent_label(percent), 222, y - 5, value_font, "#f8fafc")


def _format_percent_label(percent: float | None) -> str:
    """Format a usage value without pretending a missing limit is zero percent."""
    return f"{percent:.0f}%" if percent is not None else "None"


def _draw_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    right: int,
    y: int,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    draw.text((right - width, y), text, font=font, fill=fill)


def _format_reset_schedule(
    five_hour_reset_at: datetime | None,
    weekly_reset_at: datetime | None,
    display_timezone: tzinfo,
) -> str:
    five_hour = (
        five_hour_reset_at.astimezone(display_timezone).strftime("%H:%M")
        if five_hour_reset_at is not None
        else "--:--"
    )
    weekly = (
        weekly_reset_at.astimezone(display_timezone).strftime("%m/%d")
        if weekly_reset_at is not None
        else "--/--"
    )
    return f"{five_hour} · W {weekly}"
