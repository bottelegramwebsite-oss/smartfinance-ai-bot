"""
dashboard/sheets_reader.py
Membaca dan memproses data dari Google Sheet pengguna.
Mereuse auth credentials yang sama dengan bot Telegram.

Kolom yang diharapkan (dari sheets_service.SHEET_HEADERS):
  [Tanggal, Tipe, Kategori, Nominal (Rp), Catatan, ID Transaksi]
"""

import os
import sys
from datetime import datetime, date
from collections import defaultdict
from typing import Optional

# Tambah project root ke path agar bisa import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Mapping nama kolom → index (berdasarkan SHEET_HEADERS di sheets_service) ──
COL_TANGGAL   = 0
COL_TIPE      = 1
COL_KATEGORI  = 2
COL_NOMINAL   = 3
COL_CATATAN   = 4
COL_ID        = 5


def _get_gspread_client():
    """Init gspread client dengan Service Account credentials."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
    # Resolve path relatif terhadap root project
    if not os.path.isabs(creds_path):
        creds_path = os.path.join(os.path.dirname(__file__), "..", creds_path)

    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"credentials.json tidak ditemukan di: {creds_path}"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    return gspread.authorize(creds)


def _parse_nominal(raw: str) -> float:
    """
    Parse nilai nominal dari berbagai format yang mungkin ada di sheet.
    Contoh: "30000", "30,000", "Rp 30.000", "1500000"
    """
    if not raw:
        return 0.0
    # Hapus semua karakter non-digit kecuali titik dan koma
    cleaned = str(raw).replace("Rp", "").replace(" ", "").strip()
    # Format Indonesia: titik = pemisah ribuan, koma = desimal
    # Format angka: hapus titik dan koma jika keduanya ada
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "." in cleaned and cleaned.count(".") > 1:
        # 1.500.000 → 1500000
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        # 1,500,000 → 1500000 atau 30,5 → 30.5
        parts = cleaned.split(",")
        if len(parts[-1]) == 3:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(raw: str) -> Optional[date]:
    """
    Parse tanggal dari berbagai format yang mungkin ada di sheet.
    Format yang didukung: dd/mm/yyyy, yyyy-mm-dd, dd-mm-yyyy
    """
    if not raw:
        return None
    formats = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning(f"Format tanggal tidak dikenali: '{raw}'")
    return None


def extract_sheet_id(url_or_id: str) -> str:
    """Ekstrak Spreadsheet ID dari URL atau ID langsung."""
    import re
    url_or_id = url_or_id.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})", url_or_id)
    if match:
        return match.group(1)
    # Kalau tidak ada /d/, anggap sudah ID langsung
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url_or_id):
        return url_or_id
    raise ValueError(f"Format URL/ID Google Sheet tidak valid: '{url_or_id}'")


def read_sheet_data(spreadsheet_id: str) -> dict:
    """
    Baca seluruh data dari Google Sheet dan kembalikan dalam bentuk
    dictionary terstruktur yang siap dikonsumsi oleh frontend.

    Returns:
        {
            "sheet_title": str,
            "transactions": [ {tanggal, tipe, kategori, nominal, catatan, id} ],
            "summary": {
                "total_income": float,
                "total_expense": float,
                "balance": float,
                "income_count": int,
                "expense_count": int,
            },
            "by_category": [ {kategori, tipe, total, count} ],
            "monthly_trend": [ {bulan, pemasukan, pengeluaran} ],   # 6 bulan terakhir
            "recent_transactions": [ ... ]  # 10 terbaru
        }
    """
    client = _get_gspread_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    sheet_title = spreadsheet.title

    # Ambil worksheet pertama yang ada datanya
    worksheet = None
    for ws in spreadsheet.worksheets():
        if ws.row_count > 1:
            worksheet = ws
            break
    if worksheet is None:
        worksheet = spreadsheet.get_worksheet(0)

    all_values = worksheet.get_all_values()

    if not all_values or len(all_values) < 2:
        return _empty_response(sheet_title)

    # Baris pertama adalah header — skip
    rows = all_values[1:]

    transactions = []
    for row in rows:
        # Pad baris agar minimal punya 5 kolom
        while len(row) < 5:
            row.append("")

        raw_date    = row[COL_TANGGAL].strip()
        tipe        = row[COL_TIPE].strip().lower()
        kategori    = row[COL_KATEGORI].strip()
        raw_nominal = row[COL_NOMINAL]
        catatan     = row[COL_CATATAN].strip() if len(row) > COL_CATATAN else ""
        tx_id       = row[COL_ID].strip() if len(row) > COL_ID else ""

        # Skip baris kosong
        if not raw_date and not raw_nominal:
            continue

        nominal = _parse_nominal(raw_nominal)
        tx_date = _parse_date(raw_date)

        # Normalisasi tipe: "pemasukan" / "pengeluaran" → "income" / "expense"
        if tipe in ("pemasukan", "income", "masuk"):
            tipe_norm = "income"
        else:
            tipe_norm = "expense"

        transactions.append({
            "id":        tx_id,
            "tanggal":   raw_date,
            "tanggal_dt": tx_date.isoformat() if tx_date else None,
            "tipe":      tipe_norm,
            "kategori":  kategori,
            "nominal":   nominal,
            "catatan":   catatan,
        })

    if not transactions:
        return _empty_response(sheet_title)

    # ── Summary ────────────────────────────────────────────────────────────────
    total_income  = sum(t["nominal"] for t in transactions if t["tipe"] == "income")
    total_expense = sum(t["nominal"] for t in transactions if t["tipe"] == "expense")

    summary = {
        "total_income":   total_income,
        "total_expense":  total_expense,
        "balance":        total_income - total_expense,
        "income_count":   sum(1 for t in transactions if t["tipe"] == "income"),
        "expense_count":  sum(1 for t in transactions if t["tipe"] == "expense"),
    }

    # ── Breakdown per Kategori ─────────────────────────────────────────────────
    cat_map: dict = {}
    for t in transactions:
        key = (t["kategori"], t["tipe"])
        if key not in cat_map:
            cat_map[key] = {"total": 0.0, "count": 0}
        cat_map[key]["total"] += t["nominal"]
        cat_map[key]["count"] += 1

    by_category = [
        {
            "kategori": k[0],
            "tipe":     k[1],
            "total":    v["total"],
            "count":    v["count"],
        }
        for k, v in sorted(cat_map.items(), key=lambda x: -x[1]["total"])
    ]

    # ── Monthly Trend (6 bulan terakhir) ───────────────────────────────────────
    monthly: dict = defaultdict(lambda: {"pemasukan": 0.0, "pengeluaran": 0.0})
    for t in transactions:
        if not t["tanggal_dt"]:
            continue
        try:
            d = date.fromisoformat(t["tanggal_dt"])
            key = f"{d.year}-{d.month:02d}"
            if t["tipe"] == "income":
                monthly[key]["pemasukan"] += t["nominal"]
            else:
                monthly[key]["pengeluaran"] += t["nominal"]
        except Exception:
            continue

    # Ambil 6 bulan terakhir, urutkan
    BULAN_ID = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                "Jul", "Ags", "Sep", "Okt", "Nov", "Des"]
    sorted_months = sorted(monthly.keys())[-6:]
    monthly_trend = []
    for m in sorted_months:
        year, month = m.split("-")
        monthly_trend.append({
            "bulan":       f"{BULAN_ID[int(month)]} {year}",
            "pemasukan":   monthly[m]["pemasukan"],
            "pengeluaran": monthly[m]["pengeluaran"],
        })

    # ── Recent Transactions (10 terbaru) ──────────────────────────────────────
    # Urutkan berdasarkan tanggal terbaru, ambil 10
    sorted_tx = sorted(
        [t for t in transactions if t["tanggal_dt"]],
        key=lambda x: x["tanggal_dt"],
        reverse=True,
    )[:10]

    logger.info(
        f"Sheet '{sheet_title}' dibaca: {len(transactions)} transaksi, "
        f"income={total_income:,.0f}, expense={total_expense:,.0f}"
    )

    return {
        "sheet_title":         sheet_title,
        "transactions":        transactions,
        "summary":             summary,
        "by_category":         by_category,
        "monthly_trend":       monthly_trend,
        "recent_transactions": sorted_tx,
    }


def _empty_response(sheet_title: str) -> dict:
    """Kembalikan struktur kosong saat sheet belum punya data."""
    return {
        "sheet_title":         sheet_title,
        "transactions":        [],
        "summary": {
            "total_income":  0,
            "total_expense": 0,
            "balance":       0,
            "income_count":  0,
            "expense_count": 0,
        },
        "by_category":         [],
        "monthly_trend":       [],
        "recent_transactions": [],
    }
