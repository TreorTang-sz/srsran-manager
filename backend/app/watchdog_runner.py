"""Standalone watchdog entrypoint for the split systemd deployment:

    srsran-watchdog.service
        ExecStart=<venv>/bin/python -m app.watchdog_runner

Runs the watchdog engine + monitor loop WITHOUT the web layer. Status
is shared with srsran-manager.service through the SQLite kv_state
table. In dev (mock) mode this is not needed — everything runs in one
process via ``uvicorn app.main:app``.
"""
from __future__ import annotations

import logging
import signal
import time

from app.config import load_config
from app.runtime import build_runtime

logger = logging.getLogger("srsran.watchdog_runner")


def main() -> None:
    config = load_config()
    config.server.run_web = False
    runtime = build_runtime(config)
    runtime.start()
    logger.info("watchdog runner started (mode=%s, db=%s)",
                config.resolved_mode, config.database.path)

    stop = {"flag": False}

    def _stop(signum, frame):  # noqa: ANN001
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        while not stop["flag"]:
            time.sleep(1)
    finally:
        runtime.stop()
        logger.info("watchdog runner stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
