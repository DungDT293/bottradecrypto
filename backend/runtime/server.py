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
    import shutil
    raw_path = getattr(config, "database_file", None) or "./data/trading_state.db"
    candidates = [
        raw_path,
        os.path.join(effective_data_dir, raw_path),
        os.path.join(effective_data_dir, "data", os.path.basename(raw_path)),
        os.path.join(effective_data_dir, os.path.basename(raw_path)),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "trading_state.db"),
    ]
    # Filter to only physically existing and healthy candidates
    healthy_candidates = []
    for cand in candidates:
        if cand and os.path.exists(cand):
            if check_db_healthy(cand):
                healthy_candidates.append(cand)
            else:
                # If corrupt, attempt self-healing from clean workspace template
                clean_root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "trading_state.db")
                if os.path.exists(clean_root) and check_db_healthy(clean_root):
                    try:
                        shutil.copyfile(clean_root, cand)
                        healthy_candidates.append(cand)
                    except Exception:
                        pass

    best_candidate = None
    max_size = -1
    for cand in healthy_candidates:
        sz = os.path.getsize(cand)
        if sz > max_size:
            max_size = sz
            best_candidate = cand
    if best_candidate and max_size > 0:
        return best_candidate
    return os.path.join(effective_data_dir, "data", "trading_state.db")



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

    token = session_token or "dev_insecure_token"

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

        yield
        # Shutdown hook: Clean up metadata
        if listener_task and not listener_task.done():
            listener_task.cancel()
        if reconciliation_task and not reconciliation_task.done():
            reconciliation_task.cancel()
        if handshake_mgr:
            handshake_mgr.cleanup()


    app = FastAPI(
        title="Telegram Binance Signal Executor API",
        version="1.1.8",
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

    try:
        server.run()
    finally:
        handshake_mgr.cleanup()
