# qidi-spoolman-sync — Specification

A small service that keeps a QIDI Q2 printer's QIDI Box slots in sync with Spoolman.
The user sets a spool's **location** in Spoolman to e.g. `QIDI Box Slot 1`; the service
tells the printer which Spoolman spool is in that slot (for usage tracking) and what
filament type/color it is (for the QIDI touchscreen and QIDI Studio).

Language: **Python 3.12**. Deployment: **Docker / docker-compose**, running in the user's
datacenter next to Spoolman.

---

## 1. Environment (already set up — do not change)

| Component | Details |
|---|---|
| Printer | QIDI Q2 with one QIDI Box (4 slots), stock QIDI firmware, Klipper + Moonraker |
| Printer host | Linux (`linaro-alip`), user `mks`, config dir `/home/mks/printer_data/config` |
| Moonraker | `http://<printer-ip>:7125` (also proxied on port 80). Already connected to Spoolman. |
| Spoolman | Runs in the datacenter, `http://<spoolman-host>:7912`, REST API under `/api/v1` |
| Web UI | Fluidd v1.30.4 (Spoolman card enabled) |

### 1.1 Printer-side macros (installed in `spoolman.cfg`, included from `printer.cfg`)

```
[gcode_macro SET_ACTIVE_SPOOL]
gcode:
  {% if params.ID %}
    {action_call_remote_method("spoolman_set_active_spool", spool_id=params.ID|int)}
  {% else %}
    {action_respond_info("Parameter 'ID' is required")}
  {% endif %}

[gcode_macro CLEAR_ACTIVE_SPOOL]
gcode:
  {action_call_remote_method("spoolman_set_active_spool", spool_id=None)}

[gcode_macro SET_SLOT_SPOOL]
description: Assign a Spoolman spool ID to a Box slot (0-15)
gcode:
  {% set slot = params.SLOT|int %}
  {% set spool = params.SPOOL|default(0)|int %}
  SAVE_VARIABLE VARIABLE=spool_slot{slot} VALUE={spool}
  {action_respond_info("Slot %d -> spool %d" % (slot, spool))}

[gcode_macro USE_SLOT]
description: Make the spool in a Box slot the active Spoolman spool
gcode:
  {% set slot = params.SLOT|int %}
  {% set svv = printer.save_variables.variables %}
  {% set spool = svv['spool_slot' ~ slot]|default(0)|int %}
  {% if spool > 0 %}
    SET_ACTIVE_SPOOL ID={spool}
  {% else %}
    CLEAR_ACTIVE_SPOOL
    {action_respond_info("No spool assigned to slot %d" % slot)}
  {% endif %}
```

The slicer (QIDI Studio) calls `USE_SLOT SLOT={initial_tool}` at print start and
`USE_SLOT SLOT={next_extruder}` on filament change. The service never calls `USE_SLOT`.

### 1.2 Printer save variables (`saved_variables.cfg`, `[save_variables]` is in `printer.cfg`)

Per slot `N` (0-based, 0–15 for up to 4 Boxes; `slot16` is likely the external spool holder):

| Variable | Owner | Meaning |
|---|---|---|
| `spool_slotN` | **ours** | Spoolman spool ID in that slot, `0` = none |
| `filament_slotN` | QIDI | Index into `[filaN]` sections of `officiall_filas_list.cfg` |
| `color_slotN` | QIDI | Key into `[colordict]` |
| `vendor_slotN` | QIDI | Key into `[vendor_list]` (0 = Generic, 1 = QIDI) |
| `slotN` | QIDI | 1 = filament loaded, 0 = empty. **Never write.** |
| `value_tN` | QIDI | Tool → slot mapping (`'slotN'`). **Never write.** |

Snapshot at time of writing (matches Spoolman):

| Box slot | filament / vendor / color | Meaning | Spoolman spool |
|---|---|---|---|
| Slot 1 (`slot0`) | 1 / 1 / 20 | QIDI PLA Rapido, gray | #3 Rapido Gray (QIDI Tech, PLA, `A3A3A0`) |
| Slot 2 (`slot1`) | 39 / 0 / 2 | Generic PETG Basic, black | #1 Black (Sunlu, PETG) |
| Slot 3 (`slot2`) | 39 / 0 / 1 | Generic PETG Basic, white | #2 White (Sunlu, PETG) |
| Slot 4 (`slot3`) | empty | | |

The Box's NFC reader overwrites `filament_/color_/vendor_slotN` when it reads a QIDI tag.

### 1.3 `officiall_filas_list.cfg` (QIDI's spelling)

INI-style. Sections `[fila1]`…`[fila50]` with keys `filament` (display name), `type`,
`min_temp`, `max_temp`, `box_min_temp`, `box_max_temp`. Some sections have empty
`filament`/`type` — ignore those. Also `[colordict]` (`N = #RRGGBB`) and `[vendor_list]`
(`N = Name`). Relevant entries:

```
fila1  PLA Rapido      PLA        fila11 ABS Rapido   ABS     fila39 PETG Basic        PETG
fila2  PLA Matte       PLA        fila18 ASA          ASA     fila40 PETG-Tough        PETG
fila4  PLA Silk        PLA        fila23 PC           PC      fila41 PETG Rapido       PETG
fila5  PLA-CF          PLA-CF     fila47 PVA          PVA     fila45 PETG Translucent  PETG
fila7  PLA Basic       PLA        fila50 TPU 95A-HF   TPU
```

Read this file **at runtime from the printer** via Moonraker
(`GET /server/files/config/officiall_filas_list.cfg`), cache it, and reload it at most
every 10 minutes. Real copies of this file and `saved_variables.cfg` go in
`tests/fixtures/` for tests.

---

## 2. Behavior

### 2.1 Slot ↔ location mapping

Spoolman location names are 1-based, printer slots are 0-based. Configured as an ordered
list (default `QIDI Box Slot 1,QIDI Box Slot 2,QIDI Box Slot 3,QIDI Box Slot 4`);
list index = printer slot number. Match location names **exactly** (after trimming
whitespace). Only non-archived spools count.

### 2.2 Sync cycle (every `POLL_INTERVAL` seconds, default 30)

1. **Fetch spools** from Spoolman: `GET /api/v1/spool` (non-archived). Filter by location
   locally. If Spoolman errors or is unreachable, **skip the whole cycle** — never treat
   a failed fetch as "all slots empty".
2. **Resolve each slot:**
   - 0 spools → desired spool `0`.
   - 1 spool → that spool.
   - 2+ spools → **conflict**: log a warning naming the spool IDs, make no writes for that
     slot this cycle.
3. **Fetch printer state:**
   `GET /printer/objects/query?save_variables&print_stats`. If unreachable, skip cycle.
4. **Spool mapping (always reconciled):** if printer `spool_slotN` ≠ desired spool ID,
   send `SET_SLOT_SPOOL SLOT=N SPOOL=<id>` (use `0` for empty). NFC never touches this
   variable, so comparing against the printer directly is safe.
5. **Filament info (edge-triggered only):** see 2.3.
6. Send all commands for the cycle in one `POST /printer/gcode/script` (newline-separated
   script). Update the state file only after the printer accepts the commands.

### 2.3 Filament info — write only on change (avoid fighting NFC)

Do **not** compare `filament_/color_/vendor_slotN` against the printer, because NFC may
legitimately change them to a more specific QIDI entry. Instead, keep a persisted state file
recording, per slot, what we last wrote: `{spool_id, material, color_hex}`.

Write filament info for slot N only when the desired `(spool_id, material, color_hex)`
differs from the stored tuple — i.e. a different spool was placed in the slot, or that
spool's material/color was edited in Spoolman.

- **First run (no state file):** don't write filament info for slots where the printer's
  `spool_slotN` already equals the desired spool. Write it only where the mapping also
  changes. Then save the baseline.
- **Empty slot:** set `spool_slotN = 0` only. Leave filament/color/vendor alone.
- **Printing or paused** (`print_stats.state` in `printing`, `paused`): defer filament-info
  writes until idle (the spool mapping can still be written). Configurable via
  `DEFER_WHILE_PRINTING` (default `true`).

Commands, all integers:

```
SAVE_VARIABLE VARIABLE=filament_slotN VALUE=<fila index>
SAVE_VARIABLE VARIABLE=vendor_slotN VALUE=0
SAVE_VARIABLE VARIABLE=color_slotN VALUE=<color key>
```

### 2.4 Filament mapping rule

- **Vendor:** always `0` (Generic). Verify that `vendor_list` key 0 is Generic at load and
  log an error if not.
- **Material:** Spoolman `spool.filament.material`, trimmed and upper-cased. Apply the
  `MATERIAL_ALIASES` map first (default: `PLA+ → PLA`, `PLA PLUS → PLA`, `PETG+ → PETG`).
- **Candidates:** `[filaN]` sections with non-empty `filament` and `type.upper() == material`.
- **Tiebreak:** (1) name contains `Basic` (case-insensitive); (2) `filament.upper() == material`;
  (3) lowest N. Expected results: PLA→7, PETG→39, ABS→11, ASA→18, PC→23, PVA→47, TPU→50.
- **No candidate:** log a warning and skip filament info for that slot. Still write the
  spool mapping.

### 2.5 Color mapping

- Source: `spool.filament.color_hex` (no `#`, may be null). For multi-color filaments use
  the first entry of `multi_color_hexes`.
- Pick the `[colordict]` entry with the smallest CIE76 ΔE (convert sRGB → Lab). Ties go
  to the lowest key.
- If there's no color, don't write `color_slotN`.

### 2.6 Warnings (log only, no writes)

- Spoolman says a spool is in slot N, but printer `slotN == 0` (nothing loaded).
- Location conflict (2.2).
- Unknown material (2.4).

---

## 3. Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `SPOOLMAN_URL` | — (required) | e.g. `http://spoolman:7912` |
| `MOONRAKER_URL` | — (required) | e.g. `http://192.168.1.50:7125` |
| `MOONRAKER_API_KEY` | empty | Sent as `X-Api-Key` if set. Otherwise the host must be in Moonraker `trusted_clients`. |
| `SLOT_LOCATIONS` | `QIDI Box Slot 1,…,QIDI Box Slot 4` | Comma-separated, index = slot |
| `POLL_INTERVAL` | `30` | seconds |
| `DEFER_WHILE_PRINTING` | `true` | |
| `MATERIAL_ALIASES` | see 2.4 | JSON object |
| `STATE_FILE` | `/data/state.json` | Mount a volume at `/data` |
| `DRY_RUN` | `false` | Log the commands it would send, send nothing |
| `LOG_LEVEL` | `INFO` | |

---

## 4. Logging and errors

- One concise log line per action, e.g.
  `slot 1: spool 3 -> 7 | filament 7 (PLA Basic), vendor 0, color 12 (ΔE 4.1)`.
- Network errors: log, retry next cycle, keep state unchanged. Use 10 s timeouts.
- Never crash the loop on a single bad spool or slot.
- Graceful shutdown on SIGTERM.

---

## 5. Project layout and deliverables

```
qidi-spoolman-sync/
  SPEC.md
  README.md              # setup, env vars, Moonraker auth note, dry-run first
  pyproject.toml         # deps: httpx; dev: pytest, respx
  Dockerfile             # python:3.12-slim, non-root user
  docker-compose.yml     # env_file: .env, volume for /data, restart: unless-stopped
  .env.example
  src/qidi_spoolman_sync/
    config.py            # env parsing
    spoolman.py          # Spoolman client
    moonraker.py         # Moonraker client (query vars, fetch file, send gcode)
    filas.py             # parse officiall_filas_list.cfg; filament + color mapping
    sync.py              # one sync cycle: pure decision logic + side effects separated
    state.py             # state file load/save (atomic write)
    main.py              # loop, signals
  tests/
    fixtures/officiall_filas_list.cfg   # real copy from printer
    fixtures/saved_variables.cfg        # real copy from printer
    test_filas.py
    test_sync.py
```

Keep the decision logic pure: a function taking (spools, printer vars, state, config)
and returning (commands, new state, warnings), so it's easy to test.

### Required tests

- Filament tiebreak for PLA, PETG, ABS, an alias (`PLA+`), and an unknown material.
- Nearest color, including `A3A3A0` against the real colordict.
- Parsing tolerates empty `[filaN]` sections.
- Location conflict → no writes for that slot.
- Spoolman fetch failure → no commands at all.
- **NFC scenario:** after a sync, the printer's `filament_slot0` changes to 1 (QIDI) while
  Spoolman is unchanged → no filament writes on the next cycle.
- Spool moved into a slot → mapping plus filament info written. Moved out → only
  `spool_slotN = 0`.
- First run baseline (2.3).
- Printing → filament info deferred, mapping still written.

---

## 6. Out of scope

- Writing NFC tags, KlipperScreen, changing QIDI's own macros or `value_tN`.
- Pushing data back into Spoolman (locations are the source of truth).
- More than one printer.

## 7. Notes

- A QIDI firmware update may overwrite `printer.cfg`, removing `[include spoolman.cfg]`.
  If `SET_SLOT_SPOOL` comes back as an unknown command, log a clear error pointing at that.
- Fluidd 1.30.x has a reported save-variable casing bug; keep all variable names
  lowercase.
- The first deployment should run with `DRY_RUN=true`.