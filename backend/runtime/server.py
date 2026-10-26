import asyncio
from contextlib import asynccontextmanager
import os
import signal
import sys
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.auth_middleware import make_error_response
from backend.api.router import create_api_router
from backend.runtime.handshake import HandshakeData, HandshakeManager, find_free_port, get_default_data_dir
from config.config import AppConfig, load_config
from storage.database import DatabaseManager


def check_db_healthy(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(path, timeout=3.0)
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()
        return bool(row and row[0] == "ok")
    except Exception:
        return False


def resolve_db_path(config: AppConfig, effective_data_dir: str) -> str:
    # 1. Environment variable override
    env_path = os.environ.get("TBCE_DATABASE_PATH")
    if env_path and os.path.exists(env_path):
        return os.path.abspath(env_path)

    raw_path = getattr(config, "database_file", None) or "./data/trading_state.db"
    if os.path.isabs(raw_path):
        return os.path.abspath(raw_path)

    # 2. Check AppData canonical live database first (Platform SSOT)
    try:
        from backend.runtime.handshake import get_default_data_dir
        app_data_live = os.path.join(get_default_data_dir(), "data", "trading_state.db")
        if os.path.exists(app_data_live):
            return os.path.abspath(app_data_live)
    except Exception:
        pass

    # 3. Prevent double-nesting if effective_data_dir already ends with 'data'
    base_name = os.path.basename(raw_path)
    clean_eff = os.path.abspath(effective_data_dir)
    if os.path.basename(clean_eff) == "data":
        direct = os.path.join(clean_eff, base_name)
        if os.path.exists(direct):
            return direct
        return direct

    configured = os.path.abspath(os.path.join(effective_data_dir, raw_path))
    if os.path.exists(configured):
        return configured

    # Preserve compatibility with packaged configs that still use ./data/trading_state.db.
    runtime_path = os.path.abspath(os.path.join(effective_data_dir, "data", "trading_state.db"))
    if runtime_path != configured and os.path.exists(runtime_path):
        return runtime_path

    # Local workspace ./data/trading_state.db
    local_ws = os.path.abspath("./data/trading_state.db")
    if os.path.exists(local_ws):
        return local_ws

    return configured



def create_app(
    config: Optional[AppConfig] = None,
    db: Optional[DatabaseManager] = None,
    session_token: Optional[str] = None,
    handshake_mgr: Optional[HandshakeManager] = None,
    bound_port: int = 8000,
) -> FastAPI:
    """
    Factory function to create and configure the FastAPI application with lifespan events.
    """
    if config is None:
        config = load_config()

    if db is None:
        db_path = resolve_db_path(config, get_default_data_dir())
        db = DatabaseManager(db_path=db_path)

    token = session_token or os.environ.get("TBCE_SESSION_TOKEN", "")
    if not token:
        raise RuntimeError("Backend session token is not configured")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup hook: Only now is the server actually bound and accepting requests
        if handshake_mgr:
            handshake_mgr.mark_ready(bound_port)

        listener_task = None
        if hasattr(app.state, "listener_task_starter") and callable(app.state.listener_task_starter):
            listener_task = asyncio.create_task(app.state.listener_task_starter())

        reconciliation_task = None
        if hasattr(app.state, "reconciliation_task_starter") and callable(app.state.reconciliation_task_starter):
            reconciliation_task = asyncio.create_task(app.state.reconciliation_task_starter())

        ai_trader_task = None
        if hasattr(app.state, "ai_trader_task_starter") and callable(app.state.ai_trader_task_starter):
            ai_trader_task = asyncio.create_task(app.state.ai_trader_task_starter())

        yield
        # Shutdown hook: Clean up metadata
        if listener_task and not listener_task.done():
            listener_task.cancel()
        if reconciliation_task and not reconciliation_task.done():
            reconciliation_task.cancel()
        if ai_trader_task and not ai_trader_task.done():
            ai_trader_task.cancel()
        if handshake_mgr:
            handshake_mgr.cleanup()


    app = FastAPI(
        title="Telegram Binance Signal Executor API",
        version="2.4.0",
        docs_url="/docs" if config.mode.value != "LIVE" else None,
        redoc_url=None,
        lifespan=lifespan,
    )


    # CORS configuration - strictly restricted to loopback and Tauri schemes
    origins = [
        "http://localhost",
        "http://localhost:1420",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:1420",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=make_error_response("INTERNAL_ERROR", str(exc)),
        )

    # Mount API routes
    api_router = create_api_router(config=config, db=db, session_token=token)
    if hasattr(api_router, "listener_task_starter"):
        app.state.listener_task_starter = api_router.listener_task_starter
    if hasattr(api_router, "reconciliation_task_starter"):
        app.state.reconciliation_task_starter = api_router.reconciliation_task_starter
    if hasattr(api_router, "ai_trader_task_starter"):
        app.state.ai_trader_task_starter = api_router.ai_trader_task_starter

    app.include_router(api_router, prefix="/api")
    app.include_router(api_router, prefix="")

    # Mount Static Web Dashboard if built frontend exists
    try:
        from fastapi.staticfiles import StaticFiles
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "desktop", "dist"),
            os.path.join(os.path.dirname(sys.executable), "resources", "dist"),
            os.path.join(os.path.dirname(sys.executable), "dist"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "desktop", "dist"),
        ]
        for c_dist in candidates:
            if c_dist and os.path.exists(c_dist) and os.path.exists(os.path.join(c_dist, "index.html")):
                app.mount("/", StaticFiles(directory=c_dist, html=True), name="static_frontend")
                break
    except Exception:
        pass

    return app


def run_server(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    data_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:
    """
    Main runtime entry that coordinates handshake, port discovery, and Uvicorn execution.
    """
    import uvicorn

    effective_data_dir = data_dir or get_default_data_dir()
    config = load_config(config_path) if config_path else load_config()
    db_path = resolve_db_path(config, effective_data_dir)
    db = DatabaseManager(db_path=db_path)

    handshake_mgr = HandshakeManager(data_dir=effective_data_dir)
    actual_port = find_free_port(port)

    # Mark starting before bind
    handshake_mgr.init_starting(actual_port)

    app = create_app(
        config=config,
        db=db,
        session_token=handshake_mgr.session_token,
        handshake_mgr=handshake_mgr,
        bound_port=actual_port,
    )

    uvi_config = uvicorn.Config(
        app=app,
        host=host,
        port=actual_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(uvi_config)

    if "--open-browser" in sys.argv or os.environ.get("OPEN_BROWSER") == "1":
        import webbrowser, threading
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{actual_port}/")).start()

    try:
        server.run()
    finally:
        handshake_mgr.cleanup()
