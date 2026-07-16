# 🤖 SmartFinance AI Bot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/Telegram-Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Google_Gemini-AI-4285F4?style=for-the-badge&logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/SQLite-Database-003B57?style=for-the-badge&logo=sqlite&logoColor=white"/>
</p>

> **SmartFinance AI** is a Telegram-based personal finance bot powered by Google Gemini AI. It lets you record income and expenses in plain Indonesian language, automatically categorizes them, and syncs everything to a Google Sheet — all from your Telegram chat.

---

## ✨ Features

- 💬 **Natural Language Input** — Type `"Makan siang 30rb"` or `"Gaji bulan ini 5jt"` and the AI extracts the transaction automatically
- 🤖 **Google Gemini AI** — Intelligent extraction with a local heuristic fallback for reliability
- 📊 **FastAPI Web Dashboard** — View and manage your finances from a browser
- 📈 **Google Sheets Sync** — Optionally link a Google Sheet to keep a live spreadsheet copy
- 🗂️ **Transaction History** — Browse, filter, and delete past records
- 📅 **Monthly Reports** — Category breakdowns per month
- 🗑️ **One-command History Clear** — `/clear` wipes all local records instantly
- 🔔 **Auto-notification** — Telegram confirms when your Google Sheet is linked via the dashboard

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | `python-telegram-bot` 21.9 (async polling) |
| AI extraction | Google Gemini 1.5 Flash via HTTP |
| Web dashboard | FastAPI + Uvicorn (port 5000) |
| Database | SQLite via SQLAlchemy |
| Sheets sync | `gspread` + Google service account |
| HTTP client | `httpx` |
| Config | `python-dotenv` |

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

Edit `.env` and fill in the real values (see [Environment Variables](#-environment-variables) below).

### 4. Run the application

```bash
python main.py
```

This starts both the Telegram bot (polling) and the FastAPI dashboard on port 5000 simultaneously.

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | ✅ | API key from [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `SESSION_SECRET` | ✅ | Random string for signing dashboard session cookies |
| `GOOGLE_CREDENTIALS_BASE64` | ✅ | Base64-encoded Google service account JSON (for Sheets sync) |
| `GROQ_API_KEY` | ⚠️ | Reserved — required by config but not actively used |
| `DASHBOARD_URL` | ➖ | Public URL of the dashboard (shown in `/start` message) |

> Encode your service account key: `base64 -w 0 credentials.json`

See `.env.example` for placeholder values and comments.

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Register and get onboarding instructions |
| `/help` | Show all available commands |
| `/summary` | Daily and all-time financial summary |
| `/history` | Last 10 transactions |
| `/monthly` | Monthly report with category breakdown |
| `/add` | Manually add a transaction |
| `/delete` | Delete a transaction by ID |
| `/setsheet` | Link a Google Sheet for sync |
| `/clear` | Wipe all local transaction history |

**Natural language** — just send a message like:
- `"Beli kopi 25000"`
- `"Terima gaji 4.5 juta"`
- `"Bensin motor 50rb"`

---

## 🌐 Dashboard API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Main web interface |
| `POST` | `/api/connect` | Link Telegram account to a Google Sheet |
| `GET` | `/api/dashboard` | Fetch sheet data via web token |
| `POST` | `/api/register` | Web-based user registration |
| `POST` | `/api/login` | Web-based login |
| `GET` | `/api/user-sheet` | Retrieve sheet data for a Telegram ID |

---

## 🚀 Deployment

This project is configured for a **Replit Reserved VM** deployment, which keeps the polling bot alive continuously.

```toml
# replit.toml
deploymentTarget = "vm"
run = ["python", "main.py"]
```

> ⚠️ Do **not** run the dev workflow and the deployed VM at the same time with the same `TELEGRAM_BOT_TOKEN` — Telegram only allows one active polling connection per bot.

---

## 🔒 Security Notes

- Never commit your real `.env` file — it is listed in `.gitignore`
- `GOOGLE_CREDENTIALS_BASE64` grants access to your Google account; rotate the key if exposed
- `SESSION_SECRET` should be a cryptographically random string (minimum 32 characters)

---

## 📄 License

This project was built for academic purposes as a university submission. All rights reserved by the authors.
