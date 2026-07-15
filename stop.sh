#!/bin/zsh
pkill -f "dashboard/run.py" 2>/dev/null && echo "✅ Dashboard dihentikan"
pkill -f "python3 main.py" 2>/dev/null && echo "✅ Bot dihentikan"
rm -f "$(dirname "$0")/.pids"
echo "Semua layanan dihentikan."
