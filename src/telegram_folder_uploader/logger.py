from __future__ import annotations

import logging
from pathlib import Path
from .constants import LOG_FILENAME, LOGS_DIR


def setup_folder_logger(source_root: Path) -> tuple[logging.Logger, Path]:
    log_path = source_root / LOG_FILENAME
    logger = logging.getLogger("upload_telegram")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    try:
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    except OSError:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOGS_DIR / f"{source_root.name or 'root'}-{LOG_FILENAME}"
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger, log_path