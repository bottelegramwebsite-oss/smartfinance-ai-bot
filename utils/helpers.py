"""
utils/helpers.py
Fungsi utilitas yang dipakai lintas modul:
- Format mata uang Rupiah
- Format tanggal untuk tampilan
- Kalkulasi ringkasan keuangan
- Emoji untuk kategori & tipe transaksi
"""

from datetime import date, datetime
from typing import List, Optional
import pytz

from config import settings


# ── Timezone ──────────────────────────────────────────────────────────────────

def get_local_tz() -> pytz.BaseTzInfo:
    """Kembalikan timezone yang dikonfigurasi (default: Asia/Jakarta)."""
    return pytz.timezone(settings.TIMEZONE)


def now_local() -> datetime:
    """Waktu saat ini dalam timezone lokal."""
    return datetime.now(get_local_tz())


def today_local() -> date:
    """Tanggal hari ini dalam timezone lokal."""
    return now_local().date()


# ── Format Mata Uang ──────────────────────────────────────────────────────────

def format_rupiah(amount: float, show_sign: bool = False) -> str:
    """
    Format angka ke format Rupiah Indonesia.

    Args:
        amount: Nominal dalam rupiah
        show_sign: Tampilkan tanda + untuk nilai positif

    Returns:
        String seperti "Rp 30.000" atau "+ Rp 100.000"

    Examples:
        >>> format_rupiah(30000)
        'Rp 30.000'
        >>> format_rupiah(1500000)
        'Rp 1.500.000'
        >>> format_rupiah(100000, show_sign=True)
        '+ Rp 100.000'
    """
    # Format angka dengan pemisah ribuan titik (gaya Indonesia)
    formatted = f"Rp {int(amount):,}".replace(",", ".")

    if show_sign and amount >= 0:
        return f"+ {formatted}"
    return formatted


def parse_amount_from_text(text: str) -> Optional[float]:
    """
    Coba parse nominal dari teks mentah sebagai fallback manual.
    Mendukung: "30rb", "30ribu", "1jt", "1.5jt", "200 ribu", "1,500,000"

    Returns:
        Float nominal atau None jika tidak bisa diparse
    """
    import re

    text = text.lower().strip()

    # Pattern: angka + satuan (rb/ribu/jt/juta/m/miliar)
    pattern = r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|m|miliar|milion)?"
    match = re.search(pattern, text)

    if not match:
        return None

    number_str, unit = match.groups()

    # Normalkan desimal: ganti koma dengan titik
    number_str = number_str.replace(",", ".")
    try:
        number = float(number_str)
    except ValueError:
        return None

    multipliers = {
        "rb": 1_000,
        "ribu": 1_000,
        "k": 1_000,
        "jt": 1_000_000,
        "juta": 1_000_000,
        "m": 1_000_000,
        "miliar": 1_000_000_000,
        "milion": 1_000_000,
    }

    if unit and unit in multipliers:
        number *= multipliers[unit]

    return number


# ── Format Tanggal ────────────────────────────────────────────────────────────

def format_date_display(d: date) -> str:
    """
    Format tanggal untuk ditampilkan ke user.

    Returns:
        String seperti "Kamis, 10 Juli 2026"
    """
    HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    BULAN = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    hari = HARI[d.weekday()]
    return f"{hari}, {d.day} {BULAN[d.month]} {d.year}"


def format_month_year(d: date) -> str:
    """Format bulan-tahun, contoh: 'Juli 2026'."""
    BULAN = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    return f"{BULAN[d.month]} {d.year}"


# ── Emoji ─────────────────────────────────────────────────────────────────────

CATEGORY_EMOJI = {
    # Income
    "Gaji": "💼",
    "Investasi": "📈",
    "Freelance": "💻",
    "Bonus": "🎁",
    "Hadiah": "🎀",
    "Penjualan": "🛒",
    # Expense
    "Makanan & Minuman": "🍔",
    "Transportasi": "🚗",
    "Belanja": "🛍️",
    "Tagihan & Utilitas": "💡",
    "Hiburan": "🎮",
    "Kesehatan": "❤️‍🩹",
    "Pendidikan": "📚",
    "Cicilan": "🏦",
    # Default
    "Lainnya": "📝",
}

TYPE_EMOJI = {
    "income": "✅",
    "expense": "💸",
}


def get_category_emoji(category: str) -> str:
    """Kembalikan emoji untuk kategori tertentu."""
    return CATEGORY_EMOJI.get(category, "📝")


def get_type_emoji(transaction_type: str) -> str:
    """Kembalikan emoji untuk tipe transaksi."""
    return TYPE_EMOJI.get(transaction_type, "💰")


# ── Ringkasan Keuangan ────────────────────────────────────────────────────────

def calculate_summary(transactions: List) -> dict:
    """
    Hitung total pemasukan, pengeluaran, dan saldo dari list transaksi.

    Args:
        transactions: List objek Transaction

    Returns:
        dict dengan keys: total_income, total_expense, balance, count
    """
    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expense = sum(t.amount for t in transactions if t.type == "expense")

    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": total_income - total_expense,
        "count": len(transactions),
        "income_count": sum(1 for t in transactions if t.type == "income"),
        "expense_count": sum(1 for t in transactions if t.type == "expense"),
    }


def truncate_text(text: str, max_length: int = 30) -> str:
    """Potong teks jika melebihi batas, tambahkan '...'."""
    if not text:
        return "-"
    return text if len(text) <= max_length else text[:max_length - 3] + "..."
