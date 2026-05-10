import logging

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
