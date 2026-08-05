#!/usr/bin/env python3
"""OLED compass-style display for steer-by-wire bench tests.

This script is meant to run on a Raspberry Pi with an SSD1306 OLED connected
over I2C at address 0x3C. It renders a compass-like needle plus the angle in
degrees, so later we can feed it with the AS5600 reading without changing the
display code.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from smbus2 import SMBus

WIDTH = 128
HEIGHT = 64
PAGES = HEIGHT // 8
I2C_BUS = 1
I2C_ADDR = 0x3C
AS5600_ADDR = 0x36
AS5600_STATUS_REG = 0x0B
AS5600_RAW_ANGLE_REG = 0x0C


def normalize_angle(angle_deg: float) -> float:
    return angle_deg % 360.0


@dataclass(frozen=True)
class CompassGeometry:
    center_x: int = 64
    center_y: int = 22
    needle_length: int = 24
    head_length: int = 10
    shaft_width: int = 6


@dataclass(frozen=True)
class AS5600Reading:
    raw_angle: int
    angle_deg: float
    magnet_detected: bool
    magnet_too_strong: bool
    magnet_too_weak: bool


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]
        )

    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


class SSD1306:
    def __init__(self, bus: SMBus, width: int = WIDTH, height: int = HEIGHT, addr: int = I2C_ADDR) -> None:
        self.bus = bus
        self.width = width
        self.height = height
        self.addr = addr

    def _cmds(self, *cmds: int) -> None:
        self.bus.write_i2c_block_data(self.addr, 0x00, list(cmds))

    def _data(self, data: list[int]) -> None:
        # Keep the transfer chunks small for a reliable first-stage bench test.
        for start in range(0, len(data), 16):
            self.bus.write_i2c_block_data(self.addr, 0x40, data[start : start + 16])

    def init(self) -> None:
        self._cmds(
            0xAE,        # display off
            0x20, 0x00,  # horizontal addressing mode
            0xB0,        # page 0
            0xC8,        # COM scan direction remapped
            0x00,        # low column
            0x10,        # high column
            0x40,        # start line
            0x81, 0xCF,  # contrast
            0xA1,        # segment remap
            0xA6,        # normal display
            0xA8, 0x3F,  # multiplex 1/64
            0xA4,        # output follows RAM content
            0xD3, 0x00,  # display offset
            0xD5, 0x80,  # clock divide
            0xD9, 0xF1,  # pre-charge
            0xDA, 0x12,  # com pins for 128x64
            0xDB, 0x40,  # VCOM detect
            0x8D, 0x14,  # charge pump on
            0xAF,        # display on
        )

    def show(self, image: Image.Image) -> None:
        if image.mode != "1":
            image = image.convert("1")
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))

        buf = [0x00] * (self.width * self.height // 8)
        pixels = image.load()
        index = 0
        for page in range(PAGES):
            for x in range(self.width):
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if pixels[x, y] != 0:
                        byte |= 1 << bit
                buf[index] = byte
                index += 1

        self._cmds(0x21, 0x00, self.width - 1, 0x22, 0x00, PAGES - 1)
        self._data(buf)

    def clear(self) -> None:
        self.show(Image.new("1", (self.width, self.height), 0))


class AS5600:
    def __init__(self, bus: SMBus, addr: int = AS5600_ADDR) -> None:
        self.bus = bus
        self.addr = addr

    def read_status(self) -> tuple[bool, bool, bool]:
        value = self.bus.read_byte_data(self.addr, AS5600_STATUS_REG)
        magnet_detected = bool(value & 0x20)
        magnet_too_strong = bool(value & 0x10)
        magnet_too_weak = bool(value & 0x08)
        return magnet_detected, magnet_too_strong, magnet_too_weak

    def read_raw_angle(self) -> int:
        # RAW ANGLE is a 12-bit value at 0x0C/0x0D.
        high, low = self.bus.read_i2c_block_data(self.addr, AS5600_RAW_ANGLE_REG, 2)
        return ((high & 0x0F) << 8) | low

    def read(self, offset_deg: float = 0.0) -> AS5600Reading:
        raw_angle = self.read_raw_angle()
        angle_deg = normalize_angle(raw_angle * 360.0 / 4096.0 - offset_deg)
        magnet_detected, magnet_too_strong, magnet_too_weak = self.read_status()
        return AS5600Reading(
            raw_angle=raw_angle,
            angle_deg=angle_deg,
            magnet_detected=magnet_detected,
            magnet_too_strong=magnet_too_strong,
            magnet_too_weak=magnet_too_weak,
        )


class OLEDCompass:
    def __init__(self, display: SSD1306) -> None:
        self.display = display
        self.font_small = load_font(10)
        self.font_regular = load_font(13)
        self.font_big = load_font(20, bold=True)
        self.geo = CompassGeometry()
        self._filtered_angle: float | None = None
        self._display_angle: float | None = None

    def _polar(self, angle_deg: float, radius: float) -> tuple[float, float]:
        rad = math.radians(angle_deg - 90.0)
        x = self.geo.center_x + radius * math.cos(rad)
        y = self.geo.center_y + radius * math.sin(rad)
        return x, y

    def _draw_tick(self, draw: ImageDraw.ImageDraw, angle_deg: float, inner: float, outer: float, width: int = 1) -> None:
        x1, y1 = self._polar(angle_deg, inner)
        x2, y2 = self._polar(angle_deg, outer)
        draw.line((x1, y1, x2, y2), fill=1, width=width)

    def _draw_needle(self, draw: ImageDraw.ImageDraw, angle_deg: float) -> None:
        # Draw a filled, single-piece arrow that feels closer to an icon than a compass.
        tip_x, tip_y = self._polar(angle_deg, self.geo.needle_length)
        left_base_x, left_base_y = self._polar(angle_deg + 155.0, 9)
        right_base_x, right_base_y = self._polar(angle_deg - 155.0, 9)
        tail_left_x, tail_left_y = self._polar(angle_deg + 180.0 + 25.0, 5)
        tail_right_x, tail_right_y = self._polar(angle_deg + 180.0 - 25.0, 5)

        draw.polygon(
            [
                (tip_x, tip_y),
                (left_base_x, left_base_y),
                (tail_left_x, tail_left_y),
                (tail_right_x, tail_right_y),
                (right_base_x, right_base_y),
            ],
            outline=1,
            fill=1,
        )

        center_x, center_y = self._polar(angle_deg + 180.0, 2)
        draw.ellipse((center_x - 1, center_y - 1, center_x + 1, center_y + 1), outline=1, fill=1)

    def render(self, angle_deg: float) -> Image.Image:
        angle_deg = normalize_angle(angle_deg)
        image = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((0, 0, WIDTH - 1, HEIGHT - 1), radius=4, outline=1)

        self._draw_needle(draw, angle_deg)
        draw.text((18, 45), f"{angle_deg:6.1f}°", font=self.font_big, fill=1)

        return image

    def show_angle(self, angle_deg: float) -> None:
        self.display.show(self.render(angle_deg))

    def demo(self, angles: list[float], delay_s: float, repeat: bool) -> None:
        while True:
            for angle in angles:
                self.show_angle(angle)
                time.sleep(delay_s)
            if not repeat:
                return

    def _smooth_angle(self, angle_deg: float, alpha: float) -> float:
        angle_deg = normalize_angle(angle_deg)
        if self._filtered_angle is None:
            self._filtered_angle = angle_deg
            return angle_deg

        # Smooth the shortest way around the circle so 359 -> 0 stays stable.
        delta = ((angle_deg - self._filtered_angle + 180.0) % 360.0) - 180.0
        self._filtered_angle = normalize_angle(self._filtered_angle + alpha * delta)
        return self._filtered_angle

    def _adaptive_alpha(self, delta_deg: float) -> float:
        delta_deg = abs(delta_deg)
        if delta_deg >= 20.0:
            return 0.85
        if delta_deg >= 8.0:
            return 0.60
        if delta_deg >= 3.0:
            return 0.35
        return 0.20

    def live(self, sensor: AS5600, offset_deg: float, delay_s: float) -> None:
        while True:
            try:
                reading = sensor.read(offset_deg=offset_deg)
                current = normalize_angle(reading.angle_deg)
                if self._display_angle is None:
                    self._display_angle = current
                else:
                    delta = ((current - self._display_angle + 180.0) % 360.0) - 180.0
                    alpha = self._adaptive_alpha(delta)
                    if abs(delta) < 0.4:
                        self._display_angle = current
                    else:
                        self._display_angle = normalize_angle(self._display_angle + alpha * delta)

                self._filtered_angle = self._display_angle
                self.show_angle(self._display_angle)
            except OSError:
                self.show_angle(0.0)

            time.sleep(delay_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a compass-style angle on the SSD1306 OLED.")
    parser.add_argument("--angle", type=float, help="Show one angle in degrees and hold it on screen.")
    parser.add_argument("--offset", type=float, default=0.0, help="Subtract this calibration offset before display.")
    parser.add_argument("--hold", type=float, default=4.0, help="Seconds to hold a single-angle screen.")
    parser.add_argument("--demo", action="store_true", help="Run a short demo sweep of angles.")
    parser.add_argument("--repeat", action="store_true", help="Repeat the demo sweep forever.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between demo frames.")
    parser.add_argument("--live-delay", type=float, default=0.05, help="Delay between live sensor updates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with SMBus(I2C_BUS) as bus:
        display = SSD1306(bus)
        display.init()
        compass = OLEDCompass(display)

        if args.angle is not None:
            compass.show_angle(args.angle - args.offset)
            time.sleep(args.hold)
            return

        if args.demo or args.angle is None:
            if not args.demo:
                sensor = AS5600(bus)
                compass.live(sensor, offset_deg=args.offset, delay_s=args.live_delay)
                return
            demo_angles = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
            compass.demo(demo_angles, args.delay, args.repeat)


if __name__ == "__main__":
    main()
