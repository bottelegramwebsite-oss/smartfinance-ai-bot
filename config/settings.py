"""
config/settings.py
Memuat dan memvalidasi semua environment variables yang dibutuhkan aplikasi.
"""

import os
from dotenv import load_dotenv

# Load .env file dari root project
load_dotenv()


class ConfigError(Exception):
    """Exception untuk konfigurasi yang tidak valid."""
    pass


def _get_env(key: str, default: str = None, required: bool = True) -> str:
    """
    Ambil environment variable. Raise ConfigError jika wajib tapi tidak ada.
    """
    value = os.getenv(key, default)
    if required and not value:
        raise ConfigError(
            f"Environment variable '{key}' wajib diisi tapi tidak ditemukan. "
            f"Pastikan file .env sudah dibuat dari .env.example."
        )
    return value


# ── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = _get_env("TELEGRAM_BOT_TOKEN")

# ── Groq AI ─────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = _get_env("GROQ_API_KEY")
GROQ_MODEL: str = _get_env("GROQ_MODEL", default="llama-3.3-70b-versatile", required=False)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_PATH: str = _get_env("DATABASE_PATH", default="./data/finance.db", required=False)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = _get_env("LOG_LEVEL", default="INFO", required=False)

# ── Timezone ─────────────────────────────────────────────────────────────────
TIMEZONE: str = _get_env("TIMEZONE", default="Asia/Jakarta", required=False)

# ── AI Configuration ─────────────────────────────────────────────────────────
AI_TIMEOUT: int = int(_get_env("AI_TIMEOUT", default="30", required=False))
AI_MAX_RETRIES: int = int(_get_env("AI_MAX_RETRIES", default="3", required=False))

# ── Confidence threshold untuk ekstraksi AI ──────────────────────────────────
AI_CONFIDENCE_THRESHOLD: float = 0.65

# ── Google Sheets (opsional) ──────────────────────────────────────────────────
# Path ke file credentials.json Service Account.
# Jika tidak diset, fitur Google Sheets dinonaktifkan secara otomatis.
GOOGLE_CREDENTIALS_PATH: str = _get_env(
    "GOOGLE_CREDENTIALS_PATH",
    default="./credentials.json",
    required=False,
)

# ── Dashboard (website) ────────────────────────────────────────────────────────
# URL publik dashboard, dipakai di pesan bot (/start, /help) agar user diarahkan
# ke tempat yang benar. Set env var DASHBOARD_URL jika domain berubah.
DASHBOARD_URL: str = _get_env(
    "DASHBOARD_URL",
    default="https://smartfinanceai--bottelegramwebs.replit.app",
    required=False,
)

# ── Web server (dashboard) ─────────────────────────────────────────────────────
# Port yang dipakai FastAPI dashboard saat dijalankan bersama bot dari main.py.
PORT: int = int(_get_env("PORT", default="5000", required=False))
