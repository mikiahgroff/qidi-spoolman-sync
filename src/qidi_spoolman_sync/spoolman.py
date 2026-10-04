from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Spool:
    id: int
    location: str | None
    material: str | None
    color_hex: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Spool":
        filament = data.get("filament") or {}
        color_hex = filament.get("color_hex")
        if not color_hex:
            multi = filament.get("multi_color_hexes")
            if multi:
                color_hex = multi.split(",")[0].strip() if isinstance(multi, str) else multi[0]
        return cls(
            id=data["id"],
            location=(data.get("location") or "").strip() or None,
            material=filament.get("material"),
            color_hex=color_hex.lstrip("#").upper() if color_hex else None,
        )


class SpoolmanError(Exception):
    pass


class SpoolmanClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    def get_spools(self) -> list[Spool]:
        try:
            response = self._client.get(f"{self._base_url}/api/v1/spool")
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise SpoolmanError(f"Failed to fetch spools from Spoolman: {e}") from e

        spools = [Spool.from_api(item) for item in response.json() if not item.get("archived")]
        return spools

    def close(self) -> None:
        self._client.close()
