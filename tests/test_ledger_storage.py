from datetime import datetime
from decimal import Decimal

from storage.database import DatabaseManager, LedgerRepository


def test_ledger_event_insert_is_idempotent(tmp_path):
    db = DatabaseManager(str(tmp_path / "ledger.db"))
    ledger = LedgerRepository(db)
    event = {
        "event_key": "binance:testnet:trade:BTCUSDT:1",
        "account_scope": "binance:testnet:test",
        "execution_mode": "TESTNET",
        "event_type": "TRADE_FILL",
        "source": "REST_BACKFILL",
        "occurred_at": datetime.utcnow().isoformat(),
        "amount": Decimal("1.25"),
        "raw_payload_json": "{}",
    }
    assert ledger.append_event(event) is True
    assert ledger.append_event(event) is False
    rows = ledger.get_events("binance:testnet:test", "TESTNET")
    assert len(rows) == 1
    assert rows[0]["amount"] == "1.25"


def test_ledger_scopes_and_half_open_window(tmp_path):
    db = DatabaseManager(str(tmp_path / "ledger_scope.db"))
    ledger = LedgerRepository(db)
    base = {
        "account_scope": "account-a",
        "execution_mode": "TESTNET",
        "event_type": "FUNDING_FEE",
        "source": "REST",
        "amount": "1",
        "raw_payload_json": "{}",
    }
    assert ledger.append_event({**base, "event_key": "a", "occurred_at": "2026-01-01T00:00:00"})
    assert ledger.append_event({**base, "event_key": "b", "occurred_at": "2026-01-02T00:00:00"})
    assert len(ledger.get_events("account-a", "TESTNET", "2026-01-01T00:00:00", "2026-01-02T00:00:00")) == 1
    assert ledger.get_events("account-b", "TESTNET") == []
