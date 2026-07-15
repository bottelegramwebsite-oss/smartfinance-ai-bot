"""
bot/keyboards.py
Definisi semua inline keyboard dan reply markup untuk bot Telegram.
Dipisah dari handlers agar mudah dimodifikasi tanpa menyentuh logika bisnis.
"""

from datetime import date
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from models.transaction import Transaction


# ── Main Menu ─────────────────────────────────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Keyboard utama yang selalu tampil di bawah input.
    Memudahkan akses cepat ke fitur utama.
    """
    buttons = [
        ["📊 Ringkasan Hari Ini", "📅 Laporan Bulanan"],
        ["📋 Riwayat Transaksi", "➕ Input Manual"],
        ["❓ Bantuan"],
    ]
    return ReplyKeyboardMarkup(
        buttons,
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ── Konfirmasi Transaksi ──────────────────────────────────────────────────────

def confirm_transactions_keyboard(transaction_ids: list[int]) -> InlineKeyboardMarkup:
    """
    Keyboard untuk konfirmasi setelah AI mengekstrak transaksi.
    User bisa membatalkan (undo) transaksi yang baru disimpan.
    """
    buttons = []

    # Tombol hapus per transaksi jika lebih dari satu
    if len(transaction_ids) > 1:
        for i, tx_id in enumerate(transaction_ids, 1):
            buttons.append([
                InlineKeyboardButton(
                    f"❌ Batalkan transaksi #{i}",
                    callback_data=f"delete_tx:{tx_id}"
                )
            ])

    # Tombol hapus semua & selesai
    buttons.append([
        InlineKeyboardButton("✅ Selesai", callback_data="confirm_done"),
        InlineKeyboardButton("❌ Batalkan Semua", callback_data=f"delete_all:{','.join(map(str, transaction_ids))}"),
    ])

    return InlineKeyboardMarkup(buttons)


# ── Input Manual ──────────────────────────────────────────────────────────────

def transaction_type_keyboard() -> InlineKeyboardMarkup:
    """Pilih tipe transaksi saat input manual."""
    buttons = [
        [
            InlineKeyboardButton("✅ Pemasukan", callback_data="manual_type:income"),
            InlineKeyboardButton("💸 Pengeluaran", callback_data="manual_type:expense"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def income_category_keyboard() -> InlineKeyboardMarkup:
    """Pilih kategori untuk transaksi pemasukan."""
    categories = Transaction.INCOME_CATEGORIES
    buttons = []
    # 2 tombol per baris
    for i in range(0, len(categories), 2):
        row = [
            InlineKeyboardButton(cat, callback_data=f"manual_cat:{cat}")
            for cat in categories[i:i + 2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("« Kembali", callback_data="manual_back:type")])
    return InlineKeyboardMarkup(buttons)


def expense_category_keyboard() -> InlineKeyboardMarkup:
    """Pilih kategori untuk transaksi pengeluaran."""
    categories = Transaction.EXPENSE_CATEGORIES
    buttons = []
    for i in range(0, len(categories), 2):
        row = [
            InlineKeyboardButton(cat, callback_data=f"manual_cat:{cat}")
            for cat in categories[i:i + 2]
        ]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("« Kembali", callback_data="manual_back:type")])
    return InlineKeyboardMarkup(buttons)


# ── Navigasi Laporan Bulanan ──────────────────────────────────────────────────

def month_navigation_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """
    Navigasi bulan sebelum / sesudah untuk laporan bulanan.
    Tombol 'sesudah' di-disable jika sudah bulan ini.
    """
    # Hitung bulan sebelum dan sesudah
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    today = date.today()
    is_current_or_future = (year > today.year) or (year == today.year and month >= today.month)

    buttons = [
        [
            InlineKeyboardButton(
                "« Bulan Lalu",
                callback_data=f"monthly:{prev_year}:{prev_month}"
            ),
            InlineKeyboardButton(
                "Bulan Ini »" if is_current_or_future else "Bulan Depan »",
                callback_data=f"monthly:{next_year}:{next_month}"
            ),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


# ── Riwayat Transaksi ─────────────────────────────────────────────────────────

def history_action_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Aksi yang bisa dilakukan pada satu transaksi di riwayat."""
    buttons = [
        [InlineKeyboardButton(
            "🗑️ Hapus Transaksi Ini",
            callback_data=f"delete_tx:{transaction_id}"
        )]
    ]
    return InlineKeyboardMarkup(buttons)


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Tombol batal generik."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="cancel")]
    ])
