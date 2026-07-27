"""Logging configuration — console + rotating file with timestamps."""

import logging
import sys
from pathlib import Path


def setup_logging() -> None:
    """Configure root logger: coloured console output + daily rotating file.

    File logs go to ``logs/issuescope.{YYYY-MM-DD}.log``, rotated daily,
    kept for 30 days.  Console logs use a simpler format without the date
    (the terminal already shows it).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup_logging is called more than once.
    if root.handlers:
        return

    # ── Console handler ───────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # ── File handler (daily rotation, 30-day retain) ──────────────
    from logging.handlers import TimedRotatingFileHandler

    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "issuescope.log"
    file_handler = TimedRotatingFileHandler(
        str(log_file), when="midnight", interval=1, backupCount=30,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
