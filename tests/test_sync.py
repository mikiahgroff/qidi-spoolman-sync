from pathlib import Path

from qidi_spoolman_sync.config import Config
from qidi_spoolman_sync.filas import parse_filas_list
from qidi_spoolman_sync.spoolman import Spool
from qidi_spoolman_sync.sync import run_sync_cycle

FIXTURES = Path(__file__).parent / "fixtures"


def load_filas():
    return parse_filas_list((FIXTURES / "officiall_filas_list.cfg").read_text())


def make_config(**overrides):
    defaults = dict(
        spoolman_url="http://spoolman.example:7912",
        moonraker_url="http://printer.example:7125",
    )
    defaults.update(overrides)
    return Config(**defaults)


def make_spool(id, location, material="PLA", color_hex="A3A3A0"):
    return Spool(id=id, location=location, material=material, color_hex=color_hex)


def printer_state(variables, print_state="standby"):
    return {
        "save_variables": {"variables": variables},
        "print_stats": {"state": print_state},
    }


def test_location_conflict_no_writes_for_that_slot():
    spools = [
        make_spool(1, "QIDI Box Slot 1"),
        make_spool(2, "QIDI Box Slot 1"),
    ]
    state = {"slots": {}}
    result = run_sync_cycle(spools, printer_state({}), state, load_filas(), make_config())

    assert result.commands == []
    assert any("conflict" in w for w in result.warnings)
    assert "0" not in result.new_state["slots"]


def test_nfc_scenario_no_filament_writes_after_nfc_changes_printer_vars():
    spools = [make_spool(3, "QIDI Box Slot 1", material="PLA", color_hex="A3A3A0")]
    state = {"slots": {"0": {"spool_id": 3, "material": "PLA", "color_hex": "A3A3A0"}}}
    # NFC overwrote filament_slot0 to a QIDI entry; spool_slot0 (ours) still matches.
    variables = {"spool_slot0": 3, "filament_slot0": 1, "color_slot0": 20, "vendor_slot0": 1}
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert result.commands == []


def test_spool_moved_into_slot_writes_mapping_and_filament():
    spools = [make_spool(7, "QIDI Box Slot 1", material="PLA", color_hex="A3A3A0")]
    state = {"slots": {}}
    variables = {"spool_slot0": 0}
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert "SET_SLOT_SPOOL SLOT=0 SPOOL=7" in result.commands
    assert "SAVE_VARIABLE VARIABLE=filament_slot0 VALUE=7" in result.commands
    assert "SAVE_VARIABLE VARIABLE=vendor_slot0 VALUE=0" in result.commands
    assert "SAVE_VARIABLE VARIABLE=color_slot0 VALUE=20" in result.commands
    assert result.new_state["slots"]["0"] == {"spool_id": 7, "material": "PLA", "color_hex": "A3A3A0"}


def test_spool_moved_out_only_writes_mapping_zero():
    spools = []  # nothing in that location anymore
    state = {"slots": {"0": {"spool_id": 3, "material": "PLA", "color_hex": "A3A3A0"}}}
    variables = {"spool_slot0": 3}
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert result.commands == ["SET_SLOT_SPOOL SLOT=0 SPOOL=0"]
    assert result.new_state["slots"]["0"] == {"spool_id": 0, "material": None, "color_hex": None}


def test_first_run_baseline_no_filament_write_when_mapping_already_matches():
    spools = [make_spool(3, "QIDI Box Slot 1", material="PLA", color_hex="A3A3A0")]
    state = {"slots": {}}  # no state file yet
    variables = {"spool_slot0": 3}  # printer already agrees
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert result.commands == []
    assert result.new_state["slots"]["0"] == {"spool_id": 3, "material": "PLA", "color_hex": "A3A3A0"}


def test_first_run_mapping_differs_writes_both():
    spools = [make_spool(9, "QIDI Box Slot 1", material="PLA", color_hex="A3A3A0")]
    state = {"slots": {}}
    variables = {"spool_slot0": 0}
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert "SET_SLOT_SPOOL SLOT=0 SPOOL=9" in result.commands
    assert "SAVE_VARIABLE VARIABLE=filament_slot0 VALUE=7" in result.commands


def test_printing_defers_filament_info_but_still_writes_mapping():
    spools = [make_spool(9, "QIDI Box Slot 1", material="PLA", color_hex="A3A3A0")]
    state = {"slots": {}}
    variables = {"spool_slot0": 0}
    result = run_sync_cycle(
        spools, printer_state(variables, print_state="printing"), state, load_filas(), make_config()
    )

    assert "SET_SLOT_SPOOL SLOT=0 SPOOL=9" in result.commands
    assert not any(c.startswith("SAVE_VARIABLE VARIABLE=filament_slot0") for c in result.commands)
    # state not updated yet, so it's written once idle on a later cycle
    assert "0" not in result.new_state["slots"]


def test_unknown_material_warns_and_skips_filament_but_keeps_mapping():
    spools = [make_spool(5, "QIDI Box Slot 1", material="NYLON", color_hex="A3A3A0")]
    state = {"slots": {}}
    variables = {"spool_slot0": 0}
    result = run_sync_cycle(spools, printer_state(variables), state, load_filas(), make_config())

    assert "SET_SLOT_SPOOL SLOT=0 SPOOL=5" in result.commands
    assert not any(c.startswith("SAVE_VARIABLE") for c in result.commands)
    assert any("no [filaN] entry" in w for w in result.warnings)


def test_spoolman_fetch_failure_results_in_no_commands_at_all():
    import httpx
    import respx

    from qidi_spoolman_sync.main import run_cycle
    from qidi_spoolman_sync.moonraker import MoonrakerClient
    from qidi_spoolman_sync.spoolman import SpoolmanClient
    from qidi_spoolman_sync.filas import FilasCache

    config = make_config()

    with respx.mock(base_url="http://spoolman.example:7912") as mock:
        mock.get("/api/v1/spool").mock(return_value=httpx.Response(500))
        spoolman = SpoolmanClient(config.spoolman_url)
        moonraker = MoonrakerClient(config.moonraker_url)
        calls = []
        moonraker.run_gcode_script = lambda script: calls.append(script)
        filas_cache = FilasCache(lambda: (FIXTURES / "officiall_filas_list.cfg").read_text())

        run_cycle(config, spoolman, moonraker, filas_cache)

        assert calls == []
