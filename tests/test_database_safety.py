from datetime import datetime

import pytest

from core.enums import PositionSide, SignalState
from core.models import ParsedSignal, SourceMetadata
from storage.database import DatabaseManager, SignalRepository
from storage.state_machine import InvalidStateTransitionError


def test_memory_database_is_rejected():
    with pytest.raises(ValueError, match="file-backed"):
        DatabaseManager(":memory:")


def test_state_update_rejects_illegal_transition(tmp_path):
    db = DatabaseManager(str(tmp_path / "state.db"))
    repo = SignalRepository(db)
    now = datetime.utcnow()
    repo.save_message(1, 1, 1, now, now, "signal", "signal")
    repo.save_signal(ParsedSignal(
        signal_id="sig_db_state",
        metadata=SourceMetadata(chat_id=1, message_id=1, telegram_timestamp=now),
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        validation_status=SignalState.RECEIVED,
    ))

    with pytest.raises(InvalidStateTransitionError):
        repo.update_signal_state("sig_db_state", SignalState.CLOSED)
