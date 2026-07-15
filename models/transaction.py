"""
models/transaction.py
Definisi model SQLAlchemy untuk tabel transaksi dan users.
"""

from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Date,
    DateTime, Text, CheckConstraint, Index
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    """Model untuk menyimpan data pengguna."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=True)   # nullable: bisa daftar via web
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    # Nama yang diisi saat daftar via website
    display_name = Column(String(150), nullable=True, default=None)
    # ID Google Spreadsheet milik user ini (diset via /setsheet atau website)
    spreadsheet_id = Column(String(200), nullable=True, default=None)
    # Token sesi untuk login via website (UUID, disimpan di localStorage)
    web_token = Column(String(64), unique=True, nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @property
    def name(self) -> str:
        """Nama tampilan user — prioritas: display_name > first_name > username > telegram_id."""
        return self.display_name or self.first_name or self.username or str(self.telegram_id or self.id)

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.name} telegram={self.telegram_id}>"


class Transaction(Base):
    """Model untuk menyimpan transaksi keuangan."""

    __tablename__ = "transactions"

    # Tipe transaksi yang valid
    VALID_TYPES = ("income", "expense")

    # Kategori pemasukan
    INCOME_CATEGORIES = [
        "Gaji", "Investasi", "Freelance", "Bonus",
        "Hadiah", "Penjualan", "Lainnya"
    ]

    # Kategori pengeluaran
    EXPENSE_CATEGORIES = [
        "Makanan & Minuman", "Transportasi", "Belanja",
        "Tagihan & Utilitas", "Hiburan", "Kesehatan",
        "Pendidikan", "Cicilan", "Lainnya"
    ]

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)           # telegram_id user
    amount = Column(Float, nullable=False)
    type = Column(
        String(10),
        CheckConstraint("type IN ('income', 'expense')", name="chk_type"),
        nullable=False
    )
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    transaction_date = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Index untuk query yang sering dipakai
    __table_args__ = (
        Index("idx_user_date", "user_id", "transaction_date"),
        Index("idx_user_type", "user_id", "type"),
    )

    def to_dict(self) -> dict:
        """Konversi model ke dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": self.amount,
            "type": self.type,
            "category": self.category,
            "description": self.description,
            "transaction_date": self.transaction_date.isoformat() if self.transaction_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} type={self.type} "
            f"amount={self.amount} category={self.category}>"
        )
