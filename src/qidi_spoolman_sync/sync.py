from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .filas import FilasData, normalize_material, pick_color_key, pick_filament_index
from .spoolman import Spool

PRINTING_STATES = {"printing", "paused"}


@dataclass
class SyncResult:
    commands: list[str] = field(default_factory=list)
    new_state: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def resolve_slot_spools(
    spools: list[Spool], slot_locations: list[str]
) -> tuple[dict[int, Spool | None], list[int], list[str]]:
    """Returns (slot -> resolved spool or None, conflicted slot indices, warnings)."""
    by_location: dict[str, list[Spool]] = {}
    for spool in spools:
        if spool.location:
            by_location.setdefault(spool.location, []).append(spool)

    resolved: dict[int, Spool | None] = {}
    conflicts: list[int] = []
    warnings: list[str] = []

    for idx, location in enumerate(slot_locations):
        matches = by_location.get(location.strip(), [])
        if len(matches) == 0:
            resolved[idx] = None
        elif len(matches) == 1:
            resolved[idx] = matches[0]
        else:
            resolved[idx] = None
            conflicts.append(idx)
            ids = ", ".join(str(s.id) for s in matches)
            warnings.append(f"slot {idx}: location conflict, multiple spools ({ids}) in '{location}'")

    return resolved, conflicts, warnings


def run_sync_cycle(
    spools: list[Spool],
    printer_state: dict[str, Any],
    state: dict[str, Any],
    filas_data: FilasData,
    config: Config,
) -> SyncResult:
    result = SyncResult(new_state={"slots": dict(state.get("slots", {}))})

    variables = printer_state.get("save_variables", {}).get("variables", {})
    print_status = printer_state.get("print_stats", {}).get("state", "")
    is_printing = print_status in PRINTING_STATES

    resolved, conflicts, conflict_warnings = resolve_slot_spools(spools, config.slot_locations)
    result.warnings.extend(conflict_warnings)

    stored_slots: dict[str, Any] = result.new_state["slots"]

    for idx in range(len(config.slot_locations)):
        key = str(idx)

        if idx in conflicts:
            continue  # no writes at all for this slot this cycle

        desired_spool = resolved[idx]
        printer_spool_id = int(variables.get(f"spool_slot{idx}", 0) or 0)
        desired_spool_id = desired_spool.id if desired_spool else 0
        mapping_changed = printer_spool_id != desired_spool_id

        loaded_flag = variables.get(f"slot{idx}")
        if desired_spool is not None and loaded_flag == 0:
            result.warnings.append(
                f"slot {idx}: Spoolman expects spool {desired_spool.id} here but nothing is loaded"
            )

        if mapping_changed:
            result.commands.append(f"SET_SLOT_SPOOL SLOT={idx} SPOOL={desired_spool_id}")

        stored = stored_slots.get(key)

        if desired_spool is None:
            if mapping_changed:
                result.info.append(f"slot {idx}: spool {printer_spool_id} -> 0 (empty)")
            stored_slots[key] = {"spool_id": 0, "material": None, "color_hex": None}
            continue

        material = normalize_material(desired_spool.material or "", config.material_aliases)
        color_hex = desired_spool.color_hex
        desired_tuple = {"spool_id": desired_spool.id, "material": material, "color_hex": color_hex}

        first_run_slot = stored is None
        tuple_changed = stored is None or (
            stored.get("spool_id"),
            stored.get("material"),
            stored.get("color_hex"),
        ) != (desired_tuple["spool_id"], desired_tuple["material"], desired_tuple["color_hex"])

        if first_run_slot and not mapping_changed:
            # Baseline: trust that the printer's existing filament info is already correct.
            stored_slots[key] = desired_tuple
            continue

        if not tuple_changed:
            continue

        if is_printing and config.defer_while_printing:
            result.info.append(f"slot {idx}: filament info write deferred (printer is {print_status})")
            continue

        fila_index = pick_filament_index(material, filas_data.filas, config.material_aliases)
        if fila_index is None:
            result.warnings.append(f"slot {idx}: no [filaN] entry found for material '{material}'")
            continue

        color_result = pick_color_key(color_hex, filas_data.colordict)

        commands = [
            f"SAVE_VARIABLE VARIABLE=filament_slot{idx} VALUE={fila_index}",
            f"SAVE_VARIABLE VARIABLE=vendor_slot{idx} VALUE=0",
        ]
        log_suffix = f"filament {fila_index} ({filas_data.filas[fila_index].filament}), vendor 0"
        if color_result is not None:
            color_key, delta_e = color_result
            commands.append(f"SAVE_VARIABLE VARIABLE=color_slot{idx} VALUE={color_key}")
            log_suffix += f", color {color_key} (ΔE {delta_e:.1f})"

        result.commands.extend(commands)
        result.info.append(
            f"slot {idx}: spool {printer_spool_id} -> {desired_spool.id} | {log_suffix}"
        )
        stored_slots[key] = desired_tuple

    return result
