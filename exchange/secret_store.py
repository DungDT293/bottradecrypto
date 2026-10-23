from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Dict, Optional, Protocol


class SecretStoreError(RuntimeError):
    pass


class SecretStoreUnavailable(SecretStoreError):
    pass


class SecretStore(Protocol):
    def get(self, name: str) -> Optional[str]: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...
    def available(self) -> bool: ...


class WindowsDpapiStore:
    """Current-user DPAPI store. Raises on non-Windows or crypto failure."""

    def __init__(self, directory: Optional[str] = None):
        if os.name != "nt":
            raise SecretStoreUnavailable("DPAPI is available only on Windows")
        self.directory = Path(directory or os.path.join(os.environ.get("LOCALAPPDATA", ""), "telegram-binance-signal-executor", "secrets"))
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = name.replace("/", "__").replace("\\", "__")
        return self.directory / f"{safe}.dpapi"

    def get(self, name: str) -> Optional[str]:
        path = self._path(name)
        if not path.exists():
            return None
        try:
            crypt32 = ctypes.windll.crypt32
            kernel32 = ctypes.windll.kernel32
            class Blob(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
            raw = path.read_bytes()
            source = Blob(len(raw), (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw))
            output = Blob()
            if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
                raise SecretStoreError("DPAPI decrypt failed")
            data = ctypes.string_at(output.pbData, output.cbData)
            kernel32.LocalFree(output.pbData)
            return data.decode("utf-8")
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreUnavailable("DPAPI unavailable") from exc

    def set(self, name: str, value: str) -> None:
        if not value:
            raise SecretStoreError("Secret value cannot be empty")
        try:
            crypt32 = ctypes.windll.crypt32
            class Blob(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
            data = value.encode("utf-8")
            source = Blob(len(data), (ctypes.c_ubyte * len(data)).from_buffer_copy(data))
            output = Blob()
            if not crypt32.CryptProtectData(ctypes.byref(source), "TBCE", None, None, None, 1, ctypes.byref(output)):
                raise SecretStoreError("DPAPI encrypt failed")
            encrypted = ctypes.string_at(output.pbData, output.cbData)
            ctypes.windll.kernel32.LocalFree(output.pbData)
            path = self._path(name)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(encrypted)
            os.replace(tmp, path)
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreUnavailable("DPAPI unavailable") from exc

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink(missing_ok=True)
        except Exception as exc:
            raise SecretStoreUnavailable("DPAPI delete failed") from exc

    def available(self) -> bool:
        return os.name == "nt"


class _CredentialFileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class WindowsCredentialManagerStore:
    """Current-user Windows Credential Manager generic credential store."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class _Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _CredentialFileTime),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    PREFIX = "telegram-binance-signal-executor/"

    def __init__(self):
        if os.name != "nt":
            raise SecretStoreUnavailable("Credential Manager is available only on Windows")
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi.CredReadW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(self._Credential))]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(self._Credential), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def _target(self, name: str) -> str:
        return self.PREFIX + name

    def get(self, name: str) -> Optional[str]:
        result = ctypes.POINTER(self._Credential)()
        if not self._advapi.CredReadW(self._target(name), self.CRED_TYPE_GENERIC, 0, ctypes.byref(result)):
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                return None
            raise SecretStoreUnavailable(f"Credential Manager read failed ({error})")
        try:
            blob = ctypes.string_at(result.contents.CredentialBlob, result.contents.CredentialBlobSize)
            return blob.decode("utf-8")
        finally:
            self._advapi.CredFree(result)

    def set(self, name: str, value: str) -> None:
        if not value:
            raise SecretStoreError("Secret value cannot be empty")
        target = self._target(name)
        encoded = value.encode("utf-8")
        buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = self._Credential(
            0,
            self.CRED_TYPE_GENERIC,
            target,
            None,
            _CredentialFileTime(0, 0),
            len(encoded),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            self.CRED_PERSIST_LOCAL_MACHINE,
            0,
            None,
            None,
            None,
        )
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise SecretStoreUnavailable(f"Credential Manager write failed ({ctypes.get_last_error()})")

    def delete(self, name: str) -> None:
        if not self._advapi.CredDeleteW(self._target(name), self.CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != 1168:
                raise SecretStoreUnavailable(f"Credential Manager delete failed ({error})")

    def available(self) -> bool:
        return os.name == "nt"


class MemorySecretStore:
    """Test-only in-memory store; never persists secrets."""

    def __init__(self) -> None:
        self._values: Dict[str, str] = {}

    def get(self, name: str) -> Optional[str]:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        if not value:
            raise SecretStoreError("Secret value cannot be empty")
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)

    def available(self) -> bool:
        return True


class EnvironmentSecretStore:
    """Read-only environment provider; writes fail instead of creating plaintext files."""

    PREFIX = "TBCE_SECRET_"

    def get(self, name: str) -> Optional[str]:
        return os.environ.get(self.PREFIX + name.upper().replace("/", "_"))

    def set(self, name: str, value: str) -> None:
        raise SecretStoreUnavailable("Environment secret store is read-only")

    def delete(self, name: str) -> None:
        raise SecretStoreUnavailable("Environment secret store is read-only")

    def available(self) -> bool:
        return True


def credential_name(mode: str, field: str) -> str:
    return f"binance/{mode.lower()}/{field}"


class BinanceCredentialProvider:
    def __init__(self, store: SecretStore) -> None:
        self.store = store

    def get(self, mode: str) -> tuple[Optional[str], Optional[str]]:
        normalized = mode.upper()
        return (
            self.store.get(credential_name(normalized, "api-key")),
            self.store.get(credential_name(normalized, "api-secret")),
        )

    def set(self, mode: str, api_key: str, api_secret: str) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise SecretStoreError("API key and secret are required")
        self.store.set(credential_name(mode, "api-key"), api_key.strip())
        self.store.set(credential_name(mode, "api-secret"), api_secret.strip())

    def delete(self, mode: str) -> None:
        self.store.delete(credential_name(mode, "api-key"))
        self.store.delete(credential_name(mode, "api-secret"))
