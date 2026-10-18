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
    need_stdout_redirect = False
    if sys.stdout is None:
        need_stdout_redirect = True
    else:
        try:
            sys.stdout.write("")
            sys.stdout.flush()
        except Exception:
            need_stdout_redirect = True

    if need_stdout_redirect:
        try:
            log_dir = os.path.join(
                os.environ.get("APPDATA", os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))),
                "telegram_binance_signal_executor",
            )
            os.makedirs(log_dir, exist_ok=True)
            sys.stdout = open(os.path.join(log_dir, "backend_stdout.log"), "a", encoding="utf-8", buffering=1)
        except Exception:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    need_stderr_redirect = False
    if sys.stderr is None:
        need_stderr_redirect = True
    else:
        try:
            sys.stderr.write("")
            sys.stderr.flush()
        except Exception:
            need_stderr_redirect = True

    if need_stderr_redirect:
        try:
            log_dir = os.path.join(
                os.environ.get("APPDATA", os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))),
                "telegram_binance_signal_executor",
            )
            os.makedirs(log_dir, exist_ok=True)
            sys.stderr = open(os.path.join(log_dir, "backend_stderr.log"), "a", encoding="utf-8", buffering=1)
        except Exception:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    else:
        try:
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

