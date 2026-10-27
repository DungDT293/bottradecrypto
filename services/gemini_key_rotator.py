import os
import re
import time
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("gemini_key_rotator")


@dataclass
class GeminiKeySlot:
    api_key: str
    status: str = "ACTIVE"  # ACTIVE, COOLING_DOWN, DEPLETED, INVALID
    cooldown_until: float = 0.0
    requests_count: int = 0
    success_count: int = 0
    error_count: int = 0
    last_error: str = ""
    last_used: float = 0.0

    @property
    def masked_key(self) -> str:
        k = self.api_key.strip()
        if len(k) <= 8:
            return "***"
        return f"{k[:4]}...{k[-4:]}"

    def is_healthy(self) -> bool:
        if self.status in ("DEPLETED", "INVALID"):
            return False
        if self.status == "COOLING_DOWN":
            if time.time() >= self.cooldown_until:
                self.status = "ACTIVE"
                self.cooldown_until = 0.0
                return True
            return False
        return True


class GeminiKeyRotator:
    """
    Institutional Round-Robin Key Pool for Google Gemini API.
    Supports 1 to N API keys with automatic failover, 429 rate limit cooldown,
    and 402/400 quarantine.
    """

    _instance: Optional["GeminiKeyRotator"] = None

    @classmethod
    def get_instance(cls) -> "GeminiKeyRotator":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load_from_env()
        return cls._instance

    def __init__(self, initial_keys: Optional[List[str]] = None):
        self.slots: List[GeminiKeySlot] = []
        self._current_index: int = 0
        if initial_keys:
            self.set_keys(initial_keys)

    def set_keys(self, raw_keys: List[str]) -> None:
        """Sets or replaces the active key pool, deduplicating valid keys."""
        seen = set()
        new_slots = []
        for rk in raw_keys:
            if not rk:
                continue
            clean = rk.strip()
            if clean and len(clean) >= 10 and clean not in seen:
                seen.add(clean)
                new_slots.append(GeminiKeySlot(api_key=clean))

        self.slots = new_slots
        self._current_index = 0
        logger.info(f"[GeminiKeyRotator] Pool configured with {len(self.slots)} key(s).")

    def load_from_env(self, env_path: Optional[str] = None) -> int:
        """
        Parses all possible Gemini API keys.
        Priority:
        1. Read directly from .env file (user explicit config)
        2. Fallback to os.environ if .env has no keys
        """
        collected_keys: List[str] = []

        # 1. Read directly from .env file first (Primary Source of Truth)
        candidates = [env_path, ".env", "config/.env"]
        target_env = next((p for p in candidates if p and os.path.exists(p)), None)
        if target_env:
            try:
                with open(target_env, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k_name, k_val = line.split("=", 1)
                        k_name = k_name.strip()
                        k_val = k_val.strip().strip("'\"")
                        if k_name in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or k_name.startswith("GEMINI_API_KEY_"):
                            for part in re.split(r"[,;\n\r\t]+", k_val):
                                clean = part.strip()
                                if clean and len(clean) >= 10:
                                    collected_keys.append(clean)
            except Exception as e:
                logger.debug(f"[GeminiKeyRotator] Error parsing {target_env}: {e}")

        # 2. If no keys in .env, fallback to os.environ
        if not collected_keys:
            env_vars = ["GEMINI_API_KEYS", "GEMINI_API_KEY"]
            for v in env_vars:
                val = os.getenv(v)
                if val:
                    for part in re.split(r"[,;\n\r\t]+", val):
                        clean = part.strip()
                        if clean and len(clean) >= 10:
                            collected_keys.append(clean)

            for i in range(1, 21):
                val = os.getenv(f"GEMINI_API_KEY_{i}")
                if val:
                    clean = val.strip()
                    if clean and len(clean) >= 10:
                        collected_keys.append(clean)

        self.set_keys(collected_keys)
        return len(self.slots)

    def get_next_key(self) -> Optional[str]:
        """
        Retrieves the next healthy key in round-robin sequence.
        Returns None if no keys are configured or all keys are in quarantine.
        """
        if not self.slots:
            return None

        total = len(self.slots)
        now = time.time()

        for _ in range(total):
            slot = self.slots[self._current_index]
            self._current_index = (self._current_index + 1) % total

            if slot.is_healthy():
                slot.last_used = now
                slot.requests_count += 1
                return slot.api_key

        # If all keys are in cooldown, find the one with the earliest expiration
        cooling_slots = [s for s in self.slots if s.status == "COOLING_DOWN"]
        if cooling_slots:
            cooling_slots.sort(key=lambda s: s.cooldown_until)
            earliest = cooling_slots[0]
            remaining = max(0.0, earliest.cooldown_until - now)
            logger.warning(
                f"[GeminiKeyRotator] All {total} keys currently cooling down. Earliest ready in {remaining:.1f}s."
            )

        return None

    def mark_success(self, api_key: str) -> None:
        """Records a successful request for this key."""
        slot = self._find_slot(api_key)
        if slot:
            slot.success_count += 1
            if slot.status == "COOLING_DOWN":
                slot.status = "ACTIVE"
                slot.cooldown_until = 0.0

    def mark_rate_limited(self, api_key: str, cooldown_seconds: float = 60.0, error_msg: str = "") -> None:
        """Puts a specific key into temporary cooldown (HTTP 429) without affecting others."""
        slot = self._find_slot(api_key)
        if slot:
            slot.status = "COOLING_DOWN"
            slot.cooldown_until = time.time() + cooldown_seconds
            slot.error_count += 1
            slot.last_error = f"HTTP 429 Rate Limit: {error_msg}"
            logger.warning(
                f"[GeminiKeyRotator] Key {slot.masked_key} rate-limited. Cooling down for {cooldown_seconds}s."
            )

    def mark_depleted(self, api_key: str, error_msg: str = "") -> None:
        """Marks a key as DEPLETED (HTTP 402 prepayment credit exhausted)."""
        slot = self._find_slot(api_key)
        if slot:
            slot.status = "DEPLETED"
            slot.error_count += 1
            slot.last_error = f"HTTP 402 Credits Depleted: {error_msg}"
            logger.error(
                f"[GeminiKeyRotator] Key {slot.masked_key} DEPLETED (Credits exhausted). Quarantined."
            )

    def mark_invalid(self, api_key: str, error_msg: str = "") -> None:
        """Marks a key as INVALID (HTTP 400 invalid argument)."""
        slot = self._find_slot(api_key)
        if slot:
            slot.status = "INVALID"
            slot.error_count += 1
            slot.last_error = f"HTTP 400 Invalid Key: {error_msg}"
            logger.error(
                f"[GeminiKeyRotator] Key {slot.masked_key} INVALID. Quarantined."
            )

    def has_healthy_keys(self) -> bool:
        """Returns True if at least one key is healthy or will recover soon."""
        return any(s.is_healthy() for s in self.slots)

    def get_pool_status(self) -> Dict[str, Any]:
        """Provides status breakdown for monitoring and Telegram reports."""
        now = time.time()
        active = sum(1 for s in self.slots if s.is_healthy())
        cooling = sum(1 for s in self.slots if s.status == "COOLING_DOWN" and not s.is_healthy())
        depleted = sum(1 for s in self.slots if s.status == "DEPLETED")
        invalid = sum(1 for s in self.slots if s.status == "INVALID")

        details = []
        for s in self.slots:
            rem = max(0, int(s.cooldown_until - now)) if s.status == "COOLING_DOWN" else 0
            details.append({
                "masked_key": s.masked_key,
                "status": s.status,
                "cooldown_remaining_sec": rem,
                "requests": s.requests_count,
                "successes": s.success_count,
                "errors": s.error_count,
                "last_error": s.last_error,
            })

        return {
            "total_keys": len(self.slots),
            "active_keys": active,
            "cooling_keys": cooling,
            "depleted_keys": depleted,
            "invalid_keys": invalid,
            "has_healthy": active > 0,
            "details": details,
        }

    def _find_slot(self, api_key: str) -> Optional[GeminiKeySlot]:
        clean = api_key.strip()
        for s in self.slots:
            if s.api_key == clean:
                return s
        return None

