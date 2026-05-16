from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rust_sensei.constants import LOG_DIR_NAME
from rust_sensei.errors import RustSenseiError

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(state_dir: Path) -> Path:
    logger = logging.getLogger("rust_sensei")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    log_dir = state_dir / LOG_DIR_NAME
    log_file = (log_dir / "rust-sensei.log").resolve(strict=False)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        if not _has_file_handler(logger, log_file):
            _remove_file_handlers(logger)
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
            handler._rust_sensei_file_handler = True
            logger.addHandler(handler)
    except OSError:
        _ensure_stderr_handler(logger)

    return log_file.parent


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
    resolved_log_file = log_file.resolve(strict=False)
    return any(
        isinstance(handler, TimedRotatingFileHandler)
        and Path(handler.baseFilename).resolve(strict=False) == resolved_log_file
        for handler in logger.handlers
    )


def _remove_file_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if (
            isinstance(handler, TimedRotatingFileHandler)
            and getattr(handler, "_rust_sensei_file_handler", False)
        ):
            logger.removeHandler(handler)
            handler.close()


def _ensure_stderr_handler(logger: logging.Logger) -> None:
    if any(getattr(handler, "_rust_sensei_fallback", False) for handler in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(logging.WARNING)
    handler._rust_sensei_fallback = True
    logger.addHandler(handler)
