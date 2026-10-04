from pathlib import Path

from qidi_spoolman_sync.filas import (
    normalize_material,
    parse_filas_list,
    pick_color_key,
    pick_filament_index,
)

FIXTURES = Path(__file__).parent / "fixtures"
ALIASES = {"PLA+": "PLA", "PLA PLUS": "PLA", "PETG+": "PETG"}


def load_filas():
    text = (FIXTURES / "officiall_filas_list.cfg").read_text()
    return parse_filas_list(text)


def test_parsing_tolerates_empty_fila_sections():
    data = load_filas()
    assert 3 not in data.filas
    assert 6 not in data.filas
    assert 8 not in data.filas
    assert 7 in data.filas
    assert data.filas[7].filament == "PLA Basic"


def test_vendor_list_and_colordict_parsed():
    data = load_filas()
    assert data.vendor_list[0] == "Generic"
    assert data.vendor_list[1] == "QIDI"
    assert data.colordict[20] == "A3A3A0"


def test_filament_tiebreak_pla_prefers_basic():
    data = load_filas()
    assert pick_filament_index("PLA", data.filas, ALIASES) == 7


def test_filament_tiebreak_petg_prefers_basic():
    data = load_filas()
    assert pick_filament_index("PETG", data.filas, ALIASES) == 39


def test_filament_tiebreak_abs_single_candidate():
    data = load_filas()
    assert pick_filament_index("ABS", data.filas, ALIASES) == 11


def test_filament_alias_pla_plus_maps_to_pla_basic():
    data = load_filas()
    assert pick_filament_index("PLA+", data.filas, ALIASES) == 7


def test_filament_unknown_material_returns_none():
    data = load_filas()
    assert pick_filament_index("NYLON", data.filas, ALIASES) is None


def test_normalize_material_trims_and_upcases():
    assert normalize_material("  pla  ", ALIASES) == "PLA"


def test_normalize_material_applies_alias():
    assert normalize_material("petg+", ALIASES) == "PETG"


def test_nearest_color_exact_match_against_real_colordict():
    data = load_filas()
    key, delta = pick_color_key("A3A3A0", data.colordict)
    assert key == 20
    assert delta == 0.0


def test_nearest_color_picks_closest_not_exact():
    data = load_filas()
    # Slightly off gray should still land on the gray entry (key 20), not black/white.
    key, _ = pick_color_key("A0A09D", data.colordict)
    assert key == 20


def test_nearest_color_no_color_returns_none():
    data = load_filas()
    assert pick_color_key(None, data.colordict) is None
