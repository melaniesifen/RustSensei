import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rust_sensei.logging_config import configure_logging


def test_configure_logging_creates_append_only_daily_log_file(tmp_path):
    log_dir = configure_logging(tmp_path)
    logger = logging.getLogger("rust_sensei.test")

    logger.info("first message")
    logger.info("second message")

    log_file = log_dir / "rust-sensei.log"
    content = log_file.read_text(encoding="utf-8")
    assert log_dir == tmp_path / "logs"
    assert "first message" in content
    assert "second message" in content


def test_configure_logging_does_not_duplicate_handlers_for_relative_paths(
    tmp_path,
    monkeypatch,
):
    logger = logging.getLogger("rust_sensei")
    _clear_handlers(logger)
    monkeypatch.chdir(tmp_path)

    configure_logging(Path("state"))
    configure_logging(Path("state"))

    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert len(handlers) == 1


def test_configure_logging_falls_back_when_state_path_is_invalid():
    logger = logging.getLogger("rust_sensei")
    _clear_handlers(logger)

    log_dir = configure_logging(Path("/dev/null"))

    assert log_dir == Path("/dev/null/logs")
    assert any(getattr(handler, "_rust_sensei_fallback", False) for handler in logger.handlers)


def _clear_handlers(logger):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
