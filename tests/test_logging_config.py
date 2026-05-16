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


def test_configure_logging_replaces_prior_file_handler_for_new_state_dir(tmp_path):
    logger = logging.getLogger("rust_sensei")
    _clear_handlers(logger)

    first_log_dir = configure_logging(tmp_path / "first")
    second_log_dir = configure_logging(tmp_path / "second")

    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename) == second_log_dir / "rust-sensei.log"
    assert not any(
        Path(handler.baseFilename) == first_log_dir / "rust-sensei.log"
        for handler in handlers
    )


def test_configure_logging_preserves_external_rotating_file_handlers(tmp_path):
    logger = logging.getLogger("rust_sensei")
    _clear_handlers(logger)
    external_log_file = tmp_path / "external.log"
    external_handler = TimedRotatingFileHandler(
        filename=external_log_file,
        when="midnight",
        backupCount=1,
        encoding="utf-8",
    )
    logger.addHandler(external_handler)

    configure_logging(tmp_path / "first")
    second_log_dir = configure_logging(tmp_path / "second")

    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert external_handler in handlers
    assert any(
        getattr(handler, "_rust_sensei_file_handler", False)
        and Path(handler.baseFilename) == second_log_dir / "rust-sensei.log"
        for handler in handlers
    )


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
