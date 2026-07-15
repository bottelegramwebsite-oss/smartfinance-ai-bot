"""
dashboard/run.py
Startup script untuk SmartFinance Dashboard backend.
Support both local dev dan production (Render).
"""

import os
import sys

# Pastikan root project ada di Python path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import uvicorn

if __name__ == "__main__":
    # Get port from environment (Render sets PORT env var)
    port = int(os.getenv("PORT", 5000))
    host = "0.0.0.0"  # Bind ke semua interfaces untuk production

    print("=" * 60)
    print("  SmartFinance Dashboard — Starting...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Environment: {'Production' if os.getenv('RENDER') else 'Development'}")
    print("=" * 60)

    uvicorn.run(
        "dashboard.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
