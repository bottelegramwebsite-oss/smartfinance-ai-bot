"""
utils/logger.py
Konfigurasi logging terpusat untuk seluruh aplikasi.
Semua modul cukup memanggil get_logger(__name__).
"""

import logging
import sys
from pathlib import Path

from config import settings

# Direktori untuk menyimpan log file
LOG_DIR = Path("./logs")
LOG_FILE = LOG_DIR / "finance_bot.log"

# Format log: timestamp | level | module | pesan
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def _setup_logging() -> None:
    """
    Inisialisasi root logger sekali saat pertama kali dipanggil.
    Handler: stdout (console) + file rotating.
    """
    global _initialized
    if _initialized:
        return

    # Buat direktori log jika belum ada
    LOG_DIR.mkdir(exist_ok=True)

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # ── Root logger ───────────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── Console handler (stdout) ──────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # ── File handler (rotating, max 5 MB × 3 backup) ─────────────────────────
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Hindari duplikat handler jika setup dipanggil ulang
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # Kurangi noise dari library pihak ketiga
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Kembalikan logger dengan nama modul.

    Penggunaan:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Pesan info")
        logger.error("Terjadi error: %s", err)
    """
    _setup_logging()
    return logging.getLogger(name)
