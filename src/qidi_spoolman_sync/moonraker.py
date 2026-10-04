from __future__ import annotations

from typing import Any

import httpx

TIMEOUT_SECONDS = 10.0
FILAS_LIST_PATH = "officiall_filas_list.cfg"


class MoonrakerError(Exception):
    pass


class UnknownCommandError(MoonrakerError):
    pass


class MoonrakerClient:
    def __init__(self, base_url: str, api_key: str = "", client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        headers = {"X-Api-Key": api_key} if api_key else {}
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, headers=headers)

    def get_printer_state(self) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"{self._base_url}/printer/objects/query",
                params={"save_variables": "", "print_stats": ""},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MoonrakerError(f"Failed to query printer state: {e}") from e
        return response.json()["result"]["status"]

    def get_filas_list_text(self) -> str:
        try:
            response = self._client.get(f"{self._base_url}/server/files/config/{FILAS_LIST_PATH}")
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MoonrakerError(f"Failed to fetch {FILAS_LIST_PATH}: {e}") from e
        return response.text

    def run_gcode_script(self, script: str) -> None:
        try:
            response = self._client.post(
                f"{self._base_url}/printer/gcode/script",
                json={"script": script},
            )
        except httpx.HTTPError as e:
            raise MoonrakerError(f"Failed to send gcode script: {e}") from e

        if response.status_code == 400 and "Unknown command" in response.text:
            raise UnknownCommandError(
                "Printer rejected a SET_SLOT_SPOOL command as unknown. "
                "Check that 'spoolman.cfg' is still included from printer.cfg "
                "(a QIDI firmware update may have removed it)."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MoonrakerError(f"Printer rejected gcode script: {e}") from e

    def close(self) -> None:
        self._client.close()
