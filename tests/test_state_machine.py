import os
from datetime import datetime
import pytest

from core.enums import EntryMode, PositionSide, SignalState
from core.models import ParsedSignal, SourceMetadata
from storage.database import DatabaseManager, SignalRepository
from storage.state_machine import InvalidStateTransitionError, SignalStateMachine


@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_trading.db")
    return DatabaseManager(db_file)


@pytest.fixture
def state_machine(temp_db):
    repo = SignalRepository(temp_db)
    return SignalStateMachine(repo), repo


def test_valid_state_transitions(state_machine):
    sm, repo = state_machine
    meta = SourceMetadata(chat_id=1, message_id=1, telegram_timestamp=datetime.utcnow())
    repo.save_message(1, 1, 123, meta.telegram_timestamp, meta.received_at, "BTC LONG", "BTC LONG")

    signal = ParsedSignal(
        signal_id="sig_state_1",
        metadata=meta,
        symbol_raw="BTC/USDT",
        symbol_candidate="BTCUSDT",
        side=PositionSide.LONG,
        validation_status=SignalState.RECEIVED,
    )
    repo.save_signal(signal)

    # RECEIVED -> PARSED
    sm.transition("sig_state_1", SignalState.RECEIVED, SignalState.PARSED)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.PARSED.value

    # PARSED -> VALIDATED
    sm.transition("sig_state_1", SignalState.PARSED, SignalState.VALIDATED)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.VALIDATED.value

    # VALIDATED -> ENTRY_PENDING
    sm.transition("sig_state_1", SignalState.VALIDATED, SignalState.ENTRY_PENDING)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.ENTRY_PENDING.value

    # ENTRY_PENDING -> OPEN_PROTECTED
    sm.transition("sig_state_1", SignalState.ENTRY_PENDING, SignalState.OPEN_PROTECTED)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.OPEN_PROTECTED.value

    # OPEN_PROTECTED -> EXITING
    sm.transition("sig_state_1", SignalState.OPEN_PROTECTED, SignalState.EXITING)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.EXITING.value

    # EXITING -> CLOSED
    sm.transition("sig_state_1", SignalState.EXITING, SignalState.CLOSED)
    assert repo.get_signal("sig_state_1")["state"] == SignalState.CLOSED.value


def test_invalid_state_transition_is_rejected(state_machine):
    sm, repo = state_machine
    # Trying to jump directly from RECEIVED to OPEN_PROTECTED without parsing or entry
    with pytest.raises(InvalidStateTransitionError):
        sm.transition("sig_state_2", SignalState.RECEIVED, SignalState.OPEN_PROTECTED)

    # Trying to reopen a CLOSED signal
    with pytest.raises(InvalidStateTransitionError):
        sm.transition("sig_state_3", SignalState.CLOSED, SignalState.ENTRY_PENDING)

