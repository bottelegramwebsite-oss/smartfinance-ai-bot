"""
services/transaction_service.py
Business logic untuk semua operasi transaksi keuangan.
"""

from datetime import date, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func, extract
from sqlalchemy.exc import SQLAlchemyError

from models.database import get_db_session
from models.transaction import Transaction, User
from services.ai_service import ExtractedTransaction, ExtractionResult, ai_service
from utils.helpers import calculate_summary, today_local
from utils.logger import get_logger

logger = get_logger(__name__)

# ── User Management (SINKRONISASI OTOMATIS WEB & BOT) ─────────────────────────

def upsert_user(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> User:
    with get_db_session() as session:
        # ── 1. Cari record Telegram yang sudah ada ────────────────────────────
        existing_tg_user = session.query(User).filter_by(telegram_id=telegram_id).first()

        # ── 2. Cari orphaned web registration (telegram_id masih None, username cocok) ──
        orphaned_web_user = None
        if username:
            clean_username = username.replace("@", "").lower()
            orphaned_web_user = session.query(User).filter(
                func.lower(func.replace(User.username, "@", "")) == clean_username,
                User.telegram_id == None,
            ).first()

        # ── 3. Kedua record ada → ini adalah skenario sheet-switch ────────────
        if existing_tg_user is not None and orphaned_web_user is not None:
            old_sheet = existing_tg_user.spreadsheet_id
            new_sheet = orphaned_web_user.spreadsheet_id

            if old_sheet != new_sheet:
                # Pengguna mendaftarkan Google Sheet BARU via website.
                # Hapus semua riwayat transaksi lokal agar mulai dari awal.
                deleted_count = (
                    session.query(Transaction)
                    .filter_by(user_id=telegram_id)
                    .delete(synchronize_session="fetch")
                )
                logger.info(
                    f"[Sheet-switch] User {telegram_id} mengganti sheet "
                    f"'{old_sheet}' → '{new_sheet}'. "
                    f"{deleted_count} transaksi lokal dihapus."
                )
                existing_tg_user.spreadsheet_id = new_sheet

            # Hapus orphaned web record untuk mencegah duplikat
            session.delete(orphaned_web_user)
            logger.info(
                f"[Merge] Orphaned web record untuk username '{username}' dihapus "
                f"dan digabungkan ke Telegram ID {telegram_id}."
            )

            user = existing_tg_user

        # ── 4. Hanya orphaned web record yang ada → first-time via web ────────
        elif existing_tg_user is None and orphaned_web_user is not None:
            orphaned_web_user.telegram_id = telegram_id
            orphaned_web_user.first_name = first_name
            logger.info(
                f"[Sync] Akun Web '{username}' berhasil dihubungkan ke Telegram ID {telegram_id}."
            )
            user = orphaned_web_user

        # ── 5. Hanya Telegram record yang ada → pengguna lama, update info ────
        elif existing_tg_user is not None:
            user = existing_tg_user

        # ── 6. Tidak ada record sama sekali → pengguna baru ──────────────────
        else:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            session.add(user)
            logger.info(f"[New user] Pengguna baru dibuat: {username} (ID: {telegram_id}).")

        # ── Selalu update username & nama terkini ─────────────────────────────
        if user.username != username:
            user.username = username
        if first_name and user.first_name != first_name:
            user.first_name = first_name

        session.commit()
        session.refresh(user)
        return user

def set_user_spreadsheet(telegram_id: int, spreadsheet_id: str) -> None:
    with get_db_session() as session:
        web_user = session.query(User).filter(User.spreadsheet_id == spreadsheet_id, User.telegram_id == None).first()
        if web_user:
            web_user.telegram_id = telegram_id
            session.commit()
            return
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user is None:
            user = User(telegram_id=telegram_id, spreadsheet_id=spreadsheet_id)
            session.add(user)
        else:
            user.spreadsheet_id = spreadsheet_id
        session.commit()

def get_user_spreadsheet_id(telegram_id: int) -> Optional[str]:
    with get_db_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user is None:
            return None
        return user.spreadsheet_id

# ── Simpan Transaksi ──────────────────────────────────────────────────────────

def _sync_to_sheets(user_id: int, transaction: Transaction) -> None:
    from services.sheets_service import append_transaction_to_sheet
    spreadsheet_id = get_user_spreadsheet_id(user_id)
    if not spreadsheet_id:
        return
    append_transaction_to_sheet(spreadsheet_id, transaction)

class SheetsWarning(Exception):
    """Sheets sync failed but the transaction WAS saved to the local DB."""
    def __init__(self, tx: "Transaction", message: str):
        super().__init__(message)
        self.tx = tx


def _save_single_extracted(user_id: int, extracted: ExtractedTransaction) -> Transaction:
    with get_db_session() as session:
        tx = Transaction(
            user_id=user_id,
            amount=extracted.amount,
            type=extracted.type,
            category=extracted.category,
            description=extracted.description,
            transaction_date=extracted.transaction_date,
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)
        session.expunge(tx)
        from sqlalchemy.orm import make_transient
        make_transient(tx)

    try:
        _sync_to_sheets(user_id, tx)
    except Exception as e:
        # Transaction stays in local DB; only Sheets sync failed.
        logger.warning(f"Sheets sync gagal untuk transaksi #{tx.id}: {e}")
        raise SheetsWarning(tx, str(e))

    return tx

def save_transactions_from_ai(
    user_id: int,
    extraction_result: ExtractionResult,
) -> Tuple[List[Transaction], List[str]]:
    saved: List[Transaction] = []
    errors: List[str] = []

    if not extraction_result.success or not extraction_result.transactions:
        return saved, errors

    for extracted in extraction_result.transactions:
        try:
            tx = _save_single_extracted(user_id, extracted)
            saved.append(tx)
        except SheetsWarning as e:
            # Transaction is in local DB; only Sheets sync failed.
            saved.append(e.tx)
            errors.append(str(e))
        except Exception as e:
            msg = str(e)
            logger.error(f"Gagal simpan transaksi: {msg}")
            errors.append(msg)

    return saved, errors

def save_manual_transaction(
    user_id: int,
    amount: float,
    tx_type: str,
    category: str,
    description: str = "",
    transaction_date: Optional[date] = None,
) -> Transaction:
    if tx_type not in Transaction.VALID_TYPES:
        raise ValueError(f"Tipe transaksi tidak valid: '{tx_type}'.")
    if amount <= 0:
        raise ValueError(f"Nominal harus lebih dari 0. Diterima: {amount}")
    if transaction_date is None:
        transaction_date = today_local()

    with get_db_session() as session:
        tx = Transaction(
            user_id=user_id,
            amount=amount,
            type=tx_type,
            category=category,
            description=description.strip()[:200],
            transaction_date=transaction_date,
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)
        session.expunge(tx)
        from sqlalchemy.orm import make_transient
        make_transient(tx)

    try:
        _sync_to_sheets(user_id, tx)
    except Exception as e:
        # Transaksi tetap tersimpan di DB lokal; hanya Sheets sync yang gagal.
        logger.warning(f"Sheets sync gagal untuk transaksi manual #{tx.id}: {e}")
        raise SheetsWarning(tx, str(e))

    return tx

def delete_transaction(user_id: int, transaction_id: int) -> bool:
    with get_db_session() as session:
        tx = session.query(Transaction).filter_by(id=transaction_id, user_id=user_id).first()
        if tx is None:
            return False
        session.delete(tx)
        session.commit()
        return True

# ── Query Transaksi ───────────────────────────────────────────────────────────

def get_recent_transactions(user_id: int, limit: int = 10) -> List[Transaction]:
    with get_db_session() as session:
        transactions = session.query(Transaction).filter_by(user_id=user_id).order_by(
            Transaction.transaction_date.desc(), Transaction.created_at.desc()
        ).limit(limit).all()
        session.expunge_all()
        return transactions

def get_transactions_by_month(user_id: int, year: int, month: int) -> List[Transaction]:
    with get_db_session() as session:
        transactions = session.query(Transaction).filter(
            Transaction.user_id == user_id,
            extract("year", Transaction.transaction_date) == year,
            extract("month", Transaction.transaction_date) == month,
        ).order_by(Transaction.transaction_date.asc()).all()
        session.expunge_all()
        return transactions

def get_transactions_by_date_range(user_id: int, start_date: date, end_date: date) -> List[Transaction]:
    with get_db_session() as session:
        transactions = session.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date,
        ).order_by(Transaction.transaction_date.asc()).all()
        session.expunge_all()
        return transactions

# ── Laporan & Summary ─────────────────────────────────────────────────────────

def get_monthly_summary(user_id: int, year: int, month: int) -> dict:
    transactions = get_transactions_by_month(user_id, year, month)
    summary = calculate_summary(transactions)
    by_category: dict = {}
    for tx in transactions:
        key = (tx.type, tx.category)
        if key not in by_category:
            by_category[key] = {"total": 0.0, "count": 0}
        by_category[key]["total"] += tx.amount
        by_category[key]["count"] += 1

    summary["by_category"] = by_category
    summary["year"] = year
    summary["month"] = month
    return summary

def get_overall_summary(user_id: int) -> dict:
    with get_db_session() as session:
        rows = session.query(
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).filter(Transaction.user_id == user_id).group_by(Transaction.type).all()

    totals = {row.type: {"total": row.total or 0, "count": row.count} for row in rows}
    income_data = totals.get("income", {"total": 0, "count": 0})
    expense_data = totals.get("expense", {"total": 0, "count": 0})

    return {
        "total_income": income_data["total"],
        "total_expense": expense_data["total"],
        "balance": income_data["total"] - expense_data["total"],
        "income_count": income_data["count"],
        "expense_count": expense_data["count"],
        "count": income_data["count"] + expense_data["count"],
    }

def get_today_summary(user_id: int) -> dict:
    today = today_local()
    transactions = get_transactions_by_date_range(user_id, today, today)
    return calculate_summary(transactions)

# ── Full Pipeline: Pesan → AI → Simpan ───────────────────────────────────────

def process_natural_language_input(
    user_id: int,
    message: str,
) -> Tuple[List[Transaction], List[str], ExtractionResult]:
    extraction_result = ai_service.extract_transactions(message)
    saved_transactions, errors = save_transactions_from_ai(user_id, extraction_result)
    return saved_transactions, errors, extraction_result