from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from config.config import load_config
from core.enums import PositionSide, SignalState, UpdateType
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from storage.database import DatabaseManager, SignalRepository
from telegram.listener import TelegramSignalListener


class MockTelegramEvent:
    def __init__(self, chat_id, msg_id, text, orig_date, edit_date=None, reply_to_msg_id=None):
        self.chat_id = chat_id
        self.id = msg_id
        self.raw_text = text
        self.date = orig_date
        self.edit_date = edit_date
        self.reply_to_msg_id = reply_to_msg_id
        self.sender_id = 999


@pytest.fixture
def listener_setup(tmp_path):
    db_file = str(tmp_path / "test_listener.db")
    db = DatabaseManager(db_file)
    config = load_config()
    # Allow test chat
    config.telegram.allowed_chat_ids = [1000]
    config.risk.signal_max_age_seconds = 300
    config.telegram.reconnect_max_backlog_seconds = 300

    listener = TelegramSignalListener(config, None, db)
    return listener, db


@pytest.mark.asyncio
async def test_new_signal_expired_is_blocked(listener_setup):
    """Test 1: Tin moi nhung qua han (> 300s) -> bi chan, khong vao lenh."""
    listener, db = listener_setup
    repo = SignalRepository(db)

    # Message posted 400 seconds ago
    old_time = datetime.now(timezone.utc) - timedelta(seconds=400)
    raw_text = "BTC/USDT LONG\nEntry: 60000\nSL: 58000\nTP: 65000"
    event = MockTelegramEvent(chat_id=1000, msg_id=10, text=raw_text, orig_date=old_time)

    await listener.handle_incoming_message(event, is_edit=False)

    # Should NOT have recorded a signal
    assert repo.get_signal("sig_1000_10") is None


@pytest.mark.asyncio
async def test_old_signal_recent_edit_is_accepted(listener_setup):
    """Test 2: Tin goc cu (5 gio truoc), edit moi (10 giay truoc), keo dang mo -> edit duoc chap nhan."""
    listener, db = listener_setup
    repo = SignalRepository(db)

    orig_time = datetime.now(timezone.utc) - timedelta(hours=5)
    recent_edit_time = datetime.now(timezone.utc) - timedelta(seconds=10)

    # 1. First version stored in history
    raw_text_v1 = "ETH/USDT LONG\nEntry: 2500\nSL: 2400\nTP: 2800"
    repo.save_message_version(
        chat_id=1000,
        message_id=20,
        event_date=orig_time.replace(tzinfo=None),
        received_at=datetime.utcnow() - timedelta(hours=5),
        raw_text=raw_text_v1,
        normalized_text=raw_text_v1,
        fingerprint="fp1",
        is_edit=False,
    )

    # 2. Edit arrives: SL tightened to 2450
    raw_text_v2 = "ETH/USDT LONG\nEntry: 2500\nSL: 2450\nTP: 2800"
    edit_event = MockTelegramEvent(
        chat_id=1000,
        msg_id=20,
        text=raw_text_v2,
        orig_date=orig_time,
        edit_date=recent_edit_time,
    )

    await listener.handle_incoming_message(edit_event, is_edit=True)

    # Version 2 must be recorded
    versions = [dict(r) for r in db.get_connection().execute("SELECT * FROM message_versions WHERE message_id = 20").fetchall()]
    assert len(versions) == 2
    assert versions[1]["version"] == 2
    assert "2450" in versions[1]["raw_text"]


@pytest.mark.asyncio
async def test_duplicate_edit_is_ignored(listener_setup):
    """Test 3: Edit trung lap -> bo qua khong tao version moi."""
    listener, db = listener_setup

    orig_time = datetime.now(timezone.utc) - timedelta(minutes=2)
    raw_text = "SOL/USDT LONG\nEntry: 150\nSL: 140\nTP: 180"

    event1 = MockTelegramEvent(1000, 30, raw_text, orig_time)
    await listener.handle_incoming_message(event1, is_edit=False)

    # Same text sent as edit
    event2 = MockTelegramEvent(1000, 30, raw_text, orig_time, edit_date=datetime.now(timezone.utc))
    await listener.handle_incoming_message(event2, is_edit=True)

    # Must still have only 1 version
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM message_versions WHERE message_id = 30").fetchone()["c"]
    assert count == 1


@pytest.mark.asyncio
async def test_out_of_order_edit_is_flagged(listener_setup):
    """Test 4: Edit den sai thu tu (timestamp cu hon phien ban hien tai) -> canh bao va bo qua."""
    listener, db = listener_setup
    repo = SignalRepository(db)

    now = datetime.utcnow()
    # Save version 1 at 12:00
    repo.save_message_version(1000, 40, now, now, "Text v1", "Text v1", "fp1", is_edit=False)
    # Save version 2 at 12:10
    repo.save_message_version(1000, 40, now + timedelta(minutes=10), now, "Text v2", "Text v2", "fp2", is_edit=True)

    # An edit arrives with timestamp 12:05 (older than version 2)
    v, is_valid, status = repo.save_message_version(
        1000, 40, now + timedelta(minutes=5), now, "Text v3 stale", "Text v3 stale", "fp3", is_edit=True
    )
    assert is_valid is False
    assert status == "OUT_OF_ORDER"


@pytest.mark.asyncio
async def test_unanchored_first_edit(listener_setup):
    """Test 5: Edit khong co phien ban truoc (unanchored) -> duoc ghi nhan la version 1 unanchored."""
    listener, db = listener_setup
    repo = SignalRepository(db)

    now = datetime.utcnow()
    v, is_valid, status = repo.save_message_version(
        1000, 50, now, now, "Edit text without prior version", "Edit text", "fp_unanchored", is_edit=True
    )
    assert v == 1
    assert is_valid is True
    assert status == "UNANCHORED"


@pytest.mark.asyncio
async def test_reconnect_backlog_drops_stale_update(listener_setup):
    """Test 6: Reconnect va nhan update ton dong qua 300s -> bi chan."""
    listener, db = listener_setup
    stale_edit_time = datetime.now(timezone.utc) - timedelta(seconds=600)

    event = MockTelegramEvent(
        chat_id=1000,
        msg_id=60,
        text="Update text",
        orig_date=datetime.now(timezone.utc) - timedelta(hours=1),
        edit_date=stale_edit_time,
    )
    await listener.handle_incoming_message(event, is_edit=True)

    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM message_versions WHERE message_id = 60").fetchone()["c"]
    assert count == 0

