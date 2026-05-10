from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rust_sensei.constants import LOG_DIR_NAME
from rust_sensei.errors import RustSenseiError

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(state_dir: Path) -> Path:
    log_dir = state_dir / LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("rust_sensei")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_file = log_dir / "rust-sensei.log"
    if not _has_file_handler(logger, log_file):
        handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=True,
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    return log_dir


def log_boundary_exception(logger: logging.Logger, exc: Exception) -> None:
    if isinstance(exc, RustSenseiError):
        level = logging.ERROR if exc.envelope.retryable else logging.WARNING
        logger.log(
            level,
            "Request failed: %s",
            exc.envelope.to_dict(),
            exc_info=True,
        )
        return

    logger.exception("Unexpected request failure")


def _has_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    return any(
        isinstance(handler, TimedRotatingFileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    )
