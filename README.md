# qidi-spoolman-sync

Keeps a QIDI Q2 printer's QIDI Box slots in sync with [Spoolman](https://github.com/Donkie/Spoolman).

Set a spool's **location** in Spoolman to e.g. `QIDI Box Slot 1`, and this service tells the
printer (via Moonraker) which Spoolman spool is in that slot, and what filament type/color it
is, so the QIDI touchscreen and QIDI Studio show the right thing.

See [`SPEC.MD`](./SPEC.MD) for the full behavior spec.

## Requirements

- A QIDI Q2 with a QIDI Box, running stock firmware (Klipper + Moonraker).
- The printer-side macros in `SPEC.MD` §1.1, included from `printer.cfg`.
- Spoolman already connected to the printer in Moonraker, with spool **locations** matching
  the slot names you configure below (default `QIDI Box Slot 1`..`4`).

## Setup

1. Copy `.env.example` to `.env` and fill in your real `SPOOLMAN_URL` and `MOONRAKER_URL`
   (and `MOONRAKER_API_KEY` if your Moonraker instance requires one — otherwise this host's
   IP must be in Moonraker's `trusted_clients`). **`.env` is gitignored — never commit it.**
2. **Run with `DRY_RUN=true` first.** This logs exactly what it would send to the printer
   without sending anything. Check the logs match what you expect before flipping it off.
3. Add the macros from `SPEC.MD` §1.1 to a `spoolman.cfg` on the printer, included from
   `printer.cfg`, if they aren't there already.
4. `docker compose up -d --build` — or skip building locally and use the prebuilt image
   (see below).
5. Once you're confident, set `DRY_RUN=false` in `.env` and restart.

### Using the prebuilt image

CI publishes a multi-arch (amd64/arm64) image to GitHub Container Registry on every push to
`main` and on version tags:

```bash
docker pull ghcr.io/mikiahgroff/qidi-spoolman-sync:latest
```

To use it instead of building locally, swap `docker-compose.yml`'s `build: .` for:

```yaml
image: ghcr.io/mikiahgroff/qidi-spoolman-sync:latest
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `SPOOLMAN_URL` | — (required) | e.g. `http://spoolman:7912` |
| `MOONRAKER_URL` | — (required) | e.g. `http://192.168.1.50:7125` |
| `MOONRAKER_API_KEY` | empty | Sent as `X-Api-Key` if set. Otherwise the host must be in Moonraker `trusted_clients`. |
| `SLOT_LOCATIONS` | `QIDI Box Slot 1,…,QIDI Box Slot 4` | Comma-separated, index = printer slot |
| `POLL_INTERVAL` | `30` | seconds |
| `DEFER_WHILE_PRINTING` | `true` | Don't touch filament-info variables mid-print |
| `MATERIAL_ALIASES` | `{"PLA+": "PLA", "PLA PLUS": "PLA", "PETG+": "PETG"}` | JSON object |
| `STATE_FILE` | `/data/state.json` | Mount a volume at `/data` |
| `DRY_RUN` | `false` | Log the commands it would send, send nothing |
| `LOG_LEVEL` | `INFO` | |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Test fixtures in `tests/fixtures/` are synthetic examples shaped like a real
`officiall_filas_list.cfg` / `saved_variables.cfg`, covering the entries this project's mapping
logic depends on — not a dump of any specific printer.

## Out of scope

- Writing NFC tags, KlipperScreen, changing QIDI's own macros or `value_tN`.
- Pushing data back into Spoolman — locations are the source of truth.
- More than one printer.

## License

MIT — see [`LICENSE`](./LICENSE).
