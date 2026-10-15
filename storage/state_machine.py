from datetime import datetime
from typing import Optional, Set
from core.enums import SignalState
from core.exceptions import BotTradingError
from storage.database import SignalRepository


class InvalidStateTransitionError(BotTradingError):
    pass


class SignalStateMachine:
    """
    Guarantees valid transitions across lifecycle states:
    RECEIVED -> PARSED -> NEEDS_POLICY | NEEDS_REVIEW | REJECTED | VALIDATED
    VALIDATED -> ENTRY_PENDING -> PARTIALLY_FILLED -> OPEN_PROTECTED -> EXITING -> CLOSED
    Any active state can transition to ERROR if unrecoverable anomaly occurs.
    """

    ALLOWED_TRANSITIONS = {
        SignalState.RECEIVED: {SignalState.PARSED, SignalState.REJECTED},
        SignalState.PARSED: {
            SignalState.NEEDS_POLICY,
            SignalState.NEEDS_REVIEW,
            SignalState.REJECTED,
            SignalState.VALIDATED,
        },
        SignalState.NEEDS_POLICY: {SignalState.VALIDATED, SignalState.REJECTED},
        SignalState.NEEDS_REVIEW: {SignalState.VALIDATED, SignalState.REJECTED},
        SignalState.REJECTED: set(),  # Terminal
        SignalState.VALIDATED: {SignalState.ENTRY_PENDING, SignalState.REJECTED, SignalState.ERROR},
        SignalState.ENTRY_PENDING: {
            SignalState.PARTIALLY_FILLED,
            SignalState.OPEN_PROTECTED,
            SignalState.CLOSED,  # e.g. entry cancelled / TTL expired
            SignalState.ERROR,
        },
        SignalState.PARTIALLY_FILLED: {
            SignalState.OPEN_PROTECTED,
            SignalState.EXITING,
            SignalState.CLOSED,
            SignalState.ERROR,
        },
        SignalState.OPEN_PROTECTED: {
            SignalState.EXITING,
            SignalState.CLOSED,  # e.g. SL hit
            SignalState.ERROR,
        },
        SignalState.EXITING: {SignalState.CLOSED, SignalState.ERROR},
        SignalState.CLOSED: set(),  # Terminal
        SignalState.ERROR: {SignalState.CLOSED},  # Can be closed after manual review/reconciliation
    }

    def __init__(self, repo: SignalRepository):
        self.repo = repo

    def transition(self, signal_id: str, current_state: SignalState, target_state: SignalState, reason: Optional[str] = None) -> None:
        allowed = self.ALLOWED_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            raise InvalidStateTransitionError(
                f"Khong the chuyen trang thai tin hieu tu '{current_state.value}' sang '{target_state.value}'. "
                f"Cac trang thai hop le: {[s.value for s in allowed]}"
            )

        self.repo.update_signal_state(signal_id, target_state, reason)

