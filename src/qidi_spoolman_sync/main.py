from __future__ import annotations

import logging
import signal
import threading

from .config import Config, ConfigError
from .filas import FilasCache
from .moonraker import MoonrakerClient, MoonrakerError, UnknownCommandError
from .spoolman import SpoolmanClient, SpoolmanError
from .state import load_state, save_state
from .sync import run_sync_cycle

logger = logging.getLogger("qidi_spoolman_sync")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run_cycle(
    config: Config,
    spoolman: SpoolmanClient,
    moonraker: MoonrakerClient,
    filas_cache: FilasCache,
) -> None:
    try:
        spools = spoolman.get_spools()
    except SpoolmanError as e:
        logger.warning("Skipping cycle: %s", e)
        return

    try:
        printer_state = moonraker.get_printer_state()
    except MoonrakerError as e:
        logger.warning("Skipping cycle: %s", e)
        return

    try:
        filas_data = filas_cache.get()
    except MoonrakerError as e:
        logger.warning("Skipping cycle: could not load filament list: %s", e)
        return

    state = load_state(config.state_file)
    result = run_sync_cycle(spools, printer_state, state, filas_data, config)

    for line in result.info:
        logger.info(line)
    for line in result.warnings:
        logger.warning(line)

    if not result.commands:
        return

    if config.dry_run:
        logger.info("DRY_RUN: would send: %s", " | ".join(result.commands))
        return

    try:
        moonraker.run_gcode_script("\n".join(result.commands))
    except UnknownCommandError as e:
        logger.error(str(e))
        return
    except MoonrakerError as e:
        logger.warning("Skipping state save, printer rejected commands: %s", e)
        return

    save_state(config.state_file, result.new_state)


def main() -> None:
    try:
        config = Config.from_env()
    except ConfigError as e:
        logging.basicConfig(level=logging.ERROR)
        logger.error(str(e))
        raise SystemExit(1) from e

    configure_logging(config.log_level)
    logger.info("Starting qidi-spoolman-sync (poll interval %ss, dry_run=%s)", config.poll_interval, config.dry_run)

    spoolman = SpoolmanClient(config.spoolman_url)
    moonraker = MoonrakerClient(config.moonraker_url, config.moonraker_api_key)
    filas_cache = FilasCache(moonraker.get_filas_list_text)

    stop_event = threading.Event()

    def handle_signal(signum, frame) -> None:
        logger.info("Received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while not stop_event.is_set():
            try:
                run_cycle(config, spoolman, moonraker, filas_cache)
            except Exception:
                logger.exception("Unhandled error in sync cycle, continuing")
            stop_event.wait(config.poll_interval)
    finally:
        spoolman.close()
        moonraker.close()


if __name__ == "__main__":
    main()
