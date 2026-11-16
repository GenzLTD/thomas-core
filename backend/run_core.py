"""THOMAS core entry point（刀 4）— serves the core-only app on :5300.

Usage: FLASK_PORT=5300 python run_core.py
Host app (run.py, :5200) keeps running unchanged; both share the same DB.

Bind: default 127.0.0.1（仅本机 / SSH 隧道可达）。需要对外监听时显式设
FLASK_HOST=0.0.0.0（不推荐上 106 公网）。
"""
import os

from src.thomas_core.app import create_core_app

app = create_core_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5300"))
    app.run(host=host, port=port, debug=True)
