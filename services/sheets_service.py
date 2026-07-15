"""
services/sheets_service.py
Integrasi Google Sheets menggunakan gspread + google-auth (Service Account).

Tanggung jawab:
  - Inisialisasi koneksi ke Google Sheets API (lazy, singleton)
  - Membuat header baris pertama jika sheet masih kosong
  - Append satu baris transaksi ke sheet milik user
  - Ekstrak Spreadsheet ID dari berbagai format URL Google Sheets
  - Validasi bahwa sheet bisa diakses oleh service account
"""

import re
import os
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class SheetSyncError(Exception):
    """
    Dilempar saat penulisan ke Google Sheet gagal, dengan pesan yang sudah
    ramah-pengguna (siap ditampilkan langsung ke Telegram).

    Sebuah baris HANYA dianggap tersimpan jika worksheet.append_row() sukses
    tanpa exception apa pun — jika gagal (SpreadsheetNotFound, APIError,
    permission denied, dll), exception ini di-raise sehingga caller TIDAK
    boleh melaporkan sukses ke user.
    """
    pass

# ── Konstanta ──────────────────────────────────────────────────────────────────

# Nama worksheet/tab yang dipakai (tab pertama)
WORKSHEET_NAME = "Keuangan"

# Header kolom — urutan ini yang akan dipakai saat append_row
SHEET_HEADERS = ["Tanggal", "Tipe", "Kategori", "Nominal (Rp)", "Catatan", "ID Transaksi"]

# Nama worksheet fallback jika WORKSHEET_NAME tidak ditemukan
FALLBACK_WORKSHEET_INDEX = 0

# ── Regex untuk ekstrak Spreadsheet ID dari URL ────────────────────────────────
# Mendukung format:
#   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0
#   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/
#   SPREADSHEET_ID (langsung ID, bukan URL)
_SHEETS_URL_PATTERN = re.compile(
    r"(?:https?://docs\.google\.com/spreadsheets/d/)?"
    r"([a-zA-Z0-9_-]{20,})"
    r"(?:/.*)?$"
)


# ── Ekstrak ID dari URL ────────────────────────────────────────────────────────

def extract_spreadsheet_id(url_or_id: str) -> Optional[str]:
    """
    Ekstrak Spreadsheet ID dari URL Google Sheets atau ID langsung.

    Args:
        url_or_id: URL lengkap atau ID sheet

    Returns:
        Spreadsheet ID string, atau None jika format tidak valid

    Examples:
        >>> extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFM/edit")
        "1BxiMVs0XRA5nFM"
        >>> extract_spreadsheet_id("1BxiMVs0XRA5nFM")
        "1BxiMVs0XRA5nFM"
    """
    url_or_id = url_or_id.strip()
    match = _SHEETS_URL_PATTERN.search(url_or_id)
    if match:
        return match.group(1)
    return None


# ── Singleton gspread client ────────────────────────────────────────────────────

_gspread_client = None


def _get_client():
    """
    Lazy-init gspread client menggunakan Service Account credentials.
    Import dilakukan di sini agar app tetap bisa start meski gspread
    belum terinstall (fitur sheets opsional).

    Returns:
        gspread.Client instance

    Raises:
        FileNotFoundError: Jika credentials.json tidak ditemukan
        Exception: Jika autentikasi gagal
    """
    global _gspread_client
    if _gspread_client is not None:
        return _gspread_client

    import gspread
    from google.oauth2.service_account import Credentials

    # Load credentials (support cloud deployment)
    from utils.credentials_loader import load_credentials
    try:
        creds_path = load_credentials()
    except FileNotFoundError as e:
        raise FileNotFoundError(str(e))

    # Scope yang dibutuhkan untuk baca/tulis Google Sheets
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    _gspread_client = gspread.authorize(creds)

    logger.info("Google Sheets client berhasil diinisialisasi.")
    return _gspread_client


# ── Akses Worksheet ────────────────────────────────────────────────────────────

def _get_or_create_worksheet(spreadsheet):
    """
    Ambil worksheet dengan nama WORKSHEET_NAME.
    Jika tidak ada, buat worksheet baru dengan nama tersebut
    dan tambahkan baris header otomatis.

    Args:
        spreadsheet: gspread Spreadsheet object

    Returns:
        gspread Worksheet object
    """
    import gspread

    # Coba ambil worksheet dengan nama yang ditentukan
    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        logger.debug(f"Worksheet '{WORKSHEET_NAME}' ditemukan.")
        return worksheet
    except gspread.WorksheetNotFound:
        pass

    # Fallback: coba pakai sheet pertama (Sheet1 / default)
    try:
        worksheet = spreadsheet.get_worksheet(FALLBACK_WORKSHEET_INDEX)
        if worksheet:
            logger.debug(f"Menggunakan worksheet default: '{worksheet.title}'")
            _ensure_headers(worksheet)
            return worksheet
    except Exception:
        pass

    # Buat worksheet baru jika tidak ada sama sekali
    logger.info(f"Membuat worksheet baru: '{WORKSHEET_NAME}'")
    worksheet = spreadsheet.add_worksheet(
        title=WORKSHEET_NAME,
        rows=1000,
        cols=len(SHEET_HEADERS),
    )
    _ensure_headers(worksheet)
    return worksheet


def _ensure_headers(worksheet) -> None:
    """
    Pastikan baris pertama berisi header kolom.
    Hanya menulis jika baris pertama kosong atau bukan header kita.
    """
    try:
        first_row = worksheet.row_values(1)
        # Jika baris pertama sudah mengandung header kita, skip
        if first_row and first_row[0] == SHEET_HEADERS[0]:
            logger.debug("Header sudah ada, skip penulisan header.")
            return

        # Baris pertama kosong atau beda — tulis header
        worksheet.insert_row(SHEET_HEADERS, index=1)
        logger.info("Header kolom berhasil ditulis ke baris pertama.")

    except Exception as e:
        # Non-fatal: header gagal ditulis, tapi transaksi tetap bisa diappend
        logger.warning(f"Gagal memastikan header: {e}")


# ── Fungsi Utama: Append Transaksi ─────────────────────────────────────────────

def append_transaction_to_sheet(
    spreadsheet_id: str,
    transaction,
) -> None:
    """
    Append satu baris transaksi ke Google Sheet.

    Format kolom yang ditulis (sesuai SHEET_HEADERS):
      [Tanggal, Tipe, Kategori, Nominal (Rp), Catatan, ID Transaksi]

    Args:
        spreadsheet_id: ID Google Spreadsheet tujuan
        transaction: objek Transaction (SQLAlchemy model, sudah detached)

    Returns:
        None jika berhasil (baris sudah benar-benar ditulis via append_row()).

    Raises:
        SheetSyncError: jika penulisan gagal karena alasan apa pun — sheet
            tidak ditemukan, akses ditolak, error API Google, atau
            credentials.json hilang. Pesan error sudah diformat siap
            ditampilkan ke user. Caller TIDAK boleh menganggap sukses
            kecuali fungsi ini return tanpa exception.
    """
    import gspread

    try:
        client = _get_client()
    except FileNotFoundError as e:
        msg = f"Kredensial Google Sheets tidak ditemukan di server ({e})."
        logger.error(f"[sheet {spreadsheet_id[:15]}...] {msg}")
        raise SheetSyncError(msg) from e
    except Exception as e:
        msg = f"Gagal terhubung ke Google Sheets API ({type(e).__name__}: {e})."
        logger.error(f"[sheet {spreadsheet_id[:15]}...] {msg}")
        raise SheetSyncError(msg) from e

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as e:
        msg = "Spreadsheet tidak ditemukan (mungkin sudah dihapus, atau ID/link salah)."
        logger.error(f"[sheet {spreadsheet_id[:15]}...] {msg} — {e}")
        raise SheetSyncError(msg) from e
    except gspread.exceptions.APIError as e:
        msg = _format_api_error(e)
        logger.error(f"[sheet {spreadsheet_id[:15]}...] APIError saat membuka sheet: {e}")
        raise SheetSyncError(msg) from e
    except Exception as e:
        msg = f"Gagal membuka spreadsheet ({type(e).__name__}: {e})."
        logger.error(f"[sheet {spreadsheet_id[:15]}...] {msg}")
        raise SheetSyncError(msg) from e

    try:
        worksheet = _get_or_create_worksheet(spreadsheet)

        # Format data sesuai urutan SHEET_HEADERS
        type_label = "Pemasukan" if transaction.type == "income" else "Pengeluaran"
        date_str = (
            transaction.transaction_date.strftime("%d/%m/%Y")
            if transaction.transaction_date
            else ""
        )
        nominal = int(transaction.amount)  # Simpan sebagai integer, tanpa desimal
        description = transaction.description or ""

        row = [
            date_str,           # Tanggal
            type_label,         # Tipe
            transaction.category,  # Kategori
            nominal,            # Nominal (Rp) — angka, bukan string
            description,        # Catatan
            transaction.id,     # ID Transaksi (untuk referensi)
        ]

        # Baris HANYA dianggap tersimpan setelah baris ini sukses TANPA exception.
        worksheet.append_row(
            row,
            value_input_option="USER_ENTERED",  # Agar angka dikenali sebagai number
        )

        logger.info(
            f"[sheet {spreadsheet_id[:10]}...] "
            f"Transaksi #{transaction.id} berhasil diappend ke sheet (append_row sukses)."
        )

    except gspread.exceptions.APIError as e:
        msg = _format_api_error(e)
        logger.error(
            f"Gagal append transaksi #{transaction.id} ke sheet "
            f"'{spreadsheet_id[:15]}...': APIError: {e}"
        )
        raise SheetSyncError(msg) from e
    except Exception as e:
        error_type = type(e).__name__
        logger.error(
            f"Gagal append transaksi #{transaction.id} ke sheet "
            f"'{spreadsheet_id[:15]}...': [{error_type}] {e}"
        )
        raise SheetSyncError(f"{error_type}: {e}") from e


def _format_api_error(e) -> str:
    """Ubah gspread.exceptions.APIError jadi pesan ringkas & ramah-pengguna."""
    try:
        payload = e.response.json().get("error", {})
        status = payload.get("status", "")
        message = payload.get("message", str(e))
        if status == "PERMISSION_DENIED" or "PERMISSION_DENIED" in message:
            return (
                "Akses ditolak (Permission denied). Pastikan sheet sudah di-share "
                "sebagai Editor ke email service account bot."
            )
        return f"Google Sheets API error ({status or 'unknown'}): {message}"
    except Exception:
        return f"Google Sheets API error: {e}"


# ── Validasi Sheet ─────────────────────────────────────────────────────────────

def validate_sheet_access(spreadsheet_id: str) -> tuple[bool, str]:
    """
    Cek apakah service account punya akses ke spreadsheet ini.
    Digunakan saat user mendaftarkan sheet via /setsheet.

    Args:
        spreadsheet_id: ID Google Spreadsheet yang akan divalidasi

    Returns:
        Tuple (success: bool, message: str)
        - (True, nama_sheet) jika berhasil diakses
        - (False, pesan_error) jika gagal
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet_title = spreadsheet.title

        # Pastikan worksheet siap (buat jika perlu)
        _get_or_create_worksheet(spreadsheet)

        logger.info(
            f"Validasi sheet berhasil: '{sheet_title}' (id: {spreadsheet_id[:15]}...)"
        )
        return True, sheet_title

    except FileNotFoundError as e:
        return False, str(e)

    except Exception as e:
        error_name = type(e).__name__

        # Pesan error yang lebih ramah untuk user
        if "PERMISSION_DENIED" in str(e) or "403" in str(e):
            return False, (
                "Bot tidak punya akses ke sheet ini.\n"
                "Pastikan Anda sudah share sheet ke email service account "
                "dengan peran <b>Editor</b>."
            )
        if "NOT_FOUND" in str(e) or "404" in str(e):
            return False, "Sheet tidak ditemukan. Periksa kembali link yang Anda berikan."

        logger.error(f"validate_sheet_access error [{error_name}]: {e}")
        return False, f"Gagal mengakses sheet: {error_name}"
