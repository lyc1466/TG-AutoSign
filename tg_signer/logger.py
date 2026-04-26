import logging
import pathlib
from logging.handlers import RotatingFileHandler

from backend.core.logging import (
    ExactLevelFilter,
    MinLevelFilter,
    build_formatter,
    ensure_sensitive_filter,
)

formatter = build_formatter(include_source=True)


def configure_logger(
    name: str = "tg-signer",
    log_level: str = "INFO",
    log_dir: str | pathlib.Path = "logs",
    log_file: str | pathlib.Path = None,
    max_bytes: int = 1024 * 1024 * 3,
):
    level = log_level.strip().upper()
    level_no: int = logging.getLevelName(level)
    logger = logging.getLogger(name)
    logger.setLevel(level_no)
    logger.handlers.clear()
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    ensure_sensitive_filter(console_handler)
    logger.addHandler(console_handler)

    log_dir = pathlib.Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_file or log_dir / f"{name}.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    ensure_sensitive_filter(file_handler)
    logger.addHandler(file_handler)

    if logging.WARNING >= level_no:
        warn_file_handler = RotatingFileHandler(
            log_dir / "warn.log",
            maxBytes=max_bytes,
            backupCount=10,
            encoding="utf-8",
        )
        warn_file_handler.setLevel(logging.WARNING)
        warn_file_handler.addFilter(ExactLevelFilter(logging.WARNING))
        warn_file_handler.setFormatter(formatter)
        ensure_sensitive_filter(warn_file_handler)
        logger.addHandler(warn_file_handler)

    if logging.ERROR >= level_no:
        error_file_handler = RotatingFileHandler(
            log_dir / "error.log",
            maxBytes=max_bytes,
            backupCount=10,
            encoding="utf-8",
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.addFilter(MinLevelFilter(logging.ERROR))
        error_file_handler.setFormatter(formatter)
        ensure_sensitive_filter(error_file_handler)

        logger.addHandler(error_file_handler)
    from backend.core.runtime_config import get_legacy_signer_runtime_config

    if get_legacy_signer_runtime_config().pyrogram_log_enabled:
        pyrogram_logger = logging.getLogger("pyrogram")
        pyrogram_logger.setLevel(level)
        pyrogram_logger.addHandler(console_handler)
    return logger
