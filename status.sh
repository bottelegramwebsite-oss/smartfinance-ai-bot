#!/bin/zsh
pgrep -f "dashboard/run.py" >/dev/null && echo "✅ Dashboard: BERJALAN → http://localhost:8000" || echo "❌ Dashboard: MATI"
pgrep -f "python3 main.py" >/dev/null && echo "✅ Bot Telegram: BERJALAN" || echo "❌ Bot Telegram: MATI"
