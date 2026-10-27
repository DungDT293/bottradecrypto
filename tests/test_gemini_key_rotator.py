import time
import pytest
from services.gemini_key_rotator import GeminiKeyRotator, GeminiKeySlot


def test_key_rotator_round_robin():
    keys = ["AIzaSyKey1_1234567890", "AIzaSyKey2_1234567890", "AIzaSyKey3_1234567890"]
    rotator = GeminiKeyRotator(initial_keys=keys)

    assert len(rotator.slots) == 3
    # First rotation
    assert rotator.get_next_key() == keys[0]
    assert rotator.get_next_key() == keys[1]
    assert rotator.get_next_key() == keys[2]
    # Second rotation (loops back)
    assert rotator.get_next_key() == keys[0]


def test_key_rotator_failover_429():
    keys = ["AIzaSyKey1_1234567890", "AIzaSyKey2_1234567890"]
    rotator = GeminiKeyRotator(initial_keys=keys)

    # Key 1 hits 429
    k1 = rotator.get_next_key()
    assert k1 == keys[0]
    rotator.mark_rate_limited(k1, cooldown_seconds=10.0, error_msg="Rate limit exceeded")

    # Next call must skip Key 1 and return Key 2
    k2 = rotator.get_next_key()
    assert k2 == keys[1]
    rotator.mark_success(k2)

    # Key 1 is still cooling down, so next call still returns Key 2
    assert rotator.get_next_key() == keys[1]


def test_key_rotator_depleted_402():
    keys = ["AIzaSyKey1_1234567890", "AIzaSyKey2_1234567890"]
    rotator = GeminiKeyRotator(initial_keys=keys)

    k1 = rotator.get_next_key()
    rotator.mark_depleted(k1, error_msg="Prepayment credits depleted")

    # k1 must be quarantined
    status = rotator.get_pool_status()
    assert status["active_keys"] == 1
    assert status["depleted_keys"] == 1

    # All future calls must only use k2
    for _ in range(5):
        assert rotator.get_next_key() == keys[1]


def test_key_rotator_load_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "AIzaSyA_1111111111, AIzaSyB_2222222222")
    monkeypatch.setenv("GEMINI_API_KEY_3", "AIzaSyC_3333333333")

    fake_env = tmp_path / ".env"
    fake_env.write_text("# empty\n", encoding="utf-8")

    rotator = GeminiKeyRotator()
    cnt = rotator.load_from_env(env_path=str(fake_env))
    assert cnt == 3
    assert len(rotator.slots) == 3


def test_key_rotator_deduplication():
    keys = ["AIzaSyKey1_1234567890", "AIzaSyKey1_1234567890", "AIzaSyKey2_1234567890"]
    rotator = GeminiKeyRotator(initial_keys=keys)
    assert len(rotator.slots) == 2
