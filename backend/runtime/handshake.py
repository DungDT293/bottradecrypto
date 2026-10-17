import ctypes
from datetime import datetime, timezone
import json
import os
import secrets
import socket
import sys
import uuid
from typing import Optional
from pydantic import BaseModel, Field


def is_pid_running(pid: int) -> bool:
    """Checks if a given process ID is actively running."""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def get_default_data_dir() -> str:
    """Returns platform-standard application data directory."""
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            path = os.path.join(app_data, "telegram_binance_signal_executor")
            os.makedirs(path, exist_ok=True)
            return path
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        path = os.path.join(xdg_data, "telegram_binance_signal_executor")
        os.makedirs(path, exist_ok=True)
        return path

    fallback = os.path.abspath("./data")
    os.makedirs(fallback, exist_ok=True)
    return fallback


class HandshakeData(BaseModel):
    instance_id: str
    status: str = "STARTING"  # STARTING -> READY -> STOPPED
    host: str = "127.0.0.1"
    port: int
    session_token: str
    pid: int
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def find_free_port(preferred_port: Optional[int] = None) -> int:
    """Finds an available local port on loopback interface."""
    if preferred_port and preferred_port > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("127.0.0.1", preferred_port)) != 0:
                return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port


class HandshakeManager:
    """
    Manages session tokens, handshake lifecycle, and platform-restricted metadata.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = os.path.abspath(data_dir) if data_dir else get_default_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.handshake_file = os.path.join(self.data_dir, "backend_handshake.json")
        self.instance_id = str(uuid.uuid4())
        self.session_token = secrets.token_urlsafe(32)
        self.current_data: Optional[HandshakeData] = None

    def _write_file_secure(self, data: HandshakeData) -> None:
        """Writes handshake data with restricted owner permissions."""
        content = data.model_dump_json(indent=2).encode("utf-8")
        
        # On POSIX: 0600 (read/write only by owner)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        
        fd = os.open(self.handshake_file, flags, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(content)

    def _force_kill_pid(self, pid: int) -> None:
        try:
            if os.name == "nt":
                import ctypes
                PROCESS_TERMINATE = 0x0001
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if handle:
                    kernel32.TerminateProcess(handle, 1)
                    kernel32.CloseHandle(handle)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    def _kill_stale_processes(self) -> None:
        """
        Forcefully terminates any existing stale or zombie backend processes to prevent
        port conflicts, database locks, and duplicate Telegram listeners.
        """
        curr_pid = os.getpid()
        parent_pid = os.getppid() if hasattr(os, "getppid") else 0

        # 1. Terminate PID from existing handshake file if running
        if os.path.exists(self.handshake_file):
            try:
                with open(self.handshake_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                old_pid = content.get("pid", 0)
                if old_pid and old_pid != curr_pid and old_pid != parent_pid and is_pid_running(old_pid):
                    print(f"[HANDSHAKE] Phát hiện backend cũ (PID {old_pid}) đang chạy ngầm. Đang chấm dứt để tránh xung đột...")
                    self._force_kill_pid(old_pid)
                if os.path.exists(self.handshake_file):
                    os.remove(self.handshake_file)
            except Exception:
                pass

        # 2. Terminate any orphan backend processes on Windows
        if os.name == "nt":
            try:
                import psutil
                for p in psutil.process_iter(['pid', 'name', 'ppid']):
                    try:
                        p_name = (p.info.get('name') or '').lower()
                        p_pid = p.info.get('pid', 0)
                        if p_pid != curr_pid and p_pid != parent_pid and ('backend-x86_64-pc-windows-msvc' in p_name or p_name == 'backend.exe'):
                            if p_pid != parent_pid:
                                print(f"[HANDSHAKE] Đang dọn dẹp tiến trình backend thừa (PID {p_pid})...")
                                psutil.Process(p_pid).kill()
                    except Exception:
                        pass
            except Exception:
                pass

    def init_starting(self, port: int) -> HandshakeData:
        """Initializes metadata in STARTING state before server bind."""
        self._kill_stale_processes()

        data = HandshakeData(
            instance_id=self.instance_id,
            status="STARTING",
            host="127.0.0.1",
            port=port,
            session_token=self.session_token,
            pid=os.getpid(),
        )
        self.current_data = data
        self._write_file_secure(data)
        return data

    def mark_ready(self, actual_port: int) -> HandshakeData:
        """Marks metadata as READY after server has bound and started listening."""
        data = HandshakeData(
            instance_id=self.instance_id,
            status="READY",
            host="127.0.0.1",
            port=actual_port,
            session_token=self.session_token,
            pid=os.getpid(),
        )
        self.current_data = data
        self._write_file_secure(data)
        
        # Output protocol marker to stdout for supervisor
        print(f"__TAURI_HANDSHAKE_READY__:{data.model_dump_json()}", flush=True)
        return data

    def cleanup(self) -> None:
        """Safely removes metadata only if belonging to this exact instance."""
        if not os.path.exists(self.handshake_file):
            return

        try:
            with open(self.handshake_file, "r", encoding="utf-8") as f:
                content = json.load(f)
            
            # Verify instance_id and pid before deleting
            if content.get("instance_id") == self.instance_id and content.get("pid") == os.getpid():
                os.remove(self.handshake_file)
        except Exception:
            pass
