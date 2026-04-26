from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_STANDARD_LOG_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [%(name)s] %(filename)s:%(lineno)d - %(message)s"
)
_FLOW_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DEFAULT_MAX_BYTES = 3 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 10
_REDACTED = "***REDACTED***"
_TELEGRAM_BOT_URL_RE = re.compile(
    r"(https?://api\.telegram\.org/bot)([^/\s\"']+)",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?(?:bot_token|notification_bot_token|api_key|api_hash|"
    r"session_string|password|secret_key|app_secret_key|tg_api_hash)[\"']?"
    r"\s*[:=]\s*[\"']?)([^\"'\s,;}]+)([\"']?)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|api_key|api_hash|password|secret|session_string)=)([^&\s\"']+)"
)
_URL_PASSWORD_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)"
)


def redact_sensitive_text(value: str) -> str:
    text = str(value)
    text = _TELEGRAM_BOT_URL_RE.sub(rf"\1{_REDACTED}", text)
    text = _SECRET_ASSIGNMENT_RE.sub(rf"\1{_REDACTED}\3", text)
    text = _SECRET_QUERY_RE.sub(rf"\1{_REDACTED}", text)
    text = _URL_PASSWORD_RE.sub(rf"\1{_REDACTED}\3", text)
    return text


def _redact_log_value(value):
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {key: _redact_log_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]

    text = str(value)
    redacted = redact_sensitive_text(text)
    if redacted != text:
        return redacted
    return value


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            try:
                record.msg = redact_sensitive_text(record.getMessage())
                record.args = ()
                return True
            except Exception:
                record.args = _redact_log_value(record.args)
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        return True


def ensure_sensitive_filter(target: logging.Handler | logging.Logger) -> None:
    if not any(isinstance(item, SensitiveDataFilter) for item in target.filters):
        target.addFilter(SensitiveDataFilter())


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


class MinLevelFilter(logging.Filter):
    def __init__(self, min_level: int):
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


def build_formatter(*, include_source: bool = True) -> logging.Formatter:
    pattern = _STANDARD_LOG_FORMAT if include_source else _FLOW_LOG_FORMAT
    return logging.Formatter(pattern, datefmt=LOG_DATE_FORMAT)


def format_log_line(
    message: str,
    *,
    level: str = "INFO",
    logger_name: str = "backend",
    when: datetime | None = None,
) -> str:
    timestamp = (when or datetime.now()).strftime(LOG_DATE_FORMAT)
    return f"[{timestamp}] [{level.upper()}] [{logger_name}] {message}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    return utc_now().replace(tzinfo=None)


def utc_now_iso_z(*, timespec: str = "seconds") -> str:
    return utc_now().isoformat(timespec=timespec).replace("+00:00", "Z")


def utc_from_timestamp_iso_z(timestamp: int | float, *, timespec: str = "seconds") -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec=timespec
    ).replace("+00:00", "Z")


def describe_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = "无异常详情"
    return f"{type(exc).__name__}: {message}"


def _ensure_rotating_handler(
    logger: logging.Logger,
    *,
    file_path: Path,
    level: int,
    formatter: logging.Formatter,
    record_filter: logging.Filter | None = None,
) -> None:
    target_path = str(file_path.resolve())
    for handler in logger.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename).resolve() == Path(target_path)
        ):
            handler.setLevel(level)
            handler.setFormatter(formatter)
            ensure_sensitive_filter(handler)
            return

    handler = RotatingFileHandler(
        file_path,
        maxBytes=_DEFAULT_MAX_BYTES,
        backupCount=_DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    ensure_sensitive_filter(handler)
    if record_filter is not None:
        handler.addFilter(record_filter)
    logger.addHandler(handler)


def configure_application_logging(log_dir: Path | None = None) -> None:
    formatter = build_formatter(include_source=True)
    root_logger = logging.getLogger()

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            ensure_sensitive_filter(handler)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        ensure_sensitive_filter(console_handler)
        root_logger.addHandler(console_handler)

    if root_logger.level in {logging.NOTSET, 0} or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    for logger_name in (
        "backend",
        "tg-signer",
        "apscheduler",
        "uvicorn.error",
        "uvicorn.access",
    ):
        named_logger = logging.getLogger(logger_name)
        if named_logger.level in {logging.NOTSET, 0} or named_logger.level > logging.INFO:
            named_logger.setLevel(logging.INFO)
        for handler in named_logger.handlers:
            handler.setFormatter(formatter)
            ensure_sensitive_filter(handler)

    if log_dir is None:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    _ensure_rotating_handler(
        root_logger,
        file_path=log_dir / "app.log",
        level=logging.INFO,
        formatter=formatter,
    )
    _ensure_rotating_handler(
        root_logger,
        file_path=log_dir / "warn.log",
        level=logging.WARNING,
        formatter=formatter,
        record_filter=ExactLevelFilter(logging.WARNING),
    )
    _ensure_rotating_handler(
        root_logger,
        file_path=log_dir / "error.log",
        level=logging.ERROR,
        formatter=formatter,
        record_filter=MinLevelFilter(logging.ERROR),
    )
