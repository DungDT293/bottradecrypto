"""
Backend Launcher CLI entrypoint.
Invoked by Tauri supervisor or manually during development.
"""
import argparse
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from backend.runtime.server import run_server


def main():
    parser = argparse.ArgumentParser(description="Telegram Binance Signal Executor - Backend Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (auto-assign if omitted)")
    parser.add_argument("--data-dir", type=str, default="./data", help="Data directory path")
    parser.add_argument("--config", type=str, default=None, help="Config YAML file path")

    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()

