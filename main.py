"""
main.py
Entry point aplikasi Bot Telegram Pencatat Keuangan.
Kompatibel dengan Python 3.15 + python-telegram-bot 21.9.
"""

import asyncio
import signal
import threading

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import settings
from models.database import init_db, close_db
from bot.handlers import (
    start_command,
    help_command,
    summary_command,
    history_command,
    monthly_command,
    add_command,
    delete_command,
    setsheet_command,
    message_handler,
    callback_handler,
    error_handler,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def _run_dashboard_server(port: int) -> None:
    """
    Jalankan web server FastAPI (dashboard) di thread terpisah.

    Uvicorn butuh event loop-nya sendiri; menjalankannya di thread lain
    (dengan `server.run()`, yang membuat event loop baru via `asyncio.run`)
    membuatnya berjalan bersamaan (concurrently) dengan polling bot di
    thread utama, tanpa saling blocking. Karena bukan di main thread,
    uvicorn juga otomatis tidak memasang signal handler-nya sendiri —
    jadi tidak bentrok dengan signal handler bot di `_run_async`.
    """
    import uvicorn
    from dashboard.main import app as dashboard_app

    logger.info(f"🌐 Menjalankan dashboard web server di thread terpisah (port {port})...")
    config = uvicorn.Config(
        dashboard_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()


def build_application() -> Application:
    """Buat dan konfigurasi instance Application telegram bot."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    start_command))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("summary",  summary_command))
    app.add_handler(CommandHandler("history",  history_command))
    app.add_handler(CommandHandler("monthly",  monthly_command))
    app.add_handler(CommandHandler("add",      add_command))
    app.add_handler(CommandHandler("delete",   delete_command))
    app.add_handler(CommandHandler("setsheet", setsheet_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    return app


async def _run_async(app: Application) -> None:
    """
    Jalankan bot secara async penuh — kompatibel Python 3.15.
    PTB 21.x harus dijalankan dari dalam event loop yang sudah ada.
    """
    # Inisialisasi dan start application
    await app.initialize()
    await app.start()

    # Mulai polling
    await app.updater.start_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )

    logger.info("✅ Polling aktif. Bot siap menerima pesan.")

    # Tunggu sampai ada sinyal stop
    stop = asyncio.Event()

    def _signal_handler():
        logger.info("Sinyal stop diterima.")
        stop.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT,  _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        pass  # Windows tidak support add_signal_handler

    await stop.wait()

    # Graceful shutdown
    logger.info("Menghentikan bot...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


def main() -> None:
    logger.info("=" * 50)
    logger.info("Bot Keuangan AI — Starting up...")
    logger.info("=" * 50)
    logger.info(f"Groq model : {settings.GROQ_MODEL}")
    logger.info(f"Database   : {settings.DATABASE_PATH}")
    logger.info(f"Timezone   : {settings.TIMEZONE}")
    logger.info(f"GSheets    : {settings.GOOGLE_CREDENTIALS_PATH}")
    logger.info(f"Dashboard  : {settings.DASHBOARD_URL} (port {settings.PORT})")

    init_db()

    # Jalankan dashboard web server di background thread — berjalan bersamaan
    # (concurrently) dengan bot polling di bawah, tanpa saling blocking.
    dashboard_thread = threading.Thread(
        target=_run_dashboard_server,
        args=(settings.PORT,),
        daemon=True,
        name="dashboard-server",
    )
    dashboard_thread.start()

    app = build_application()

    logger.info("Bot berjalan. Tekan Ctrl+C untuk menghentikan.")

    asyncio.run(_run_async(app))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot dihentikan.")
    except Exception as e:
        logger.critical(f"Bot berhenti: {e}", exc_info=True)
        raise
    finally:
        close_db()
        logger.info("Selesai.")
