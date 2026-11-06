"""THOMAS core entry point（刀 4）— serves the core-only app on :5300.

Usage: FLASK_PORT=5300 python run_core.py
Host app (run.py, :5200) keeps running unchanged; both share the same DB.
"""
import os

from src.thomas_core.app import create_core_app

app = create_core_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5300))
    app.run(host="0.0.0.0", port=port, debug=True)
