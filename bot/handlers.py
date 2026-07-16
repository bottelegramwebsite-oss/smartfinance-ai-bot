"""
bot/handlers.py
Handler untuk semua command dan message dari Telegram.
Menggunakan python-telegram-bot v20+ (async-based).
"""

import asyncio
from datetime import date
from functools import partial
from typing import Optional

from telegram import Update
from telegram.error import Conflict as TelegramConflict
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from sqlalchemy.exc import OperationalError as DBOperationalError

from config import settings
from services import transaction_service
from services.ai_service import ai_service
from services.sheets_service import extract_spreadsheet_id, validate_sheet_access
from utils.helpers import (
    format_rupiah, format_date_display, format_month_year,
    get_category_emoji, get_type_emoji, truncate_text,
    today_local, parse_amount_from_text,
)
from utils.logger import get_logger
from bot.keyboards import (
    main_menu_keyboard, confirm_transactions_keyboard,
    month_navigation_keyboard,
)

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNAL
# ══════════════════════════════════════════════════════════════════════════════

async def _send_monthly_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    year: int,
    month: int,
) -> None:
    """Kirim laporan bulanan ke user (dipakai oleh command dan callback)."""
    user_id = update.effective_user.id
    summary = transaction_service.get_monthly_summary(user_id, year, month)
    month_label = format_month_year(date(year, month, 1))

    msg = update.message or update.callback_query.message

    if summary["count"] == 0:
        await msg.reply_text(
            f"📭 Tidak ada transaksi di bulan <b>{month_label}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=month_navigation_keyboard(year, month),
        )
        return

    by_cat = summary.get("by_category", {})
    income_lines, expense_lines = [], []
    for (tx_type, category), data in sorted(by_cat.items(), key=lambda x: -x[1]["total"]):
        emoji = get_category_emoji(category)
        line = f"  {emoji} {category}: {format_rupiah(data['total'])} ({data['count']}x)"
        if tx_type == "income":
            income_lines.append(line)
        else:
            expense_lines.append(line)

    income_section = "\n".join(income_lines) if income_lines else "  (tidak ada)"
    expense_section = "\n".join(expense_lines) if expense_lines else "  (tidak ada)"

    text = (
        f"📅 <b>Laporan {month_label}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Pemasukan</b>: {format_rupiah(summary['total_income'])}\n"
        f"{income_section}\n\n"
        f"💸 <b>Pengeluaran</b>: {format_rupiah(summary['total_expense'])}\n"
        f"{expense_section}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Saldo Bulan Ini</b>: {format_rupiah(summary['balance'])}\n"
        f"📝 Total: {summary['count']} transaksi "
        f"({summary['income_count']} masuk, {summary['expense_count']} keluar)"
    )
    await msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=month_navigation_keyboard(year, month),
    )


async def _send_transaction_confirmation(update: Update, transactions: list) -> None:
    """Kirim pesan konfirmasi setelah transaksi AI berhasil disimpan."""
    try:
        lines = ["✅ <b>Transaksi Berhasil Dicatat!</b>\n"]

        for i, tx in enumerate(transactions, 1):
            emoji = get_type_emoji(tx.type)
            cat_emoji = get_category_emoji(tx.category)
            type_label = "Pemasukan" if tx.type == "income" else "Pengeluaran"
            desc = tx.description or tx.category

            from datetime import date as date_type
            td = tx.transaction_date
            if isinstance(td, str):
                try:
                    td = date_type.fromisoformat(td)
                except Exception:
                    td = today_local()
            date_str = format_date_display(td) if td else "—"

            lines.append(
                f"<b>{'—' * 20}</b>\n"
                f"{emoji} <b>#{i} {type_label}</b>\n"
                f"{cat_emoji} {tx.category}\n"
                f"💰 {format_rupiah(tx.amount)}\n"
                f"📝 {truncate_text(desc, 40)}\n"
                f"📅 {date_str}\n"
                f"🔖 ID: #{tx.id}"
            )

        if len(transactions) > 1:
            total_income = sum(t.amount for t in transactions if t.type == "income")
            total_expense = sum(t.amount for t in transactions if t.type == "expense")
            lines.append(f"\n<b>{'—' * 20}</b>")
            if total_income:
                lines.append(f"✅ Total masuk : {format_rupiah(total_income)}")
            if total_expense:
                lines.append(f"💸 Total keluar: {format_rupiah(total_expense)}")

        lines.append("\n<i>Salah catat? Tekan tombol di bawah atau ketik /delete [ID]</i>")

        tx_ids = [tx.id for tx in transactions]
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_transactions_keyboard(tx_ids),
        )

    except Exception as e:
        logger.error(f"Error saat kirim konfirmasi transaksi: {e}", exc_info=True)
        await update.message.reply_text(
            f"✅ {len(transactions)} transaksi berhasil disimpan!\n"
            f"Ketik /history untuk melihat riwayat.",
            reply_markup=main_menu_keyboard(),
        )


async def _send_ai_error(update: Update) -> None:
    """Pesan fallback ketika Groq/Gemini API gagal setelah semua retry."""
    await update.message.reply_text(
        "⚠️ <b>AI sedang tidak tersedia.</b>\n\n"
        "Silakan catat secara manual:\n"
        "<code>/add [tipe] [nominal] [kategori] [keterangan]</code>\n\n"
        "Contoh:\n"
        "<code>/add pengeluaran 30000 Makanan makan siang</code>\n"
        "<code>/add pemasukan 100000 Investasi profit saham</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user

    transaction_service.upsert_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )

    spreadsheet_id = transaction_service.get_user_spreadsheet_id(tg_user.id)
    nama = tg_user.first_name or tg_user.username or "Kamu"

    if spreadsheet_id:
        await update.message.reply_text(
            f"👋 Halo lagi, <b>{nama}</b>!\n\n"
            "✅ Google Sheet kamu sudah terhubung.\n"
            "Langsung ketik transaksimu, semua otomatis tercatat.\n\n"
            "📌 <b>Contoh:</b>\n"
            "• <i>Makan siang 30rb</i>\n"
            "• <i>Gaji masuk 5jt</i>\n"
            "• <i>Bayar listrik 200rb dan beli kopi 25rb</i>\n\n"
            "/summary /history /monthly /help",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            f"👋 Halo, <b>{nama}</b>! Selamat datang di Bot Keuangan AI.\n\n"
            "Untuk mulai mencatat, kamu perlu menghubungkan Google Sheet.\n\n"
            "🌐 <b>Cara termudah — daftar via website:</b>\n"
            f"<a href='{settings.DASHBOARD_URL}'>{settings.DASHBOARD_URL}</a>\n"
            "Cukup isi nama + link sheet, selesai!\n\n"
            "📱 <b>Atau daftar langsung di sini:</b>\n"
            "Kirim: <code>/setsheet [link_google_sheet]</code>\n\n"
            "Setelah terhubung, kamu bisa langsung ketik transaksi seperti:\n"
            "• <i>Makan siang 30rb</i>\n"
            "• <i>Terima transfer 500rb dari klien</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ <b>Panduan Penggunaan</b>\n\n"
        "<b>1. Catat via AI (natural language)</b>\n"
        "Ketik saja dengan bahasa natural:\n"
        "• <i>Beli bensin 80rb</i>\n"
        "• <i>Transfer dari klien 2.5jt</i>\n"
        "• <i>Kopi 25rb, ojek 15rb, makan 40rb</i>\n\n"
        "<b>2. Input Manual</b>\n"
        "<code>/add [tipe] [nominal] [kategori] [keterangan]</code>\n"
        "Contoh: <code>/add pengeluaran 30000 Makanan makan siang</code>\n\n"
        "<b>3. Hapus Transaksi</b>\n"
        "<code>/delete [ID]</code>\n\n"
        "<b>4. Sinkronisasi Google Sheets</b>\n"
        "<code>/setsheet [link_google_sheet]</code>\n\n"
        "<b>5. Bersihkan Riwayat Lokal</b>\n"
        "<code>/clear</code> — hapus semua riwayat transaksi lokal Anda\n\n"
        "<b>6. Semua Perintah</b>\n"
        "/start /summary /monthly /history /add /delete /setsheet /clear /help",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    today = today_local()

    today_data = transaction_service.get_today_summary(user_id)
    overall_data = transaction_service.get_overall_summary(user_id)

    if overall_data["count"] == 0:
        await update.message.reply_text(
            "📭 Belum ada transaksi tercatat.\n\n"
            "Mulai ketik transaksimu, contoh: <i>Makan siang 30rb</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.reply_text(
        f"📊 <b>Ringkasan Keuangan</b>\n"
        f"<i>{format_date_display(today)}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Hari Ini</b>\n"
        f"✅ Pemasukan  : {format_rupiah(today_data['total_income'])}\n"
        f"💸 Pengeluaran: {format_rupiah(today_data['total_expense'])}\n"
        f"💰 Saldo      : <b>{format_rupiah(today_data['balance'])}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>All-time</b>\n"
        f"✅ Total Pemasukan  : {format_rupiah(overall_data['total_income'])}\n"
        f"💸 Total Pengeluaran: {format_rupiah(overall_data['total_expense'])}\n"
        f"💰 Saldo Total      : <b>{format_rupiah(overall_data['balance'])}</b>\n"
        f"📝 Total Transaksi  : {overall_data['count']} transaksi",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    transactions = transaction_service.get_recent_transactions(user_id, limit=10)

    if not transactions:
        await update.message.reply_text(
            "📭 Belum ada riwayat transaksi.",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = ["📋 <b>10 Transaksi Terakhir</b>\n"]
    for i, tx in enumerate(transactions, 1):
        emoji = get_type_emoji(tx.type)
        cat_emoji = get_category_emoji(tx.category)
        sign = "+" if tx.type == "income" else "-"
        desc = truncate_text(tx.description, 25) if tx.description else tx.category
        lines.append(
            f"{i}. {emoji} <code>[#{tx.id}]</code> {cat_emoji} {desc}\n"
            f"   {sign}{format_rupiah(tx.amount)} · "
            f"{tx.transaction_date.strftime('%d/%m/%Y')}"
        )

    lines.append("\n💡 <i>Hapus transaksi: /delete [ID]</i>")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = today_local()
    await _send_monthly_report(update, context, today.year, today.month)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args or len(args) < 2:
        await update.message.reply_text(
            "📝 <b>Format Input Manual</b>\n\n"
            "<code>/add [tipe] [nominal] [kategori] [keterangan]</code>\n\n"
            "Contoh: <code>/add pengeluaran 30000 Makanan makan siang</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return

    type_map = {
        "pengeluaran": "expense", "keluar": "expense",
        "expense": "expense", "pemasukan": "income",
        "masuk": "income", "income": "income",
    }
    tx_type = type_map.get(args[0].lower())
    if not tx_type:
        await update.message.reply_text(
            f"❌ Tipe '<b>{args[0]}</b>' tidak dikenal.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        amount_str = args[1].replace(",", "").replace(".", "")
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        amount = parse_amount_from_text(args[1])
        if not amount:
            await update.message.reply_text(
                f"❌ Nominal '<b>{args[1]}</b>' tidak valid.",
                parse_mode=ParseMode.HTML,
            )
            return

    category = args[2] if len(args) > 2 else "Lainnya"
    description = " ".join(args[3:]) if len(args) > 3 else ""

    sheets_warning: str = ""
    try:
        tx = transaction_service.save_manual_transaction(
            user_id=user_id,
            amount=amount,
            tx_type=tx_type,
            category=category,
            description=description,
        )
    except transaction_service.SheetsWarning as sw:
        # Transaction IS in the local DB; only Sheets sync failed.
        tx = sw.tx
        sheets_warning = str(sw)
    except DBOperationalError as e:
        logger.error(f"[user {user_id}] DB locked (manual): {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Sistem sedang sibuk mencatat data, mohon coba kirim kembali dalam beberapa detik.",
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as e:
        logger.error(f"[user {user_id}] Gagal simpan transaksi manual: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Gagal menyimpan transaksi: {str(e)}",
            reply_markup=main_menu_keyboard(),
        )
        return

    emoji = get_type_emoji(tx_type)
    cat_emoji = get_category_emoji(category)
    await update.message.reply_text(
        f"✅ <b>Transaksi Disimpan!</b>\n\n"
        f"{emoji} <b>Tipe</b>     : {'Pemasukan' if tx_type == 'income' else 'Pengeluaran'}\n"
        f"{cat_emoji} <b>Kategori</b>: {category}\n"
        f"💰 <b>Nominal</b>  : {format_rupiah(amount)}\n"
        f"🔖 <b>ID</b>       : #{tx.id}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )
    if sheets_warning:
        await update.message.reply_text(
            f"⚠️ <i>Tersimpan secara lokal, gagal sinkron ke Google Sheets:</i>\n{sheets_warning}",
            parse_mode=ParseMode.HTML,
        )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "🗑️ Format: <code>/delete [ID]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        tx_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka.")
        return

    success = transaction_service.delete_transaction(user_id, tx_id)
    if success:
        await update.message.reply_text(
            f"🗑️ Transaksi <b>#{tx_id}</b> berhasil dihapus.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            f"❌ Transaksi <b>#{tx_id}</b> tidak ditemukan.",
            parse_mode=ParseMode.HTML,
        )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hapus semua riwayat transaksi lokal milik user (mulai dari awal)."""
    user_id = update.effective_user.id
    try:
        transaction_service.clear_user_history(user_id)
    except Exception as e:
        logger.error(f"[user {user_id}] Gagal membersihkan riwayat lokal: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Gagal membersihkan riwayat. Silakan coba lagi.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.reply_text(
        "🧹 Semua riwayat transaksi lokal Anda telah dihapus bersih!",
        reply_markup=main_menu_keyboard(),
    )


async def setsheet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args

    if not args:
        current_id = transaction_service.get_user_spreadsheet_id(user_id)
        status_text = f"📊 Sheet aktif Anda: <code>{current_id}</code>\n\n" if current_id else "📭 Anda belum mendaftarkan Google Sheet.\n\n"
        await update.message.reply_text(
            f"{status_text}📋 <b>Cara Mendaftarkan Google Sheet:</b>\n"
            "<code>/setsheet [link_google_sheet]</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return

    raw_input = args[0].strip()
    spreadsheet_id = extract_spreadsheet_id(raw_input)
    if not spreadsheet_id:
        await update.message.reply_text("❌ <b>Format link tidak valid.</b>", parse_mode=ParseMode.HTML)
        return

    await update.message.chat.send_action("typing")
    processing_msg = await update.message.reply_text("⏳ Sedang memvalidasi akses ke Google Sheet...")

    try:
        loop = asyncio.get_event_loop()
        success, result_info = await loop.run_in_executor(
            None, partial(validate_sheet_access, spreadsheet_id)
        )
    except Exception as e:
        await processing_msg.edit_text("❌ Gagal menghubungi Google Sheets API.", parse_mode=ParseMode.HTML)
        return

    if not success:
        await processing_msg.edit_text(f"❌ <b>Gagal mengakses Google Sheet.</b>\n\n{result_info}", parse_mode=ParseMode.HTML)
        return

    transaction_service.set_user_spreadsheet(user_id, spreadsheet_id)
    await processing_msg.edit_text(
        f"✅ <b>Google Sheet berhasil didaftarkan!</b>\n\n📊 <b>Nama Sheet</b>: {result_info}",
        parse_mode=ParseMode.HTML,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER — Natural Language Input (Core Feature)
# ══════════════════════════════════════════════════════════════════════════════

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()

    shortcuts = {
        "📊 Ringkasan Hari Ini": summary_command,
        "📅 Laporan Bulanan": monthly_command,
        "📋 Riwayat Transaksi": history_command,
        "❓ Bantuan": help_command,
    }
    if text in shortcuts:
        await shortcuts[text](update, context)
        return

    if text == "➕ Input Manual":
        await update.message.reply_text(
            "📝 Gunakan perintah:\n<code>/add [tipe] [nominal] [kategori] [keterangan]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not ai_service.is_financial_message(text):
        await update.message.reply_text(
            "🤔 Saya tidak mendeteksi informasi keuangan. Coba tulis seperti: <i>Makan siang 30rb</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.chat.send_action("typing")

    loop = asyncio.get_event_loop()
    try:
        saved, errors, extraction_result = await loop.run_in_executor(
            None,
            partial(transaction_service.process_natural_language_input, user.id, text),
        )
    except DBOperationalError as e:
        logger.error(f"[user {user.id}] Database locked/busy: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Sistem sedang sibuk mencatat data, mohon coba kirim kembali dalam beberapa detik.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as e:
        logger.error(f"[user {user.id}] Pipeline error: {e}", exc_info=True)
        await _send_ai_error(update)
        return

    # ── Prioritas utama: transaksi berhasil disimpan → selalu tampilkan sukses ──
    # Ini mencakup kasus di mana Gemini gagal tetapi heuristic engine berhasil.
    # Pengguna tidak perlu tahu engine mana yang digunakan.
    if saved:
        await _send_transaction_confirmation(update, saved)
        if errors:
            # Hanya tampilkan warning Sheets sync, bukan error AI
            err_text = "\n".join([f"• {e}" for e in errors])
            await update.message.reply_text(
                f"⚠️ <i>Tersimpan secara lokal, gagal sinkron ke Google Sheets:</i>\n{err_text}",
                parse_mode=ParseMode.HTML,
            )
        else:
            spreadsheet_id = transaction_service.get_user_spreadsheet_id(user.id)
            if not spreadsheet_id:
                await update.message.reply_text(
                    "💡 <i>Transaksi tersimpan. Daftarkan Google Sheet Anda dengan perintah /setsheet [link_sheet] agar tersinkronisasi otomatis!</i>",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        return

    # ── Tidak ada transaksi yang tersimpan → periksa apakah AI benar-benar gagal ──
    if not extraction_result.success:
        # AI gagal total dan tidak ada transaksi yang bisa diselamatkan
        await _send_ai_error(update)
        return

    # AI berhasil tapi tidak mendeteksi transaksi dalam pesan
    await update.message.reply_text(
        "🤔 Saya membaca pesanmu tapi tidak yakin ini transaksi keuangan.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY HANDLER — Inline Keyboard
# ══════════════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    if data == "confirm_done":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Semua transaksi tersimpan!", reply_markup=main_menu_keyboard())

    elif data.startswith("delete_tx:"):
        tx_id = int(data.split(":")[1])
        success = transaction_service.delete_transaction(user_id, tx_id)
        if success:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"🗑️ Transaksi <b>#{tx_id}</b> berhasil dihapus.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard(),
            )
        else:
            await query.message.reply_text(f"❌ Transaksi #{tx_id} tidak ditemukan.")

    elif data.startswith("delete_all:"):
        ids = [int(i) for i in data.split(":")[1].split(",")]
        deleted = sum(1 for tx_id in ids if transaction_service.delete_transaction(user_id, tx_id))
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"🗑️ {deleted} transaksi berhasil dibatalkan.", reply_markup=main_menu_keyboard())

    elif data.startswith("monthly:"):
        _, year, month = data.split(":")
        await _send_monthly_report(update, context, int(year), int(month))

    elif data == "cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_keyboard())


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL ERROR HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Conflict terjadi saat ada dua instance bot berjalan bersamaan.
    # Ini bukan error fatal — cukup log sebagai warning agar log tidak banjir.
    if isinstance(context.error, TelegramConflict):
        logger.warning(
            "⚠️ Telegram Conflict: instance bot lain sedang berjalan bersamaan "
            "(cek apakah bot juga aktif di mesin lokal atau deployment lain). "
            "Bot ini akan terus mencoba polling."
        )
        return

    logger.error("Unhandled exception:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Terjadi kesalahan pada sistem. Silakan coba lagi.",
            reply_markup=main_menu_keyboard(),
        )