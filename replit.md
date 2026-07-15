# SmartFinance AI — Bot Keuangan Telegram

A Telegram finance bot with an AI-powered transaction parser and a web dashboard.

## Stack

- **Bot**: python-telegram-bot 21.9 (async polling)
- **AI**: Groq (`llama-3.3-70b-versatile`) for natural-language transaction extraction
- **Dashboard**: FastAPI + Uvicorn served on port 5000
- **Database**: SQLite (`data/finance.db`) via SQLAlchemy
- **Google Sheets**: optional sync via gspread service account

## How to run

The single entry point `main.py` starts both services:
- The FastAPI dashboard in a background thread on port 5000
- The Telegram bot polling loop in the main thread

```
python main.py
```

The workflow **"Start application"** is already configured and runs this command automatically.

## Required secrets

| Secret | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather on Telegram |
| `GEMINI_API_KEY` | From Google AI Studio. Actually used by `services/ai_service.py` for AI transaction extraction — without it the bot silently falls back to a local heuristic parser. |

## Optional configuration

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | required by `config/settings.py` at startup, but currently unused by any code path (dead config left over from an earlier design) | Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model name (unused, see above) |
| `DATABASE_PATH` | `./data/finance.db` | SQLite database path |
| `GOOGLE_CREDENTIALS_PATH` | `./credentials.json` | Google service account JSON (enables Sheets sync) |
| `DASHBOARD_URL` | Replit app URL | Public URL shown in bot messages |
| `PORT` | `5000` | Dashboard port |
| `TIMEZONE` | `Asia/Jakarta` | Locale for date handling |

## Google Sheets integration (optional)

1. Create a Google Cloud service account and download `credentials.json`
2. Place `credentials.json` in the project root
3. Share your Google Sheet with the service account email as **Editor**
4. Use `/setsheet <url>` in the Telegram bot

## Project structure

```
main.py              — entry point (bot + dashboard)
bot/                 — Telegram handlers and keyboards
config/              — environment/settings loader
dashboard/           — FastAPI app and static frontend
models/              — SQLAlchemy models and DB init
services/            — AI, transaction, and Sheets services
utils/               — helpers, logger
data/                — SQLite database files
logs/                — application logs
```

## User preferences

- Keep existing project structure and stack
