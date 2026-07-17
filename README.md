# 🚀 SmartFinance AI - Bot Telegram & Web Dashboard

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Google_Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/SQLite-Database-003B57?style=for-the-badge&logo=sqlite&logoColor=white"/>
</p>

<p align="center">
  <strong>Project Tugas Akhir - Penerapan Kecerdasan Buatan (AI)</strong><br/>
  Teknik Industri — Universitas Stikubank (Unisbank) Semarang
</p>

---

## 🌐 URL Aplikasi (Live Deployment)

| Platform | URL |
|---|---|
| 🖥️ Web Dashboard | [https://smartfinanceai--bottelegramwebs.replit.app](https://smartfinanceai--bottelegramwebs.replit.app) |
| 🤖 Bot Telegram | [@SmartFinanceAIBot](https://t.me/SmartFinanceAIBot) |

---

## 👥 Anggota Kelompok: smartfinanceai

| Nama | NIM | Program Studi |
|---|---|---|
| Naufal Ilhamul Lutfi | 24.04.51.0006 | Teknik Industri UNISBANK |
| Quinamora Divi N | 24.04.51.0010 | Teknik Industri UNISBANK |
| Bintang Teo Cahya R | 24.04.51.0012 | Teknik Industri UNISBANK |
| Lailatun Najwa M | 24.04.51.0014 | Teknik Industri UNISBANK |

---

## ✨ Features

- 💬 **Natural Language Input** — Ketik `"Makan siang 30rb"` atau `"Gaji bulan ini 5jt"` dan AI langsung mengekstrak transaksi secara otomatis
- 🤖 **Google Gemini AI** — Ekstraksi cerdas dengan *Heuristic Local Fallback Engine* untuk keandalan tinggi
- 📊 **FastAPI Web Dashboard** — Pantau dan kelola keuangan dari browser
- 📈 **Google Sheets Sync** — Sinkronisasi data transaksi ke Google Sheet secara real-time
- 🗂️ **Transaction History** — Browse, filter, dan hapus riwayat transaksi
- 📅 **Monthly Reports** — Laporan bulanan dengan breakdown per kategori
- 🗑️ **One-command History Clear** — `/clear` menghapus semua riwayat lokal seketika
- 🔔 **Auto-notification** — Telegram mengonfirmasi saat Google Sheet berhasil terhubung via dashboard

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | `python-telegram-bot` 21.9 (async polling) |
| AI extraction | Google Gemini 1.5 Flash via HTTP (3-second fast-fail) |
| Fallback engine | Heuristic Local Fallback Engine (rule-based, zero-dependency) |
| Web dashboard | FastAPI + Uvicorn (port 5000) |
| Primary database | SQLite via SQLAlchemy (`connect_args={"timeout": 30}`) |
| Secondary storage | Google Sheets via `gspread` + service account |
| HTTP client | `httpx` |
| Config | `python-dotenv` |

---

## 🏗️ Hybrid Database Architecture

SmartFinance AI menggunakan arsitektur **hybrid database** dua lapis:

```
┌─────────────────────────────────────────────────────────┐
│                    USER INPUT (Telegram)                 │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              AI LAYER (Google Gemini 1.5 Flash)         │
│  • Single-attempt, 3-second timeout (fast-fail)         │
│  • On failure → Heuristic Local Fallback Engine         │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│           PRIMARY: SQLite (via SQLAlchemy)               │
│  • connect_args={"timeout": 30}  ← prevents DB locking  │
│  • expire_on_commit=False  ← prevents DetachedInstance  │
│  • Local, fast, always-available                        │
└────────────────────────┬────────────────────────────────┘
                         │  (optional sync)
                         ▼
┌─────────────────────────────────────────────────────────┐
│           SECONDARY: Google Sheets (gspread)            │
│  • Linked per-user via /setsheet command                │
│  • Service account auth (GOOGLE_CREDENTIALS_BASE64)     │
│  • Live spreadsheet copy for sharing & analysis         │
└─────────────────────────────────────────────────────────┘
```

### Key reliability decisions:
- **SQLite `timeout: 30`** — prevents `OperationalError: database is locked` under concurrent dashboard + bot writes
- **Google Gemini fast-fail (3s)** — if Gemini times out or returns an error, the system immediately falls back to the local heuristic engine without retrying, so users never wait
- **Heuristic Local Fallback Engine** — a rule-based parser that handles common Indonesian currency patterns (`rb`, `jt`, `ribu`, `juta`) and transaction keywords without any external API call

---

## 📁 Project Structure

```
smartfinance-ai-bot/
├── main.py                  # Entry point — starts bot + dashboard
├── bot/
│   ├── handlers.py          # All Telegram command & message handlers
│   └── keyboards.py         # Inline keyboard helpers
├── config/
│   └── settings.py          # Environment variable loading
├── dashboard/
│   └── main.py              # FastAPI routes and Telegram notify helper
├── models/
│   └── database.py          # SQLAlchemy models & session factory
├── services/
│   ├── ai_service.py        # Gemini extraction + heuristic fallback
│   ├── transaction_service.py # CRUD helpers for transactions & users
│   └── sheets_service.py    # Google Sheets read/write logic
├── utils/
│   └── logger.py            # Centralized logging setup
├── data/                    # SQLite database (auto-created, git-ignored)
├── .env.example             # Environment variable template
├── requirements.txt
└── README.md
```

---

## ⚙️ Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/bottelegramwebsite-oss/smartfinance-ai-bot.git
cd smartfinance-ai-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` dan isi dengan nilai yang sebenarnya (lihat [Environment Variables](#-environment-variables) di bawah).

### 4. Run the application

```bash
python main.py
```

Perintah ini menjalankan bot Telegram (polling) dan dashboard FastAPI di port 5000 secara bersamaan dalam satu proses.

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token bot dari [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | ✅ | API key dari [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `SESSION_SECRET` | ✅ | String acak untuk menandatangani session cookie dashboard |
| `GOOGLE_CREDENTIALS_BASE64` | ✅ | Isi file JSON service account Google, di-encode Base64 |
| `GROQ_API_KEY` | ⚠️ | Dicadangkan — dibutuhkan `config/settings.py` tapi belum dipakai |
| `DASHBOARD_URL` | ➖ | URL publik dashboard (default: `https://smartfinanceai--bottelegramwebs.replit.app`) |

> Encode service account key: `base64 -w 0 credentials.json`

Lihat `.env.example` untuk nilai placeholder dan komentar lengkap.

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Registrasi dan panduan onboarding |
| `/help` | Tampilkan semua perintah yang tersedia |
| `/summary` | Ringkasan keuangan harian dan all-time |
| `/history` | 10 transaksi terakhir |
| `/monthly` | Laporan bulanan dengan breakdown kategori |
| `/add` | Tambah transaksi secara manual |
| `/delete` | Hapus transaksi berdasarkan ID |
| `/setsheet` | Hubungkan Google Sheet untuk sinkronisasi |
| `/clear` | Hapus seluruh riwayat transaksi lokal |

**Natural language** — cukup kirim pesan seperti:
- `"Beli kopi 25000"`
- `"Terima gaji 4.5 juta"`
- `"Bensin motor 50rb"`

---

## 🌐 Dashboard API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Antarmuka web utama |
| `POST` | `/api/connect` | Hubungkan akun Telegram ke Google Sheet |
| `GET` | `/api/dashboard` | Ambil data sheet via web token |
| `POST` | `/api/register` | Registrasi pengguna berbasis web |
| `POST` | `/api/login` | Login berbasis web |
| `GET` | `/api/user-sheet` | Ambil data sheet untuk Telegram ID tertentu |

---

## 🚀 Deployment

Project ini dikonfigurasi untuk **Replit Reserved VM** agar bot polling tetap aktif terus-menerus.

```toml
# replit.toml
deploymentTarget = "vm"
run = ["python", "main.py"]
```

> ⚠️ Jangan jalankan dev workflow dan deployed VM secara bersamaan dengan `TELEGRAM_BOT_TOKEN` yang sama — Telegram hanya mengizinkan satu koneksi polling aktif per bot.

---

## 🔒 Security Notes

- Jangan pernah commit file `.env` asli — sudah terdaftar di `.gitignore`
- `GOOGLE_CREDENTIALS_BASE64` memberikan akses ke akun Google; rotate key jika terekspos
- `SESSION_SECRET` harus berupa string acak kriptografis (minimum 32 karakter)

---

## 📄 Lisensi

Project ini dibuat untuk keperluan akademis sebagai Tugas Akhir Semester (UAS).  
© 2025 Kelompok smartfinanceai — Universitas Stikubank (Unisbank) Semarang. All rights reserved.
