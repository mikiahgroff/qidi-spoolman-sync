from __future__ import annotations

import configparser
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RELOAD_INTERVAL_SECONDS = 10 * 60


@dataclass(frozen=True)
class FilaEntry:
    index: int
    filament: str
    type: str
    min_temp: int | None = None
    max_temp: int | None = None
    box_min_temp: int | None = None
    box_max_temp: int | None = None


@dataclass(frozen=True)
class FilasData:
    filas: dict[int, FilaEntry]
    colordict: dict[int, str]  # value: upper-case hex, no '#'
    vendor_list: dict[int, str]


def parse_filas_list(text: str) -> FilasData:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve key case
    parser.read_string(text)

    filas: dict[int, FilaEntry] = {}
    colordict: dict[int, str] = {}
    vendor_list: dict[int, str] = {}

    for section in parser.sections():
        if section.startswith("fila"):
            try:
                index = int(section[len("fila") :])
            except ValueError:
                continue
            data = parser[section]
            filament = data.get("filament", "").strip()
            type_ = data.get("type", "").strip()
            if not filament or not type_:
                continue
            filas[index] = FilaEntry(
                index=index,
                filament=filament,
                type=type_,
                min_temp=_int_or_none(data.get("min_temp")),
                max_temp=_int_or_none(data.get("max_temp")),
                box_min_temp=_int_or_none(data.get("box_min_temp")),
                box_max_temp=_int_or_none(data.get("box_max_temp")),
            )
        elif section == "colordict":
            for key, value in parser.items(section):
                try:
                    colordict[int(key)] = value.strip().lstrip("#").upper()
                except ValueError:
                    continue
        elif section == "vendor_list":
            for key, value in parser.items(section):
                try:
                    vendor_list[int(key)] = value.strip()
                except ValueError:
                    continue

    if vendor_list.get(0, "").strip().lower() != "generic":
        logger.error(
            "vendor_list[0] is %r, expected 'Generic' — vendor mapping assumption may be wrong",
            vendor_list.get(0),
        )

    return FilasData(filas=filas, colordict=colordict, vendor_list=vendor_list)


def _int_or_none(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def normalize_material(material: str, aliases: dict[str, str]) -> str:
    normalized = material.strip().upper()
    for alias, target in aliases.items():
        if alias.strip().upper() == normalized:
            return target.strip().upper()
    return normalized


def pick_filament_index(material: str, filas: dict[int, FilaEntry], aliases: dict[str, str]) -> int | None:
    """Pick the best [filaN] match for a Spoolman material. See SPEC.md 2.4."""
    normalized = normalize_material(material, aliases)

    candidates = [entry for entry in filas.values() if entry.type.strip().upper() == normalized]
    if not candidates:
        return None

    def sort_key(entry: FilaEntry) -> tuple[int, int, int]:
        is_basic = 0 if "basic" in entry.filament.lower() else 1
        exact_name = 0 if entry.filament.strip().upper() == normalized else 1
        return (is_basic, exact_name, entry.index)

    best = min(candidates, key=sort_key)
    return best.index


def _srgb_to_lab(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def to_linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = to_linear(r), to_linear(g), to_linear(b)

    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    xn, yn, zn = 0.95047, 1.0, 1.08883
    x, y, z = x / xn, y / yn, z / zn

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else (1 / 3) * (29 / 6) ** 2 * t + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return (L, a, bb)


def delta_e_cie76(hex_a: str, hex_b: str) -> float:
    l1, a1, b1 = _srgb_to_lab(hex_a)
    l2, a2, b2 = _srgb_to_lab(hex_b)
    return ((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5


def pick_color_key(color_hex: str | None, colordict: dict[int, str]) -> tuple[int, float] | None:
    """Pick the nearest [colordict] entry by CIE76 Delta E. See SPEC.md 2.5."""
    if not color_hex or not colordict:
        return None

    best_key: int | None = None
    best_delta = float("inf")
    for key in sorted(colordict):
        delta = delta_e_cie76(color_hex, colordict[key])
        if delta < best_delta:
            best_delta = delta
            best_key = key

    if best_key is None:
        return None
    return (best_key, best_delta)


class FilasCache:
    """Fetches and parses officiall_filas_list.cfg, reloading at most every 10 minutes."""

    def __init__(self, fetch_text: Callable[[], str], reload_interval: float = RELOAD_INTERVAL_SECONDS):
        self._fetch_text = fetch_text
        self._reload_interval = reload_interval
        self._cached: FilasData | None = None
        self._fetched_at: float = -float("inf")

    def get(self) -> FilasData:
        now = time.monotonic()
        if self._cached is None or (now - self._fetched_at) >= self._reload_interval:
            text = self._fetch_text()
            self._cached = parse_filas_list(text)
            self._fetched_at = now
        return self._cached
