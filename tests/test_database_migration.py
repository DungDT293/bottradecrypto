from datetime import datetime

from storage.database import DatabaseManager


def test_schema_migration_and_integrity_report(tmp_path):
    db = DatabaseManager(str(tmp_path / "runtime.db"))
    report = db.integrity_report()
    assert report["integrity"] == "ok"
    assert report["foreign_keys"] == []
    assert report["migration_version"] >= 1
    DatabaseManager(str(tmp_path / "runtime.db"))
    assert DatabaseManager(str(tmp_path / "runtime.db")).integrity_report()["migration_version"] >= 1


def test_wal_safe_backup_restores_ledger(tmp_path):
    source_path = tmp_path / "source.db"
    backup_path = tmp_path / "backup.db"
    source = DatabaseManager(str(source_path))
    from storage.database import LedgerRepository
    ledger = LedgerRepository(source)
    assert ledger.append_event({
        "event_key": "backup-event",
        "account_scope": "paper:test",
        "execution_mode": "PAPER",
        "event_type": "REALIZED_PNL",
        "source": "TEST",
        "occurred_at": datetime.utcnow().isoformat(),
        "amount": "1.23",
        "raw_payload_json": "{}",
    })
    source.backup_to(str(backup_path))
    restored = DatabaseManager(str(backup_path))
    assert len(LedgerRepository(restored).get_events("paper:test", "PAPER")) == 1
