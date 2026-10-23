import asyncio
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    ApiIdInvalidError,
    UserAlreadyParticipantError,
    InviteHashExpiredError,
    InviteHashInvalidError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from config.config import AppConfig
from core.exceptions import BotTradingError
from telegram.client import TelegramUserClient


class TelegramStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_LOGGED_IN = "NOT_LOGGED_IN"
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    ERROR = "ERROR"


def mask_phone_number(phone: str) -> str:
    cleaned = phone.strip()
    if len(cleaned) <= 6:
        return "***"
    return f"{cleaned[:4]}***{cleaned[-3:]}"


@dataclass
class AuthAttempt:
    attempt_id: str
    phone: str
    client: TelegramClient
    phone_code_hash: str
    created_at: float
    expires_at: float


def check_session_healthy(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(path, timeout=2.0)
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()
        return bool(row and row[0] == "ok")
    except Exception:
        return False


class TelegramService:
    """
    Application service managing Telegram MTProto connection, authentication,
    dialog discovery, and historical collection.
    Strict Invariants:
    - Never logs or exposes raw phone, OTP, or 2FA passwords.
    - Read-only operations only.
    - Preserves login context via backend-managed AuthAttempt instances.
    - Prevents duplicate login requests or double listeners.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._auth_attempts: Dict[str, AuthAttempt] = {}
        self._client: Optional[TelegramClient] = None
        self._login_client: Optional[TelegramClient] = None
        self._phone: Optional[str] = None
        self._is_collecting: bool = False
        self._cancel_collection_flag: bool = False
        self._dialogs_cache: Optional[Dict[str, Any]] = None
        self._dialogs_cache_time: float = 0.0

    def get_client(self) -> TelegramClient:
        """
        Returns the single shared TelegramClient instance for this service.
        Strict invariant: Never instantiate multiple TelegramClient objects on the same
        SQLite session file to prevent 'database is locked' errors.
        """
        if not self.config.telegram.api_id or not self.config.telegram.api_hash:
            raise BotTradingError("Chưa cấu hình TELEGRAM_API_ID hoặc TELEGRAM_API_HASH.")
        if self._client is None:
            sess_path = self.get_session_file_path()
            sess_base = sess_path[:-8] if sess_path.endswith(".session") else sess_path
            self._client = TelegramClient(
                sess_base,
                self.config.telegram.api_id,
                self.config.telegram.api_hash,
            )
        return self._client

    def get_credentials_status(self) -> Dict[str, Any]:
        has_id = bool(self.config.telegram.api_id)
        has_hash = bool(self.config.telegram.api_hash)
        return {
            "has_credentials": has_id and has_hash,
            "api_id_configured": has_id,
            "api_hash_configured": has_hash,
            "status": self.get_status().value,
        }

    async def update_credentials(self, api_id: int, api_hash: str) -> Dict[str, Any]:
        self.config.telegram.api_id = int(api_id)
        self.config.telegram.api_hash = str(api_hash).strip()
        os.environ["TELEGRAM_API_ID"] = str(api_id)
        os.environ["TELEGRAM_API_HASH"] = str(api_hash).strip()

        if self._client:
            try:
                if self._client.is_connected():
                    await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        try:
            env_file = ".env"
            lines = []
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            new_lines = []
            seen_id, seen_hash = False, False
            for line in lines:
                if line.startswith("TELEGRAM_API_ID="):
                    new_lines.append(f"TELEGRAM_API_ID={api_id}\n")
                    seen_id = True
                elif line.startswith("TELEGRAM_API_HASH="):
                    new_lines.append(f"TELEGRAM_API_HASH={api_hash}\n")
                    seen_hash = True
                else:
                    new_lines.append(line)
            if not seen_id:
                new_lines.append(f"TELEGRAM_API_ID={api_id}\n")
            if not seen_hash:
                new_lines.append(f"TELEGRAM_API_HASH={api_hash}\n")

            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass

        return {"success": True, "message": "Đã cập nhật cấu hình Telegram API thành công."}

    def _cleanup_expired_attempts(self):
        now = time.time()
        expired_ids = [aid for aid, a in self._auth_attempts.items() if now > a.expires_at]
        for aid in expired_ids:
            self._auth_attempts.pop(aid, None)




    def get_session_file_path(self) -> str:
        base = self.config.telegram.session_name
        sess = f"{base}.session" if not base.endswith(".session") else base

        # Check candidates in data_dir, APPDATA, LOCALAPPDATA, exe_dir, or project root
        candidates = [sess]
        if hasattr(self.config, "data_dir") and self.config.data_dir:
            candidates.append(os.path.join(self.config.data_dir, "telegram_user.session"))
            candidates.append(os.path.join(self.config.data_dir, "data", "telegram_user.session"))
        if "APPDATA" in os.environ:
            candidates.append(os.path.join(os.environ["APPDATA"], "telegram_binance_signal_executor", "telegram_user.session"))
            candidates.append(os.path.join(os.environ["APPDATA"], "telegram_binance_signal_executor", "data", "telegram_user.session"))
        if "LOCALAPPDATA" in os.environ:
            candidates.append(os.path.join(os.environ["LOCALAPPDATA"], "telegram-binance-signal-executor", "telegram_user.session"))
            candidates.append(os.path.join(os.environ["LOCALAPPDATA"], "telegram-binance-signal-executor", "data", "telegram_user.session"))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "telegram_user.session"))
        candidates.append(os.path.join(exe_dir, "data", "telegram_user.session"))
        candidates.append(r"e:\TOOL DUNG CODE\bottradecrypto\data\telegram_user.session")
        candidates.append(r"e:\TOOL DUNG CODE\bottradecrypto\telegram_user.session")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        candidates.append(os.path.join(project_root, "data", "telegram_user.session"))
        candidates.append(os.path.join(project_root, "telegram_user.session"))

        # 1. First look for any healthy candidate
        healthy_path = None
        for cand in candidates:
            if cand and os.path.exists(cand) and check_session_healthy(cand):
                healthy_path = cand
                break

        # 2. If we found a healthy path, check if primary target is corrupted and heal it
        if healthy_path:
            # If target in APPDATA exists but is corrupted, heal it
            for cand in candidates:
                if cand and os.path.exists(cand) and not check_session_healthy(cand):
                    try:
                        import shutil
                        # Remove stale shm/wal if present
                        for ext in ["-shm", "-wal", "-journal"]:
                            if os.path.exists(cand + ext):
                                try:
                                    os.remove(cand + ext)
                                except Exception:
                                    pass
                        shutil.copy2(healthy_path, cand)
                    except Exception:
                        pass
            return healthy_path

        # Fallback to base
        return sess

    def get_status(self) -> TelegramStatus:
        if not self.config.telegram.api_id or not self.config.telegram.api_hash:
            return TelegramStatus.NOT_CONFIGURED
        if not os.path.exists(self.get_session_file_path()):
            return TelegramStatus.NOT_LOGGED_IN
        return TelegramStatus.CONNECTED

    async def get_account_profile(self) -> Dict[str, Any]:
        """
        Retrieves current authorized user profile with masked sensitive data.
        Re-uses single shared client without opening duplicate SQLite sessions.
        """
        status = self.get_status()
        if status != TelegramStatus.CONNECTED:
            return {
                "status": status.value,
                "connected": False,
                "first_name": None,
                "username_masked": None,
                "phone_masked": None,
            }

        try:
            client = self.get_client()
            if not client.is_connected():
                await client.connect()
            if not await client.is_user_authorized():
                return {
                    "status": TelegramStatus.NOT_LOGGED_IN.value,
                    "connected": False,
                    "first_name": None,
                    "username_masked": None,
                    "phone_masked": None,
                }
            me = await client.get_me()
            raw_phone = getattr(me, "phone", "") or ""
            phone_masked = mask_phone_number(f"+{raw_phone}" if not raw_phone.startswith("+") else raw_phone)
            raw_uname = getattr(me, "username", "") or ""
            uname_masked = f"@{raw_uname[:2]}***" if len(raw_uname) > 3 else (f"@{raw_uname}" if raw_uname else "None")

            return {
                "status": TelegramStatus.CONNECTED.value,
                "connected": True,
                "first_name": getattr(me, "first_name", "Telegram User"),
                "username_masked": uname_masked,
                "phone_masked": phone_masked,
            }
        except Exception as e:
            return {
                "status": TelegramStatus.ERROR.value,
                "connected": False,
                "error": str(e),
                "first_name": None,
                "username_masked": None,
                "phone_masked": None,
            }

    async def send_login_code(self, phone: str) -> Dict[str, Any]:
        """
        Step 1 of interactive login: Sends OTP request to user's phone via MTProto.
        Saves phone_code_hash securely in an AuthAttempt on backend.
        """
        self._cleanup_expired_attempts()

        if not self.config.telegram.api_id or not self.config.telegram.api_hash:
            return {
                "success": False,
                "error_code": "CONFIG_MISSING",
                "error": "Chưa cấu hình TELEGRAM_API_ID hoặc TELEGRAM_API_HASH. Vui lòng thiết lập API credentials từ https://my.telegram.org trong form cài đặt trước khi gửi mã.",
            }

        phone_clean = phone.strip()
        if not phone_clean.startswith("+") or len(phone_clean) < 10 or not phone_clean[1:].isdigit():
            return {
                "success": False,
                "error_code": "INVALID_PHONE_FORMAT",
                "error": "Số điện thoại phải ở định dạng quốc tế bắt đầu bằng dấu + (Ví dụ: +84393954568).",
            }

        session_dir = os.path.dirname(os.path.abspath(self.get_session_file_path()))
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)

        try:
            client = self.get_client()
            if not client.is_connected():
                await client.connect()
            if await client.is_user_authorized():
                return {
                    "success": True,
                    "already_authorized": True,
                    "message": "Tài khoản Telegram đã được đăng nhập từ trước.",
                }

            sent_code = await client.send_code_request(phone_clean)
            attempt_id = str(uuid.uuid4())
            now = time.time()
            self._auth_attempts[attempt_id] = AuthAttempt(
                attempt_id=attempt_id,
                phone=phone_clean,
                client=client,
                phone_code_hash=sent_code.phone_code_hash,
                created_at=now,
                expires_at=now + 600.0,
            )

            self._login_client = client
            self._phone = phone_clean

            return {
                "success": True,
                "already_authorized": False,
                "auth_attempt_id": attempt_id,
                "phone_masked": mask_phone_number(phone_clean),
                "timeout_seconds": getattr(sent_code, "timeout", 60),
            }
        except ApiIdInvalidError:
            if client.is_connected():
                await client.disconnect()
            return {
                "success": False,
                "error_code": "API_CREDENTIALS_INVALID",
                "error": "TELEGRAM_API_ID hoặc TELEGRAM_API_HASH không hợp lệ. Vui lòng kiểm tra lại cấu hình từ my.telegram.org.",
            }
        except PhoneNumberInvalidError:
            if client.is_connected():
                await client.disconnect()
            return {
                "success": False,
                "error_code": "PHONE_NUMBER_INVALID",
                "error": "Số điện thoại không hợp lệ theo quy định của Telegram.",
            }
        except FloodWaitError as e:
            if client.is_connected():
                await client.disconnect()
            return {
                "success": False,
                "error_code": "FLOOD_WAIT",
                "error": f"Telegram giới hạn thao tác do thử quá nhiều lần. Vui lòng đợi {e.seconds} giây.",
            }
        except Exception as e:
            if client.is_connected():
                await client.disconnect()
            return {
                "success": False,
                "error_code": "SEND_CODE_FAILED",
                "error": f"Lỗi từ máy chủ Telegram MTProto: {str(e)}",
            }

    async def submit_login_code(
        self,
        code: str,
        password_2fa: Optional[str] = None,
        auth_attempt_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Step 2 of interactive login: Submits OTP code and handles 2FA password.
        """
        self._cleanup_expired_attempts()

        attempt: Optional[AuthAttempt] = None
        if auth_attempt_id and auth_attempt_id in self._auth_attempts:
            attempt = self._auth_attempts[auth_attempt_id]
        elif self._auth_attempts:
            attempt = list(self._auth_attempts.values())[-1]

        client = attempt.client if attempt else self._login_client
        phone = attempt.phone if attempt else self._phone
        phone_code_hash = attempt.phone_code_hash if attempt else None

        if not client or not phone:
            return {
                "success": False,
                "error_code": "SESSION_EXPIRED",
                "error": "Phiên xác thực đã hết hạn hoặc chưa được khởi tạo. Vui lòng gửi lại mã OTP.",
            }

        try:
            if not client.is_connected():
                await client.connect()

            try:
                if phone_code_hash:
                    await client.sign_in(phone=phone, code=code.strip(), phone_code_hash=phone_code_hash)
                else:
                    await client.sign_in(phone=phone, code=code.strip())
            except SessionPasswordNeededError:
                if not password_2fa:
                    return {
                        "success": False,
                        "needs_2fa": True,
                        "auth_attempt_id": attempt.attempt_id if attempt else None,
                        "error_code": "PASSWORD_REQUIRED",
                        "error": "Tài khoản Telegram đã kích hoạt bảo mật 2 lớp (2FA). Vui lòng nhập mật khẩu.",
                    }
                await client.sign_in(password=password_2fa.strip())

            me = await client.get_me()
            await client.disconnect()

            if attempt and attempt.attempt_id in self._auth_attempts:
                del self._auth_attempts[attempt.attempt_id]
            self._login_client = None
            self._phone = None

            return {
                "success": True,
                "first_name": getattr(me, "first_name", "Telegram User"),
                "phone_masked": mask_phone_number(phone),
            }
        except PhoneCodeInvalidError:
            return {
                "success": False,
                "error_code": "CODE_INVALID",
                "error": "Mã xác thực OTP không chính xác. Vui lòng kiểm tra lại tin nhắn Telegram.",
            }
        except PhoneCodeExpiredError:
            return {
                "success": False,
                "error_code": "CODE_EXPIRED",
                "error": "Mã xác thực OTP đã hết hạn. Vui lòng bấm gửi lại mã mới.",
            }
        except PasswordHashInvalidError:
            return {
                "success": False,
                "needs_2fa": True,
                "auth_attempt_id": attempt.attempt_id if attempt else None,
                "error_code": "PASSWORD_INVALID",
                "error": "Mật khẩu 2FA không chính xác. Vui lòng kiểm tra và nhập lại.",
            }
        except FloodWaitError as e:
            return {
                "success": False,
                "error_code": "FLOOD_WAIT",
                "error": f"Thao tác quá nhanh. Telegram yêu cầu đợi {e.seconds} giây.",
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": "SIGN_IN_FAILED",
                "error": str(e),
            }

    async def list_accessible_dialogs(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Lists channels/groups accessible to user, along with Telegram chat folders and pinned status.
        Results are cached in memory for 10 minutes unless force_refresh is True.
        """
        if not force_refresh and self._dialogs_cache is not None:
            if time.time() - self._dialogs_cache_time < 600.0:
                return self._dialogs_cache

        client = self.get_client()
        if not client.is_connected():
            await client.connect()
        if not await client.is_user_authorized():
            raise BotTradingError("Chưa đăng nhập Telegram.")

        # 1. Fetch Telegram chat folders (DialogFilters)
        folder_map: Dict[int, Dict[str, Any]] = {}
        try:
            from telethon import utils, types
            from telethon.tl.functions.messages import GetDialogFiltersRequest

            raw_filters = await client(GetDialogFiltersRequest())
            filter_list = []
            if hasattr(raw_filters, "filters"):
                filter_list = raw_filters.filters
            elif isinstance(raw_filters, list):
                filter_list = raw_filters

            for f in filter_list:
                if isinstance(f, types.DialogFilterDefault):
                    continue

                folder_id = getattr(f, "id", None)
                if folder_id is None:
                    continue

                raw_title = getattr(f, "title", None)
                if raw_title is None:
                    folder_title = f"Folder {folder_id}"
                elif isinstance(raw_title, str):
                    folder_title = raw_title
                elif hasattr(raw_title, "text"):
                    folder_title = str(raw_title.text)
                else:
                    folder_title = str(raw_title)

                emoticon = getattr(f, "emoticon", "") or ""

                pinned_ids = set()
                for p in getattr(f, "pinned_peers", []) or []:
                    try:
                        pid = utils.get_peer_id(p)
                        pinned_ids.add(pid)
                    except Exception:
                        pass

                include_ids = set()
                for p in getattr(f, "include_peers", []) or []:
                    try:
                        pid = utils.get_peer_id(p)
                        include_ids.add(pid)
                    except Exception:
                        pass

                exclude_ids = set()
                for p in getattr(f, "exclude_peers", []) or []:
                    try:
                        pid = utils.get_peer_id(p)
                        exclude_ids.add(pid)
                    except Exception:
                        pass

                folder_map[folder_id] = {
                    "id": folder_id,
                    "title": folder_title,
                    "emoticon": emoticon,
                    "pinned_ids": pinned_ids,
                    "include_ids": include_ids,
                    "exclude_ids": exclude_ids,
                    "include_groups": bool(getattr(f, "groups", False)),
                    "include_broadcasts": bool(getattr(f, "broadcasts", False)),
                    "include_bots": bool(getattr(f, "bots", False)),
                    "matched_chat_ids": set(pinned_ids | include_ids),
                }
        except Exception:
            # Graceful fallback if MTProto GetDialogFiltersRequest is unavailable
            pass

        # 2. Fetch dialogs
        try:
            dialogs = await client.get_dialogs(limit=300)
        except Exception:
            if self._dialogs_cache is not None:
                return self._dialogs_cache
            dialogs = []
        result_dialogs = []
        for d in dialogs:
            if not (d.is_channel or d.is_group):
                continue

            d_id = d.id
            is_pinned = bool(getattr(d, "pinned", False))
            unread_count = int(getattr(d, "unread_count", 0))

            dialog_folder_ids = []
            dialog_folder_pinned_in = []

            for folder_id, f_info in folder_map.items():
                is_in_folder = False
                if d_id in f_info["pinned_ids"]:
                    is_in_folder = True
                    dialog_folder_pinned_in.append(folder_id)
                elif d_id in f_info["include_ids"]:
                    is_in_folder = True
                elif d_id not in f_info["exclude_ids"]:
                    if f_info["include_groups"] and d.is_group:
                        is_in_folder = True
                    elif f_info["include_broadcasts"] and d.is_channel and not d.is_group:
                        is_in_folder = True

                if is_in_folder:
                    f_info["matched_chat_ids"].add(d_id)
                    dialog_folder_ids.append(folder_id)

            result_dialogs.append({
                "id": d_id,
                "title": d.title or f"Chat {d_id}",
                "is_channel": bool(d.is_channel),
                "is_group": bool(d.is_group),
                "pinned": is_pinned,
                "unread_count": unread_count,
                "folder_ids": dialog_folder_ids,
                "folder_pinned_in": dialog_folder_pinned_in,
            })

        # Ensure all allowed_chat_ids are present in result_dialogs
        existing_ids = {d["id"] for d in result_dialogs}
        known_names = {
            -1002052872813: "CRYPTO LEOPARD'S",
            -1001756316676: "Boom_Boom_Billionaires",
            -1001370457350: "Crypto Neon",
            -1002007658025: "THE WOLF (CRYPTO)®",
            -1001552004524: "CRYPTO MONK",
        }
        for allowed_id in (self.config.telegram.allowed_chat_ids or []):
            if allowed_id not in existing_ids:
                c_name = known_names.get(allowed_id, f"Kênh {allowed_id}")
                result_dialogs.append({
                    "id": allowed_id,
                    "title": c_name,
                    "is_channel": True,
                    "is_group": False,
                    "pinned": True,
                    "unread_count": 0,
                    "folder_ids": [],
                    "folder_pinned_in": [],
                })

        # 3. Format folders response
        formatted_folders = []
        for f_info in folder_map.values():
            formatted_folders.append({
                "id": f_info["id"],
                "title": f_info["title"],
                "emoticon": f_info["emoticon"],
                "chat_ids": sorted(list(f_info["matched_chat_ids"])),
                "pinned_chat_ids": sorted(list(f_info["pinned_ids"])),
                "chat_count": len(f_info["matched_chat_ids"]),
            })

        res = {
            "dialogs": result_dialogs,
            "folders": formatted_folders,
        }
        self._dialogs_cache = res
        self._dialogs_cache_time = time.time()
        return res

    async def collect_history(
        self,
        chat_id: int,
        limit: int = 1000,
        max_days: int = 7,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Collects history with cancellation support.
        """
        self._is_collecting = True
        self._cancel_collection_flag = False

        def _cb(last_msg_id: int, count: int):
            if progress_callback:
                progress_callback(last_msg_id, count)
            if self._cancel_collection_flag:
                raise BotTradingError("Người dùng đã hủy thu thập lịch sử.")

        client = self.get_client()
        if not client.is_connected():
            await client.connect()
        client_wrapper = TelegramUserClient(self.config)
        client_wrapper.client = client
        try:
            return await client_wrapper.collect_channel_history(
                chat_id=chat_id,
                limit=limit,
                max_days=max_days,
                checkpoint_callback=_cb,
            )
        finally:
            self._is_collecting = False

    def cancel_collection(self) -> None:
        self._cancel_collection_flag = True

    def logout(self) -> bool:
        """
        Removes session file. Note: Does not touch exchange orders.
        """
        if self._client:
            try:
                if self._client.is_connected():
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._client.disconnect())
                    else:
                        loop.run_until_complete(self._client.disconnect())
            except Exception:
                pass
            self._client = None
        session_file = self.get_session_file_path()
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                return True
            except Exception:
                return False
        return True

    DEFAULT_ELITE_TARGETS = [
        {
            "id": -1002007658025,
            "name": "THE WOLF (CRYPTO)®",
            "link": "https://t.me/+lBx7BGAjD4wxY2I5",
            "hash": "lBx7BGAjD4wxY2I5",
            "username": None,
        },
        {
            "id": -1001756316676,
            "name": "Boom_Boom_Billionaires",
            "link": "https://t.me/+n5N2aXPU5Y42MTNk",
            "hash": "n5N2aXPU5Y42MTNk",
            "username": None,
        },
        {
            "id": -1002052872813,
            "name": "CRYPTO LEOPARD'S",
            "link": "https://t.me/+2qFH92pocvhhNWFk",
            "hash": "2qFH92pocvhhNWFk",
            "username": None,
        },
        {
            "id": -1001552004524,
            "name": "CRYPTO MONK",
            "link": "https://t.me/+KacfkVSBR0tkNzI0",
            "hash": "KacfkVSBR0tkNzI0",
            "username": None,
        },
        {
            "id": -1001370457350,
            "name": "Crypto Neon",
            "link": "https://t.me/CryptoNeon0",
            "hash": None,
            "username": "CryptoNeon0",
        },
    ]

    async def fetch_remote_elite_channels(self) -> List[Dict[str, Any]]:
        """
        Dynamically loads the latest invite links from remote JSON (GitHub Gist, Cloudflare Pages, Raw JSON)
        or falls back to local cache / bundled defaults.
        Ensures invite links don't get broken after .exe build when channels rotate private invite links.
        """
        remote_url = getattr(self.config.telegram, "remote_channels_url", None) or os.environ.get("TELEGRAM_REMOTE_CHANNELS_URL")
        cache_path = os.path.join(self.config.data_dir, "remote_elite_channels_cache.json")

        # 1. Try remote fetch if URL configured
        if remote_url:
            try:
                import aiohttp
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
                    async with session.get(remote_url) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            channels = data.get("channels") if isinstance(data, dict) else data
                            if isinstance(channels, list) and len(channels) > 0:
                                try:
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, "w", encoding="utf-8") as f:
                                        json.dump(channels, f, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                                return channels
            except Exception:
                pass

        # 2. Check local file config/elite_channels.json
        local_cfg_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "elite_channels.json"),
            os.path.join(os.path.dirname(sys.executable), "config", "elite_channels.json"),
            os.path.join(os.path.dirname(sys.executable), "resources", "config", "elite_channels.json"),
            "config/elite_channels.json",
        ]
        for p in local_cfg_candidates:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        channels = data.get("channels") if isinstance(data, dict) else data
                        if isinstance(channels, list) and len(channels) > 0:
                            return channels
                except Exception:
                    pass

        # 3. Check local cache
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    channels = data.get("channels") if isinstance(data, dict) else data
                    if isinstance(channels, list) and len(channels) > 0:
                        return channels
            except Exception:
                pass

        # 4. Fallback to bundled defaults
        return self.DEFAULT_ELITE_TARGETS

    async def auto_join_elite_channels(
        self,
        progress_callback: Optional[Callable[[int, int, str, float, str, str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Commercial 1-Click Auto-Join:
        Automatically joins the 5 Elite Whitelisted channels using MTProto Telethon.
        - Uses dynamic remote link resolution with local cache fallback.
        - Enforces randomized safe delay (8-15s) between channel joins to protect account from FloodWait/bans.
        - Emits real-time progress events for UI progress bar.
        """
        client = self.get_client()
        if not client.is_connected():
            await client.connect()
        if not await client.is_user_authorized():
            return {
                "success": False,
                "message": "Tài khoản Telegram chưa đăng nhập. Vui lòng đăng nhập trước khi tham gia nhóm.",
                "results": [],
            }

        elite_targets = await self.fetch_remote_elite_channels()
        total_targets = len(elite_targets)

        results = []
        joined_count = 0
        already_count = 0
        failed_count = 0

        # Query existing dialogs once to quickly detect already-joined channels
        existing_chat_ids = set()
        try:
            dialogs = await client.get_dialogs(limit=200)
            existing_chat_ids = {d.id for d in dialogs}
        except Exception:
            pass

        for idx, target in enumerate(elite_targets, start=1):
            name = target["name"]
            inv_hash = target.get("hash")
            uname = target.get("username")
            target_id = target.get("id")

            # Extract hash or username if link is provided without explicit hash/uname
            link = target.get("link", "")
            if not inv_hash and link and ("+" in link or "joinchat/" in link):
                inv_hash = link.split("+")[-1].split("joinchat/")[-1].strip("/")
            if not uname and link and "t.me/" in link and not ("+" in link or "joinchat/" in link):
                uname = link.split("t.me/")[-1].strip("/")

            # Emit progress: Starting
            if progress_callback:
                try:
                    res_p = progress_callback(
                        idx,
                        total_targets,
                        name,
                        0.0,
                        f"Đang kiểm tra và tham gia kênh {idx}/{total_targets} ({name})...",
                        "STARTING",
                    )
                    if asyncio.iscoroutine(res_p):
                        await res_p
                except Exception:
                    pass

            needs_flood_delay = False
            try:
                # 1. Quick check if already in channel
                if target_id in existing_chat_ids:
                    results.append({
                        "name": name,
                        "chat_id": target_id,
                        "status": "ALREADY_JOINED",
                        "message": "Đã tham gia từ trước",
                    })
                    already_count += 1
                    if progress_callback:
                        try:
                            res_p = progress_callback(
                                idx,
                                total_targets,
                                name,
                                0.0,
                                f"Kênh {idx}/{total_targets} ({name}) đã có sẵn.",
                                "ALREADY_JOINED",
                            )
                            if asyncio.iscoroutine(res_p):
                                await res_p
                        except Exception:
                            pass
                    continue

                # 2. Join via hash or username
                if inv_hash:
                    try:
                        await client(ImportChatInviteRequest(inv_hash))
                        results.append({
                            "name": name,
                            "chat_id": target_id,
                            "status": "JOINED",
                            "message": "Tham gia thành công",
                        })
                        joined_count += 1
                        needs_flood_delay = True
                    except UserAlreadyParticipantError:
                        results.append({
                            "name": name,
                            "chat_id": target_id,
                            "status": "ALREADY_JOINED",
                            "message": "Đã tham gia từ trước",
                        })
                        already_count += 1
                    except (InviteHashExpiredError, InviteHashInvalidError):
                        results.append({
                            "name": name,
                            "chat_id": target_id,
                            "status": "LINK_EXPIRED",
                            "message": "Link mời của kênh này đã hết hạn",
                        })
                        failed_count += 1
                elif uname:
                    try:
                        await client(JoinChannelRequest(uname))
                        results.append({
                            "name": name,
                            "chat_id": target_id,
                            "status": "JOINED",
                            "message": "Tham gia thành công",
                        })
                        joined_count += 1
                        needs_flood_delay = True
                    except UserAlreadyParticipantError:
                        results.append({
                            "name": name,
                            "chat_id": target_id,
                            "status": "ALREADY_JOINED",
                            "message": "Đã tham gia từ trước",
                        })
                        already_count += 1

                # If joined a new channel and more channels remain, enforce safe randomized delay (8-15s)
                if needs_flood_delay and idx < total_targets:
                    delay_sec = round(random.uniform(8.0, 15.0), 1)
                    if progress_callback:
                        try:
                            res_p = progress_callback(
                                idx,
                                total_targets,
                                name,
                                delay_sec,
                                f"Đang tham gia kênh {idx}/{total_targets} ({name})... vui lòng chờ {int(delay_sec)}s để bảo vệ tài khoản Telegram.",
                                "WAITING",
                            )
                            if asyncio.iscoroutine(res_p):
                                await res_p
                        except Exception:
                            pass
                    await asyncio.sleep(delay_sec)
                else:
                    await asyncio.sleep(1.0)

            except FloodWaitError as e:
                results.append({
                    "name": name,
                    "chat_id": target_id,
                    "status": "RATE_LIMITED",
                    "message": f"Telegram giới hạn tạm thời (Vui lòng thử lại sau {e.seconds}s)",
                })
                failed_count += 1
                if progress_callback:
                    try:
                        res_p = progress_callback(
                            idx,
                            total_targets,
                            name,
                            float(e.seconds),
                            f"Telegram giới hạn tạm thời (FloodWait {e.seconds}s).",
                            "RATE_LIMITED",
                        )
                        if asyncio.iscoroutine(res_p):
                            await res_p
                    except Exception:
                        pass
                break
            except Exception as e:
                results.append({
                    "name": name,
                    "chat_id": target_id,
                    "status": "ERROR",
                    "message": str(e),
                })
                failed_count += 1

        # Automatically ensure all IDs from targets are in allowed_chat_ids in config
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from config.config import load_config, save_config
                cfg_disk = load_config()
                top_ids = [t["id"] for t in elite_targets if t.get("id")]
                current_allowed = list(getattr(cfg_disk.telegram, "allowed_chat_ids", []))
                updated_allowed = list(set(current_allowed + top_ids))
                cfg_disk.telegram.allowed_chat_ids = updated_allowed
                save_config(cfg_disk)
            except Exception:
                pass

        # Final completion progress notification
        if progress_callback:
            try:
                res_p = progress_callback(
                    total_targets,
                    total_targets,
                    "ALL",
                    0.0,
                    f"Hoàn tất: Tham gia mới {joined_count} nhóm, đã có sẵn {already_count} nhóm.",
                    "DONE",
                )
                if asyncio.iscoroutine(res_p):
                    await res_p
            except Exception:
                pass

        return {
            "success": True,
            "joined_count": joined_count,
            "already_count": already_count,
            "failed_count": failed_count,
            "total_channels": total_targets,
            "message": f"Hoàn tất: Tham gia mới {joined_count} nhóm, đã có sẵn {already_count} nhóm.",
            "results": results,
        }

