"""
models/database.py
Setup koneksi database SQLite menggunakan SQLAlchemy.
Menyediakan session factory dan fungsi inisialisasi tabel.
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from config import settings
from models.transaction import Base
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────

def _build_engine() -> Engine:
    """
    Buat SQLAlchemy engine untuk SQLite.
    Pastikan direktori data ada sebelum membuat file database.
    """
    db_path = settings.DATABASE_PATH

    # Buat direktori jika belum ada
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={
            "check_same_thread": False,  # Diperlukan untuk SQLite + async
            "timeout": 30,               # Tunggu hingga 30 detik jika DB sedang terkunci
        },
        echo=False,   # Set True untuk debug SQL queries
    )

    # Aktifkan foreign keys di SQLite (off by default)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        cursor.close()

    logger.info(f"Database engine dibuat: {db_path}")
    return engine


# Singleton engine dan session factory
_engine: Engine = None
_SessionFactory: sessionmaker = None


def get_engine() -> Engine:
    """Kembalikan singleton engine, buat jika belum ada."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    """Kembalikan singleton session factory."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            # Penting: tanpa ini, ORM objects yang dikembalikan dari
            # `with get_db_session() as session: ... return obj` menjadi
            # "detached" setelah session ditutup — attribute apapun yang
            # diakses sesudahnya (mis. user.telegram_id) melempar
            # DetachedInstanceError karena SQLAlchemy meng-expire semua
            # atribut setelah commit secara default.
            expire_on_commit=False,
        )
    return _SessionFactory


# ── Context Manager ───────────────────────────────────────────────────────────

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager untuk database session.

    Penggunaan:
        with get_db_session() as session:
            session.add(obj)
            session.commit()
    """
    SessionFactory = get_session_factory()
    session: Session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error, rollback dilakukan: {e}")
        raise
    finally:
        session.close()


# ── Inisialisasi ──────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Buat semua tabel yang didefinisikan di models jika belum ada.
    Dipanggil sekali saat aplikasi startup.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database diinisialisasi. Semua tabel sudah siap.")


def close_db() -> None:
    """Tutup koneksi database saat aplikasi shutdown."""
    global _engine, _SessionFactory
    if _engine:
        _engine.dispose()
        _engine = None
        _SessionFactory = None
        logger.info("Koneksi database ditutup.")
