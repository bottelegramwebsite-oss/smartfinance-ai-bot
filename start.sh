#!/bin/zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/venv/bin/python3"
mkdir -p "$ROOT/logs"
pkill -f "dashboard/run.py" 2>/dev/null
pkill -f "python3 main.py" 2>/dev/null
sleep 2
cd "$ROOT"
nohup "$PYTHON" dashboard/run.py >> "$ROOT/logs/dashboard.log" 2>&1 &
echo $! > "$ROOT/.pids"
sleep 2
echo "✅ Dashboard → http://localhost:8000"
nohup "$PYTHON" main.py >> "$ROOT/logs/bot.log" 2>&1 &
echo $! >> "$ROOT/.pids"
sleep 3
echo "✅ Bot Telegram → @BudgetMateAIBot"
echo "Selesai! Buka http://localhost:8000"
