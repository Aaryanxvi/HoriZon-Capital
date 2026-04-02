"""Structured JSON logging via structlog.

In TUI mode logs go to a rotating file (~/.horizon-capital/horizon.log).
In headless mode logs go to stdout.
"""

import logging
import os
import sys
from pathlib import Path

import structlog

# Log file location
_DATA_DIR = Path(os.getenv("HORIZON_DATA_DIR", Path.home() / ".horizon-capital"))
_LOG_FILE = _DATA_DIR / "horizon.log"


def setup_logging(debug: bool = False, headless: bool = False) -> None:
    """Configure structlog. Logs go to file in TUI mode, stdout in headless."""
    log_level = logging.DEBUG if debug else logging.INFO

    # Choose output target
    if headless:
        log_target = sys.stdout
    else:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_target = open(_LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_target),
        cache_logger_on_first_use=True,
    )

    # Standard library logging goes to same target
    handler = logging.StreamHandler(log_target)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.root.handlers = [handler]
    logging.root.setLevel(log_level)

    # Silence noisy loggers regardless of debug mode
    for noisy in ("aiosqlite", "sqlalchemy.engine", "httpx", "httpcore", "yfinance"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
