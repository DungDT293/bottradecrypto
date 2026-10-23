"""
Commercial License Management & Device Binding Service.
Protects application IP, manages trial and VIP activations,
and enforces machine HWID binding.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

def _signing_secret() -> bytes:
    secret = os.environ.get("LICENSE_MASTER_SECRET", "").strip()
    if not secret:
        raise RuntimeError("LICENSE_MASTER_SECRET is not configured")
    return secret.encode("utf-8")

class LicenseService:
    def __init__(
        self,
        data_dir: Optional[str] = None,
        license_file: Optional[str] = None,
        trial_file: Optional[str] = None,
    ):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            self.data_dir = Path(appdata) / "telegram_binance_signal_executor"
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.license_file = Path(license_file) if license_file else self.data_dir / "license.json"
        self.trial_file = Path(trial_file) if trial_file else self.data_dir / ".trial_claimed"
        self._cached_hwid: Optional[str] = None

    def get_hardware_id(self) -> str:
        """
        Generates a deterministic, unique, privacy-preserving Machine HWID.
        Combines machine hostname, processor architecture, and hardware UUID.
        """
        if self._cached_hwid:
            return self._cached_hwid
        
        raw_parts = [
            platform.node(),
            platform.processor(),
            str(uuid.getnode()),
            platform.machine(),
        ]
        raw_string = "|".join(raw_parts)
        digest = hashlib.sha256(raw_string.encode("utf-8")).hexdigest().upper()
        self._cached_hwid = f"HWID-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"
        return self._cached_hwid

    def get_machine_hwid(self) -> str:
        """Alias for get_hardware_id."""
        return self.get_hardware_id()

    def _sign_payload(self, hwid: str, plan: str, expires_epoch: int) -> str:
        msg = f"{hwid.strip().upper()}|{plan.strip().upper()}|{expires_epoch}".encode("utf-8")
        return hmac.new(_signing_secret(), msg, hashlib.sha256).hexdigest()[:16].upper()

    def generate_license_key(
        self,
        hwid: str,
        days: int = 30,
        plan: str = "VIP_MONTHLY",
        duration_days: Optional[int] = None,
        plan_name: Optional[str] = None,
    ) -> str:
        """
        Admin method to generate cryptographic license key bound to a specific HWID.
        Use days=0 or days>=9999 for LIFETIME.
        """
        effective_days = duration_days if duration_days is not None else days
        effective_plan = plan_name if plan_name is not None else plan

        now_epoch = int(time.time())
        if effective_days <= 0 or effective_plan == "LIFETIME" or effective_days >= 9999:
            expires_epoch = 0  # 0 indicates lifetime access
            target_plan = "LIFETIME"
        else:
            expires_epoch = now_epoch + (effective_days * 86400)
            target_plan = effective_plan.upper()

        clean_hwid = hwid.strip().upper()
        sig = self._sign_payload(clean_hwid, target_plan, expires_epoch)
        
        payload = {
            "h": clean_hwid,
            "p": target_plan,
            "e": expires_epoch,
            "s": sig
        }
        raw_json = json.dumps(payload, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("utf-8").rstrip("=")
        return f"VIP-{encoded}"

    def verify_license_key(self, key_string: str) -> Dict[str, Any]:
        """
        Verifies a license key against current machine HWID and expiration.
        """
        clean_key = key_string.strip()
        if not clean_key.startswith("VIP-"):
            return {"valid": False, "reason": "Định dạng License Key không hợp lệ (Phải bắt đầu bằng VIP-)"}

        b64_part = clean_key[4:]
        # Add padding back if necessary
        rem = len(b64_part) % 4
        if rem > 0:
            b64_part += "=" * (4 - rem)

        try:
            raw_bytes = base64.urlsafe_b64decode(b64_part.encode("utf-8"))
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return {"valid": False, "reason": "Mã License Key bị sai cấu trúc hoặc bị hỏng"}

        req_hwid = payload.get("h", "").strip().upper()
        plan = payload.get("p", "VIP").strip().upper()
        expires_epoch = int(payload.get("e", 0))
        provided_sig = payload.get("s", "").strip().upper()

        current_hwid = self.get_hardware_id()
        if req_hwid == "ANY":
            return {"valid": False, "reason": "Universal license keys are disabled"}
        if req_hwid != current_hwid:
            return {
                "valid": False,
                "reason": f"Mã bản quyền này thuộc về máy khác ({req_hwid}). Mã máy của bạn là {current_hwid}",
            }

        # Verify signature
        expected_sig = self._sign_payload(req_hwid, plan, expires_epoch)
        if not hmac.compare_digest(provided_sig, expected_sig):
            return {"valid": False, "reason": "Chữ ký xác thực bản quyền không hợp lệ (Mã giả mạo)"}

        # Check expiration
        now_epoch = int(time.time())
        if expires_epoch > 0 and now_epoch > expires_epoch:
            expire_date_str = datetime.fromtimestamp(expires_epoch, timezone.utc).strftime("%d/%m/%Y %H:%M")
            return {
                "valid": False,
                "reason": f"Bản quyền gói {plan} đã hết hạn vào ngày {expire_date_str}. Vui lòng liên hệ Admin gia hạn.",
            }

        days_remaining = None
        if expires_epoch > 0:
            days_remaining = max(1, int((expires_epoch - now_epoch) / 86400))

        return {
            "valid": True,
            "plan": plan,
            "expires_epoch": expires_epoch,
            "days_remaining": days_remaining,
            "is_lifetime": expires_epoch == 0,
            "hwid": req_hwid,
        }

    def activate_key(self, key_string: str) -> Dict[str, Any]:
        """
        Validates and activates a license key, saving it to disk.
        """
        ver = self.verify_license_key(key_string)
        if not ver["valid"]:
            return {"success": False, "message": ver["reason"]}

        license_data = {
            "key": key_string.strip(),
            "plan": ver["plan"],
            "hwid": self.get_hardware_id(),
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "expires_epoch": ver["expires_epoch"],
            "is_lifetime": ver["is_lifetime"],
        }

        try:
            with open(self.license_file, "w", encoding="utf-8") as f:
                json.dump(license_data, f, indent=2)
            return {
                "success": True,
                "plan": ver["plan"],
                "message": f"Kích hoạt thành công gói {ver['plan']}! " + (
                    "Bản quyền Vĩnh Viễn." if ver['is_lifetime'] else f"Thời hạn còn {ver['days_remaining']} ngày."
                ),
                "license": self.get_license_info()
            }
        except Exception as e:
            return {"success": False, "message": f"Lỗi lưu trữ bản quyền: {str(e)}"}

    def activate_trial(self) -> Dict[str, Any]:
        """
        Activates a 3-day Free Trial if this machine has never used trial before.
        """
        info = self.get_license_info()
        if info["is_active"]:
            return {"success": False, "message": "Máy của bạn hiện đang có bản quyền hoạt động!"}

        trial_marker_file = self.trial_file
        if trial_marker_file.exists():
            return {
                "success": False,
                "message": "Thiết bị này đã từng sử dụng lượt Dùng Thử Miễn Phí. Vui lòng nâng cấp bản quyền VIP để tiếp tục.",
            }

        # Generate a 3-day trial key
        hwid = self.get_hardware_id()
        trial_key = self.generate_license_key(hwid, days=3, plan="TRIAL_3_DAYS")
        res = self.activate_key(trial_key)
        if res["success"]:
            try:
                with open(trial_marker_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"hwid": hwid, "claimed_at": datetime.now(timezone.utc).isoformat()}))
            except Exception:
                pass
            res["message"] = "Kích hoạt Dùng Thử 3 Ngày thành công! Hãy trải nghiệm bot tự động cùng 5 nhóm tinh hoa."
        return res

    def get_license_info(self) -> Dict[str, Any]:
        """
        Returns full status of current machine license for UI rendering.
        """
        hwid = self.get_hardware_id()
        if not self.license_file.exists():
            return {
                "is_active": False,
                "status": "UNLICENSED",
                "plan": "FREE",
                "days_remaining": 0,
                "expires_at": None,
                "is_lifetime": False,
                "hwid": hwid,
                "message": "Chưa kích hoạt bản quyền. Vui lòng nhập License Key hoặc bấm Dùng Thử 3 Ngày.",
            }

        try:
            with open(self.license_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("key", "")
            ver = self.verify_license_key(key)
            if not ver["valid"]:
                return {
                    "is_active": False,
                    "status": "EXPIRED",
                    "plan": data.get("plan", "EXPIRED"),
                    "days_remaining": 0,
                    "expires_at": None,
                    "is_lifetime": False,
                    "hwid": hwid,
                    "message": ver["reason"],
                }

            expires_at_iso = None
            if ver["expires_epoch"] > 0:
                expires_at_iso = datetime.fromtimestamp(ver["expires_epoch"], timezone.utc).isoformat()

            return {
                "is_active": True,
                "status": "ACTIVE",
                "plan": ver["plan"],
                "days_remaining": ver["days_remaining"],
                "expires_at": expires_at_iso,
                "is_lifetime": ver["is_lifetime"],
                "hwid": hwid,
                "message": "Bản quyền hợp lệ",
            }
        except Exception as e:
            return {
                "is_active": False,
                "status": "ERROR",
                "plan": "UNKNOWN",
                "days_remaining": 0,
                "expires_at": None,
                "is_lifetime": False,
                "hwid": hwid,
                "message": f"Không thể đọc file bản quyền: {str(e)}",
            }
