from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DEFAULT_SLOT_LOCATIONS = [
    "QIDI Box Slot 1",
    "QIDI Box Slot 2",
    "QIDI Box Slot 3",
    "QIDI Box Slot 4",
]

DEFAULT_MATERIAL_ALIASES = {
    "PLA+": "PLA",
    "PLA PLUS": "PLA",
    "PETG+": "PETG",
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    spoolman_url: str
    moonraker_url: str
    moonraker_api_key: str = ""
    slot_locations: list[str] = field(default_factory=lambda: list(DEFAULT_SLOT_LOCATIONS))
    poll_interval: int = 30
    defer_while_printing: bool = True
    material_aliases: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MATERIAL_ALIASES))
    state_file: str = "/data/state.json"
    dry_run: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env

        spoolman_url = env.get("SPOOLMAN_URL")
        moonraker_url = env.get("MOONRAKER_URL")
        if not spoolman_url:
            raise ConfigError("SPOOLMAN_URL is required")
        if not moonraker_url:
            raise ConfigError("MOONRAKER_URL is required")

        slot_locations_raw = env.get("SLOT_LOCATIONS")
        slot_locations = (
            [s.strip() for s in slot_locations_raw.split(",")]
            if slot_locations_raw
            else list(DEFAULT_SLOT_LOCATIONS)
        )

        material_aliases_raw = env.get("MATERIAL_ALIASES")
        if material_aliases_raw:
            try:
                material_aliases = json.loads(material_aliases_raw)
            except json.JSONDecodeError as e:
                raise ConfigError(f"MATERIAL_ALIASES is not valid JSON: {e}") from e
        else:
            material_aliases = dict(DEFAULT_MATERIAL_ALIASES)

        return cls(
            spoolman_url=spoolman_url.rstrip("/"),
            moonraker_url=moonraker_url.rstrip("/"),
            moonraker_api_key=env.get("MOONRAKER_API_KEY", ""),
            slot_locations=slot_locations,
            poll_interval=int(env.get("POLL_INTERVAL", 30)),
            defer_while_printing=_parse_bool(env.get("DEFER_WHILE_PRINTING", "true")),
            material_aliases=material_aliases,
            state_file=env.get("STATE_FILE", "/data/state.json"),
            dry_run=_parse_bool(env.get("DRY_RUN", "false")),
            log_level=env.get("LOG_LEVEL", "INFO"),
        )


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")
