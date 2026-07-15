"""
dashboard/main.py
FastAPI backend untuk SmartFinance Dashboard.

Endpoints:
  GET  /                          → serve index.html
  GET  /api/health                → health check
  POST /api/connect               → hubungkan/ambil dashboard via username Telegram (+ sheet_url opsional)
  POST /api/register              → daftar user baru via website (legacy)
  POST /api/login                 → login user yang sudah terdaftar (legacy)
  GET  /api/dashboard?token=...   → baca sheet data berdasarkan web_token
  GET  /api/sheet?url=...         → baca sheet langsung via URL (fallback)
  GET  /api/user-sheet?telegram_id=... → baca sheet via Telegram ID
  GET  /api/users                 → list semua user terdaftar
"""

import os
import sys
import secrets
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func

from dashboard.sheets_reader import read_sheet_data, extract_sheet_id
from services.sheets_service import validate_sheet_access
from models.database import get_db_session, init_db
from models.transaction import User
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Init DB saat startup ──────────────────────────────────────────────────────
init_db()

# ── Inisialisasi App ──────────────────────────────────────────────────────────
app = FastAPI(
    title="SmartFinance Dashboard API",
    version="2.0.0",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Request / Response Schemas ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str                              # Nama tampilan user
    sheet_url: str                         # URL Google Sheet milik user
    telegram_username: Optional[str] = None  # @username Telegram (opsional, untuk auto-link)


class LoginRequest(BaseModel):
    sheet_url: str      # URL Google Sheet (dipakai sebagai identifier login)


class ConnectRequest(BaseModel):
    username: str                      # @username Telegram — identifier utama, wajib diisi
    name: Optional[str] = None         # Nama tampilan (opsional)
    sheet_url: Optional[str] = None    # URL Google Sheet (opsional jika sudah /setsheet di bot)


# ── Helper: bangun response data sheet + info user ────────────────────────────

def _sheet_response(user: User, spreadsheet_id: str) -> dict:
    """Baca sheet dan gabungkan dengan info user."""
    data = read_sheet_data(spreadsheet_id)
    data["user_name"]  = user.name
    data["web_token"]  = user.web_token
    data["user_id"]    = user.id
    return data


def _handle_sheet_error(e: Exception) -> None:
    """Terjemahkan error Google API ke HTTPException yang sesuai."""
    s = str(e)
    if "PERMISSION_DENIED" in s or "403" in s:
        raise HTTPException(
            status_code=403,
            detail=(
                "Bot belum punya akses ke sheet ini. "
                "Pastikan sheet sudah di-share ke email service account "
                "dengan peran Editor."
            ),
        )
    if "NOT_FOUND" in s or "404" in s:
        raise HTTPException(status_code=404, detail="Google Sheet tidak ditemukan. Periksa URL-nya.")
    if "credentials" in s.lower():
        raise HTTPException(status_code=500, detail="Konfigurasi server belum lengkap (credentials.json).")
    logger.error(f"Sheet error [{type(e).__name__}]: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail=f"Gagal membaca sheet: {type(e).__name__}")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_path, media_type="text/html")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "SmartFinance Dashboard API v2"}


# ── POST /api/register ────────────────────────────────────────────────────────

@app.post("/api/register")
async def register(body: RegisterRequest):
    """
    Daftarkan user baru via website.

    Flow:
      1. Validasi & ekstrak spreadsheet_id dari URL
      2. Cek apakah sheet sudah bisa diakses service account
      3. Cek apakah sheet sudah dipakai user lain
      4. Buat user baru + generate web_token
      5. Kembalikan token + data dashboard

    Errors:
      400 — URL tidak valid / nama kosong
      403 — Sheet tidak bisa diakses
      409 — Sheet sudah terdaftar
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama tidak boleh kosong.")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Nama terlalu panjang (maks 100 karakter).")

    # Ekstrak spreadsheet ID
    try:
        spreadsheet_id = extract_sheet_id(body.sheet_url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="URL Google Sheet tidak valid. Pastikan formatnya benar.",
        )

    # Validasi akses ke sheet
    try:
        ok, info = validate_sheet_access(spreadsheet_id)
    except Exception as e:
        _handle_sheet_error(e)
        return  # unreachable, buat type checker

    if not ok:
        raise HTTPException(status_code=403, detail=info)

    sheet_title = info  # validate_sheet_access mengembalikan nama sheet jika sukses

    # Normalisasi @username Telegram (opsional) — dipakai untuk auto-link
    # ke akun Telegram yang sudah ada (misal user sudah pernah /start bot).
    telegram_username = None
    if body.telegram_username:
        telegram_username = body.telegram_username.strip().lstrip("@").lower() or None

    with get_db_session() as session:
        # Cek apakah sheet sudah dipakai user lain
        existing = session.query(User).filter_by(spreadsheet_id=spreadsheet_id).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Sheet ini sudah terdaftar atas nama '{existing.name}'. "
                    "Gunakan tombol Masuk jika ini akun kamu."
                ),
            )

        linked_user = None
        if telegram_username:
            # Cari akun yang sudah terhubung ke Telegram dengan username yang sama —
            # jika ada, langsung simpan spreadsheet_id di akun itu sehingga bot bisa
            # langsung menemukannya via telegram_id (tanpa perlu /setsheet lagi).
            linked_user = (
                session.query(User)
                .filter(
                    User.telegram_id.isnot(None),
                    func.lower(User.username) == telegram_username,
                )
                .first()
            )

        if linked_user:
            web_token = linked_user.web_token or secrets.token_hex(32)
            linked_user.display_name = name
            linked_user.spreadsheet_id = spreadsheet_id
            linked_user.web_token = web_token
            session.commit()
            session.refresh(linked_user)
            user_id   = linked_user.id
            user_name = linked_user.name
            logger.info(
                f"User terdaftar via web & langsung ter-link ke Telegram @{telegram_username} "
                f"(id={user_id}) sheet='{sheet_title}'"
            )
        else:
            # Belum pernah /start bot dengan username ini (atau tidak diisi) —
            # buat akun web biasa. Akan otomatis ter-link saat user /start atau
            # /setsheet di bot dengan username/URL yang sama.
            web_token = secrets.token_hex(32)
            user = User(
                telegram_id=None,
                username=telegram_username,
                display_name=name,
                spreadsheet_id=spreadsheet_id,
                web_token=web_token,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id   = user.id
            user_name = user.name
            logger.info(f"User baru terdaftar via web: '{name}' sheet='{sheet_title}'")

    try:
        data = read_sheet_data(spreadsheet_id)
        data["user_name"] = user_name
        data["web_token"] = web_token
        data["user_id"]   = user_id
        return JSONResponse(content=data)
    except Exception as e:
        _handle_sheet_error(e)


# ── POST /api/connect ─────────────────────────────────────────────────────────

@app.post("/api/connect")
async def connect(body: ConnectRequest):
    """
    Endpoint tunggal yang menyatukan alur website + Telegram, dikunci oleh
    @username Telegram (bukan URL sheet) sebagai identifier utama.

    Flow:
      1. Normalisasi username (buang '@', lowercase) — wajib diisi.
      2. Cari user yang sudah ada di DB berdasarkan username (dibuat baik
         dari /start bot, /setsheet, maupun pendaftaran web sebelumnya).
      3a. Jika sheet_url diisi:
          - Validasi & ekstrak spreadsheet_id, cek akses service account.
          - Cek sheet belum dipakai username lain (409 jika bentrok).
          - Simpan/perbarui spreadsheet_id user ini (baik user baru atau lama).
            → Ini otomatis membuat data terlihat dari Telegram juga, karena
              bot & website membaca tabel `users` SQLite yang sama.
      3b. Jika sheet_url TIDAK diisi:
          - Ambil spreadsheet_id yang sudah tersimpan (mis. via /setsheet
            di Telegram). 404 jika user/sheet belum ada sama sekali.
      4. Baca data asli dari Google Sheet dan kembalikan sebagai JSON.

    Errors:
      400 — username kosong / URL sheet tidak valid
      403 — sheet tidak bisa diakses oleh service account
      404 — username belum pernah setsheet & sheet_url juga tidak diisi
      409 — sheet_url sudah dipakai username lain
    """
    username = body.username.strip().lstrip("@").lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username Telegram wajib diisi.")

    display_name = body.name.strip() if body.name else None
    sheet_url = body.sheet_url.strip() if body.sheet_url else None

    with get_db_session() as session:
        user = (
            session.query(User)
            .filter(func.lower(User.username) == username)
            .first()
        )

        if sheet_url:
            # ── Kasus: user memberikan link sheet (pertama kali, atau update) ──
            try:
                spreadsheet_id = extract_sheet_id(sheet_url)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="URL Google Sheet tidak valid. Pastikan formatnya benar.",
                )

            try:
                ok, info = validate_sheet_access(spreadsheet_id)
            except Exception as e:
                _handle_sheet_error(e)
                return  # unreachable, buat type checker

            if not ok:
                raise HTTPException(status_code=403, detail=info)

            # Cek sheet ini sudah dipakai user lain (username berbeda)
            sheet_owner = session.query(User).filter_by(spreadsheet_id=spreadsheet_id).first()
            if sheet_owner and (user is None or sheet_owner.id != user.id):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Sheet ini sudah terdaftar atas nama '{sheet_owner.name}'. "
                        "Gunakan username Telegram yang benar untuk sheet ini."
                    ),
                )

            if user is None:
                # Belum pernah interaksi dengan bot maupun website — buat akun baru
                user = User(
                    telegram_id=None,
                    username=username,
                    display_name=display_name,
                    spreadsheet_id=spreadsheet_id,
                    web_token=secrets.token_hex(32),
                )
                session.add(user)
                logger.info(f"User baru dibuat via /api/connect: @{username}")
            else:
                # Sudah ada (mungkin dari /start bot) — link/perbarui sheet-nya
                user.spreadsheet_id = spreadsheet_id
                if display_name:
                    user.display_name = display_name
                if not user.web_token:
                    user.web_token = secrets.token_hex(32)
                logger.info(f"Sheet di-link/diperbarui via /api/connect untuk @{username}")

            session.commit()
            session.refresh(user)
        else:
            # ── Kasus: user hanya mengisi username, sheet_url diharapkan sudah
            #    tersimpan sebelumnya (dari /setsheet di Telegram) ──────────────
            if user is None or not user.spreadsheet_id:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Belum ada Google Sheet untuk username ini. "
                        "Daftarkan sheet dulu lewat /setsheet di bot Telegram, "
                        "atau isi link sheet-nya di form ini."
                    ),
                )
            if display_name and not user.display_name:
                user.display_name = display_name
            if not user.web_token:
                user.web_token = secrets.token_hex(32)
            session.commit()
            session.refresh(user)

        spreadsheet_id = user.spreadsheet_id
        user_name      = user.name
        user_id        = user.id
        web_token      = user.web_token

    try:
        data = read_sheet_data(spreadsheet_id)
        data["user_name"] = user_name
        data["web_token"] = web_token
        data["user_id"]   = user_id
        return JSONResponse(content=data)
    except Exception as e:
        _handle_sheet_error(e)


# ── POST /api/login ───────────────────────────────────────────────────────────

@app.post("/api/login")
async def login(body: LoginRequest):
    """
    Login user yang sudah terdaftar via URL sheet mereka.

    URL sheet berfungsi sebagai identifier unik — hanya pemilik
    sheet yang bisa menggunakannya karena mereka yang share ke bot.

    Flow:
      1. Ekstrak spreadsheet_id dari URL
      2. Cari user di DB berdasarkan spreadsheet_id
      3. Kembalikan token + data dashboard

    Errors:
      400 — URL tidak valid
      404 — Sheet belum terdaftar (arahkan ke daftar)
    """
    try:
        spreadsheet_id = extract_sheet_id(body.sheet_url)
    except ValueError:
        raise HTTPException(status_code=400, detail="URL Google Sheet tidak valid.")

    with get_db_session() as session:
        user = session.query(User).filter_by(spreadsheet_id=spreadsheet_id).first()
        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Sheet ini belum terdaftar. Silakan klik Daftar terlebih dahulu.",
            )
        # Baca semua field yang dibutuhkan SEBELUM expunge
        user_name       = user.name
        user_id         = user.id
        web_token       = user.web_token
        sheet_id        = user.spreadsheet_id

    logger.info(f"Login via web: '{user_name}' (id={user_id})")

    # Jika user belum punya web_token (didaftar via Telegram), buat satu
    if not web_token:
        import secrets as _sec
        web_token = _sec.token_hex(32)
        with get_db_session() as session:
            u = session.query(User).filter_by(id=user_id).first()
            if u:
                u.web_token = web_token
                session.commit()

    try:
        data = read_sheet_data(sheet_id)
        data["user_name"] = user_name
        data["web_token"] = web_token
        data["user_id"]   = user_id
        return JSONResponse(content=data)
    except Exception as e:
        _handle_sheet_error(e)


# ── GET /api/dashboard ────────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def get_dashboard(token: str = Query(..., description="web_token dari localStorage")):
    """
    Ambil data dashboard berdasarkan token sesi yang tersimpan di browser.
    Dipakai saat halaman di-refresh agar user tidak perlu login ulang.
    """
    with get_db_session() as session:
        user = session.query(User).filter_by(web_token=token).first()
        if user is None:
            raise HTTPException(status_code=401, detail="Sesi tidak valid atau sudah kedaluwarsa.")
        # Baca semua field sebelum session tutup
        spreadsheet_id = user.spreadsheet_id
        user_name      = user.name
        user_id        = user.id
        web_token_val  = user.web_token

    if not spreadsheet_id:
        raise HTTPException(status_code=404, detail="Sheet belum terdaftar untuk akun ini.")

    try:
        data = read_sheet_data(spreadsheet_id)
        data["user_name"] = user_name
        data["web_token"] = web_token_val
        data["user_id"]   = user_id
        return JSONResponse(content=data)
    except Exception as e:
        _handle_sheet_error(e)


# ── GET /api/sheet (fallback via URL langsung) ────────────────────────────────

@app.get("/api/sheet")
async def get_sheet_data(url: str = Query(..., description="URL atau ID Google Sheet")):
    try:
        spreadsheet_id = extract_sheet_id(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return JSONResponse(content=read_sheet_data(spreadsheet_id))
    except Exception as e:
        _handle_sheet_error(e)


# ── GET /api/user-sheet (via Telegram ID) ────────────────────────────────────

@app.get("/api/user-sheet")
async def get_user_sheet(telegram_id: int = Query(...)):
    with get_db_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"Telegram ID {telegram_id} belum terdaftar.")
        spreadsheet_id = user.spreadsheet_id
        session.expunge(user)

    if not spreadsheet_id:
        raise HTTPException(status_code=404, detail="Belum mendaftarkan Google Sheet.")

    try:
        return JSONResponse(content=_sheet_response(user, spreadsheet_id))
    except Exception as e:
        _handle_sheet_error(e)


# ── GET /api/users ────────────────────────────────────────────────────────────

@app.get("/api/users")
async def list_users():
    with get_db_session() as session:
        users = session.query(User).all()
        result = [
            {
                "id":          u.id,
                "name":        u.name,
                "telegram_id": u.telegram_id,
                "has_sheet":   bool(u.spreadsheet_id),
            }
            for u in users
        ]
    return {"users": result, "count": len(result)}
