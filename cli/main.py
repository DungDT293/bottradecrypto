import argparse
import asyncio
import os
import sys
from datetime import datetime
from decimal import Decimal
from typing import Optional
from rich.console import Console
from rich.table import Table

from config.config import load_config
from core.enums import ExecutionMode, SignalState
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository
from telegram.auth_helper import TelegramAuthHelper
from telegram.client import TelegramUserClient
from tests.fixtures.sample_signals import SAMPLE_SIGNALS

console = Console()


def cmd_telegram_login(args):
    """CLI: telegram-login"""
    config = load_config(args.config)
    helper = TelegramAuthHelper(config)
    asyncio.run(helper.login_interactive())


def cmd_list_chats(args):
    """CLI: list-chats"""
    config = load_config(args.config)
    if not config.telegram.api_id or not config.telegram.api_hash:
        print("[BLOCKED] Thieu TELEGRAM_API_ID hoac TELEGRAM_API_HASH trong file .env.")
        print("Vui long lay tai https://my.telegram.org va dien vao file .env.")
        return

    client_wrapper = TelegramUserClient(config)

    async def _run():
        try:
            dialogs = await client_wrapper.list_dialogs()
            table = Table(title="DANH SACH NHOM / KENH TELEGRAM")
            table.add_column("Chat ID", style="cyan", no_wrap=True)
            table.add_column("Ten Nhom / Kenh", style="magenta")
            table.add_column("Loai", style="green")
            table.add_column("Tin chua doc", justify="right")

            for d in dialogs:
                kind = "Kenh (Channel)" if d["is_channel"] else "Nhom (Group)"
                table.add_row(str(d["id"]), d["title"], kind, str(d["unread_count"]))

            console.print(table)
            print("\nHuong dan: Copy Chat ID cua kenh can theo doi vao muc `allowed_chat_ids` trong file `config.yaml`.")
        except Exception as e:
            print(f"[LOI] {str(e)}")

    asyncio.run(_run())


def cmd_parse_samples(args):
    """CLI: parse-samples"""
    config = load_config(args.config)
    parser = SignalParser()
    validator = SignalValidator(config)

    table = Table(title="KET QUA PHAN TICH 9 MAU TIN HIEU THUC TE")
    table.add_column("Mau", style="bold cyan")
    table.add_column("Symbol", style="white")
    table.add_column("Huong", style="yellow")
    table.add_column("Entry", style="green")
    table.add_column("SL", style="red")
    table.add_column("TP Count", justify="right")
    table.add_column("Trang thai", style="bold")
    table.add_column("Ly do / Canh bao", style="dim")

    for name, raw_text in SAMPLE_SIGNALS.items():
        meta = SourceMetadata(chat_id=999, message_id=1, telegram_timestamp=datetime.utcnow())
        parsed = parser.parse(raw_text, meta)
        parsed, validated = validator.validate_and_resolve(parsed)

        status_style = "green" if parsed.validation_status == SignalState.VALIDATED else "yellow" if parsed.validation_status in [SignalState.NEEDS_POLICY, SignalState.NEEDS_REVIEW] else "red"
        status_text = f"[{status_style}]{parsed.validation_status.value}[/{status_style}]"

        entries_str = ", ".join(str(e) for e in parsed.entries) if parsed.entries else "None"
        reason = parsed.blocking_reason or ("; ".join(parsed.warnings) if parsed.warnings else "OK")

        table.add_row(
            name,
            parsed.symbol_candidate or parsed.symbol_raw,
            parsed.side.value if parsed.side else "None",
            entries_str,
            str(parsed.stop_loss) if parsed.stop_loss else "None",
            str(len(parsed.take_profits)),
            status_text,
            reason[:60] + "..." if len(reason) > 60 else reason,
        )

    console.print(table)


def cmd_doctor(args):
    """CLI: doctor - System preflight check"""
    config = load_config(args.config)
    print("=" * 60)
    print("KIEM TRA TRANG THAI HE THONG (SYSTEM DOCTOR)")
    print("=" * 60)

    # 1. Python environment
    print(f"1. Python Version: {sys.version.split()[0]} [OK]")

    # 2. Config & Mode
    print(f"2. Che do hoat dong: {config.mode.value}")
    print(f"   Live trading enabled: {config.live_trading_enabled}")

    # 3. Database
    try:
        db = DatabaseManager(config.database_file)
        with db.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        print(f"3. Co so du lieu SQLite: {config.database_file} [OK]")
    except Exception as e:
        print(f"3. Co so du lieu SQLite: [LOI] {str(e)}")

    # 4. Telegram credentials
    tg_id = config.telegram.api_id
    tg_hash = config.telegram.api_hash
    session_file = f"{config.telegram.session_name}.session"
    has_session = os.path.exists(session_file)

    if not tg_id or not tg_hash:
        print("4. Telegram MTProto: [BLOCKED] Thieu api_id hoac api_hash trong .env")
    elif not has_session:
        print(f"4. Telegram MTProto: [CHO DANG NHAP] Chua tim thay session '{session_file}'. Chay `python -m cli.main telegram-login`")
    else:
        print(f"4. Telegram MTProto: Session '{session_file}' da san sang [OK]")

    # 5. Binance status
    if config.mode in [ExecutionMode.TESTNET, ExecutionMode.LIVE]:
        key = config.binance.live_api_key if config.mode == ExecutionMode.LIVE else config.binance.testnet_api_key
        sec = config.binance.live_api_secret if config.mode == ExecutionMode.LIVE else config.binance.testnet_api_secret
        if not key or not sec:
            print(f"5. Binance API ({config.mode.value}): [BLOCKED] Thieu API Key hoac Secret trong .env")
        else:
            print(f"5. Binance API ({config.mode.value}): Credentials da duoc cau hinh [OK]")
    else:
        print(f"5. Binance API: Che do {config.mode.value} (Khong can ket noi write vao san) [OK]")

    print("=" * 60)


def cmd_status(args):
    """CLI: status"""
    config = load_config(args.config)
    db = DatabaseManager(config.database_file)

    print("=" * 60)
    print(f"TRANG THAI HE THONG | Che do: {config.mode.value}")
    print("=" * 60)

    with db.get_connection() as conn:
        active_signals = conn.execute(
            "SELECT * FROM signals WHERE state IN ('ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')"
        ).fetchall()
        recent_messages = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]

    print(f"- So tin nhan da ghi nhan: {recent_messages}")
    print(f"- So tin hieu dang hoat dong: {len(active_signals)}")

    if active_signals:
        table = Table(title="TIN HIEU DANG HOAT DONG")
        table.add_column("Signal ID")
        table.add_column("Symbol")
        table.add_column("Huong")
        table.add_column("Trang thai")
        for s in active_signals:
            table.add_row(s["signal_id"], s["symbol"] or "N/A", s["side"] or "N/A", s["state"])
        console.print(table)
    else:
        print("Khong co vi the hoac tin hieu nao dang mo.")
    print("=" * 60)


def cmd_export_history(args):
    """CLI: export-history"""
    config = load_config(args.config)
    db = DatabaseManager(config.database_file)
    repo = SignalRepository(db)

    data = repo.export_history_data()
    out_file = args.output or f"./data/history_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)

    import json
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n[DA XUAT LICH SU] File da luu tai: {out_file}")
    print(f"- Messages: {len(data['messages'])}")
    print(f"- Message Versions: {len(data['message_versions'])}")
    print(f"- Signals: {len(data['signals'])}")
    print(f"- Orders: {len(data['orders'])}")
    print(f"- Timeline Events: {len(data['timeline'])}\n")


def cmd_offline_replay(args):
    """CLI: offline-replay - Replays historical signals/messages without write API calls"""
    config = load_config(args.config)
    db = DatabaseManager(config.database_file)
    parser = SignalParser()
    validator = SignalValidator(config)

    print("=" * 60)
    print("REPLAY OFFLINE LICH SU TIN HIEU (KHONG GOI WRITE API)")
    print("=" * 60)

    with db.get_connection() as conn:
        versions = conn.execute(
            "SELECT * FROM message_versions ORDER BY chat_id, message_id, version ASC"
        ).fetchall()

    if not versions:
        print("Chua co lich su tin nhan nao trong database de replay.")
        print("Ban co the dung lenh `parse-samples` de kiem tra 9 mau san co.")
        return

    for v in versions:
        chat_id = v["chat_id"]
        msg_id = v["message_id"]
        ver = v["version"]
        is_edit = bool(v["is_edit"])
        raw = v["raw_text"]
        date_str = v["event_date"]

        meta = SourceMetadata(chat_id=chat_id, message_id=msg_id, telegram_timestamp=datetime.fromisoformat(date_str))
        parsed = parser.parse(raw, meta)
        parsed, validated = validator.validate_and_resolve(parsed)

        tag = f"[v{ver} {'EDIT' if is_edit else 'NEW'}]"
        sym = parsed.symbol_candidate or parsed.symbol_raw
        side = parsed.side.value if parsed.side else "N/A"
        status = parsed.validation_status.value
        print(f"{date_str} | {tag} Chat {chat_id} Msg {msg_id}: {sym} {side} -> {status}")


def cmd_shadow_mode(args):
    """CLI: shadow-mode - Listens and logs simulated execution without touching exchange"""
    print("\n" + "=" * 60)
    print("KHOI DONG SHADOW MODE (CHE DO BONG QUAN SAT)")
    print("Cam ket an toan: Khong ket noi write den Binance, khong gui lenh san.")
    print("Moi tin hieu va cap nhat chi duoc danh gia va de xuat co dieu kien.")
    print("=" * 60 + "\n")
    cmd_listen(args, is_shadow=True)


def cmd_collect_history(args):
    """CLI: collect-history - Collects up to N messages from last M days from a single channel"""
    import json
    from parser.normalizer import normalize_text
    from parser.update_parser import ChannelUpdateParser
    from core.enums import UpdateType

    config = load_config(args.config)
    chat_id = args.chat_id
    limit = args.limit
    days = args.days
    output = args.output or f"./data/telegram_history_{chat_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    checkpoint_file = args.checkpoint or f"./data/checkpoint_{chat_id}.json"

    print("=" * 60)
    print(f"THU THAP LICH SU TELEGRAM READ-ONLY (GIOI HAN)")
    print(f"- Chat ID: {chat_id}")
    print(f"- Gioi han: {limit} tin gan nhat trong vong {days} ngay")
    print(f"- Checkpoint file: {checkpoint_file}")
    print(f"- Output file: {output}")
    print("=" * 60)

    min_id = 0
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                cp_data = json.load(f)
                min_id = cp_data.get("last_msg_id", 0)
                print(f"[CHECKPOINT] Tim thay checkpoint: tiep tuc tu Msg ID > {min_id}")
        except Exception:
            pass

    def save_checkpoint(last_id: int, count: int):
        os.makedirs(os.path.dirname(os.path.abspath(checkpoint_file)), exist_ok=True)
        try:
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump({
                    "chat_id": chat_id,
                    "last_msg_id": last_id,
                    "count": count,
                    "updated_at": datetime.utcnow().isoformat(),
                }, f, indent=2)
        except Exception:
            pass

    client_wrapper = TelegramUserClient(config)
    parser = SignalParser()
    update_parser = ChannelUpdateParser()
    validator = SignalValidator(config)

    async def _collect():
        messages = await client_wrapper.collect_channel_history(
            chat_id=chat_id,
            limit=limit,
            max_days=days,
            min_id=min_id,
            checkpoint_callback=save_checkpoint,
        )

        print(f"\n[DA THU THAP] Tong so tin nhan tai ve: {len(messages)}")

        collected_signals = []
        collected_updates = []
        unrecognized = []

        for m in messages:
            raw = m["raw_text"]
            if not raw.strip():
                continue

            normalized = normalize_text(raw)
            meta = SourceMetadata(
                chat_id=chat_id,
                message_id=m["message_id"],
                sender_id=m["sender_id"],
                telegram_timestamp=datetime.fromisoformat(m["date"]) if m["date"] else datetime.utcnow(),
                received_at=datetime.utcnow(),
                is_edit=bool(m["edit_date"]),
                edit_timestamp=datetime.fromisoformat(m["edit_date"]) if m["edit_date"] else None,
            )

            # Check update
            up_type, up_val, detail = update_parser.parse_update(normalized)
            if up_type != UpdateType.UNKNOWN:
                collected_updates.append({
                    "message_id": m["message_id"],
                    "date": m["date"],
                    "type": up_type.value,
                    "detail": detail,
                    "reply_to": m["reply_to_msg_id"],
                })
                continue

            # Parse signal
            parsed = parser.parse(raw, meta)
            if parsed.symbol_candidate or parsed.entries:
                parsed, validated = validator.validate_and_resolve(parsed)
                collected_signals.append({
                    "message_id": m["message_id"],
                    "date": m["date"],
                    "symbol": parsed.symbol_candidate or parsed.symbol_raw,
                    "side": parsed.side.value if parsed.side else None,
                    "entries": [str(e) for e in parsed.entries],
                    "stop_loss": str(parsed.stop_loss) if parsed.stop_loss else None,
                    "tp_count": len(parsed.take_profits),
                    "status": parsed.validation_status.value,
                    "blocking_reason": parsed.blocking_reason,
                })
            else:
                unrecognized.append({
                    "message_id": m["message_id"],
                    "date": m["date"],
                    "text_preview": raw[:80].replace("\n", " "),
                })

        export_payload = {
            "metadata": {
                "chat_id": chat_id,
                "collected_at": datetime.utcnow().isoformat(),
                "total_messages": len(messages),
                "signals_count": len(collected_signals),
                "updates_count": len(collected_updates),
                "unrecognized_count": len(unrecognized),
                "note": "Trang thai tin nhan tai thoi diem thu thap lich su (Telegram MTProto khong cung cap toan bo lich su sua tin cuoi cung)",
            },
            "signals": collected_signals,
            "updates": collected_updates,
            "unrecognized": unrecognized,
            "raw_messages": messages,
        }

        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(export_payload, f, indent=2, ensure_ascii=False)

        print(f"[XUAT THANH CONG] File lich su da luu tai: {output}")
        print(f"- Tin hieu nhan dien duoc: {len(collected_signals)}")
        print(f"- Cap nhat admin: {len(collected_updates)}")
        print(f"- Tin khong thuoc danh muc tin hieu: {len(unrecognized)}")
        print("=" * 60)

    asyncio.run(_collect())


def cmd_export_report(args):
    """CLI: export-report - Generates sanitized report of timelines, updates, and anomalies"""
    import json
    config = load_config(args.config)
    db = DatabaseManager(config.database_file)
    out_file = args.output or f"./data/audit_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"

    with db.get_connection() as conn:
        signals = [dict(r) for r in conn.execute("SELECT * FROM signals ORDER BY created_at DESC").fetchall()]
        timeline = [dict(r) for r in conn.execute("SELECT * FROM signal_timeline ORDER BY id ASC").fetchall()]
        versions = [dict(r) for r in conn.execute("SELECT * FROM message_versions ORDER BY received_at DESC").fetchall()]

    lines = [
        "# BAO CAO AUDIT DU LIEU TIN HIEU VA CAP NHAT TELEGRAM",
        f"- Thoi diem tao: {datetime.utcnow().isoformat()} UTC",
        f"- Che do he thong: {config.mode.value} (live_trading_enabled={config.live_trading_enabled})",
        "",
        "## 1. TIMELINE CAC TIN HIEU (SIGNALS)",
    ]

    if not signals:
        lines.append("*Chua co tin hieu nao duoc ghi nhan trong SQLite.*")
    else:
        for s in signals:
            sig_id = s["signal_id"]
            sym = s["symbol"] or "UNKNOWN"
            side = s["side"] or "UNKNOWN"
            state = s["state"]
            lines.append(f"### Kèo: `{sym}` ({side}) | ID: `{sig_id}` | Trang thai: **{state}**")
            lines.append(f"- Ly do chan / Canh bao: {s['blocking_reason'] or 'Khong co'}")
            lines.append(f"- SL: `{s['stop_loss']}` | Entries: `{s['entries_json']}`")
            lines.append("- **Cac moc su kien (Timeline):**")

            events = [e for e in timeline if e["signal_id"] == sig_id]
            if events:
                for ev in events:
                    lines.append(f"  - `{ev['timestamp']}` | **{ev['event_type']}**: {ev['description']}")
            else:
                lines.append("  - *Chua co su kien timeline bo sung.*")
            lines.append("")

    lines.extend([
        "## 2. BANG TONG HOP CAC CAP NHAT ADMIN VA TIN SU'A",
        f"- Tong so phien ban tin nhan quan sat duoc: {len(versions)}",
        "",
        "## 3. QUY TAC NGUON DE XUAT (DE XUAT CHUA KICH HOAT)",
        "- Don bay truyen thong qua kenh thuong cao (20x-200x) -> Bat buoc duy tri gioi han an toan tai `config.yaml` (mac dinh 3x-5x).",
        "- Vung Entry dang Range can lua chon chinh sach (`MID_POINT`, `BEST_PRICE`, `SPLIT_2_LIMITS`).",
        "- Chot loi nhieu nac khong ghi ty le -> De xuat ty le mac dinh `FRONT_LOADED_50_30_20` hoac `EQUAL_SPLIT`.",
        "",
        "## 4. CAC TRUONG HOP CAN NGUOI DUNG XAC NHAN",
        "- Cac tin cap nhat khong kem reply_to den tin goc.",
        "- Cac tin sua Stop Loss co xu huong noi rong khoang cach.",
    ])

    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[DA TAO BAO CAO] Bao cao audit da luu tai: {out_file}\n")


def cmd_testnet_check(args):
    """CLI: testnet-check - Preflight check against Binance USD-M Futures"""
    config = load_config(args.config)
    key = config.binance.testnet_api_key
    sec = config.binance.testnet_api_secret

    print("=" * 60)
    print("KIEM TRA KET NOI BINANCE TESTNET (USD-M FUTURES)")
    print("=" * 60)

    if not key or not sec:
        print("[BLOCKED] Thieu BINANCE_TESTNET_API_KEY hoac BINANCE_TESTNET_API_SECRET trong .env.")
        print("Vui long lay key tai https://testnet.binancefuture.com va them vao file .env.")
        print("=" * 60)
        return

    from exchange.binance_client import BinanceFuturesClient

    async def _check():
        client = BinanceFuturesClient(config)
        try:
            print("1. Dang kiem tra endpoint mang va server time...")
            data = await client._request("GET", "/fapi/v1/time")
            print(f"   Server time: {data.get('serverTime')} [OK]")

            print("2. Dang kiem tra Position Mode (Bat buoc One-Way)...")
            await client.check_position_mode_one_way()
            print("   Position Mode: One-Way [OK]")

            print("3. Dang kiem tra so du ky quy USDT...")
            equity = await client.get_account_equity()
            print(f"   USDT Margin Balance: {equity} USDT [OK]")
            print("\n[TESTNET PASS] Ket noi va xac thuc Testnet hoan toan thanh cong!")
        except Exception as e:
            print(f"\n[LOI TESTNET] {str(e)}")
        finally:
            await client.close()

    asyncio.run(_check())
    print("=" * 60)


def cmd_listen(args, is_shadow: bool = False):
    """CLI: listen"""
    config = load_config(args.config)
    if is_shadow:
        config.mode = ExecutionMode.READ_ONLY
        config.live_trading_enabled = False

    if not config.telegram.api_id or not config.telegram.api_hash:
        print("\n[BLOCKED] Thieu TELEGRAM_API_ID hoac TELEGRAM_API_HASH trong file .env")
        print("Vui long lay tai https://my.telegram.org va dien vao file .env truoc khi chay listener.\n")
        return

    session_file = f"{config.telegram.session_name}.session"
    if not os.path.exists(session_file):
        print(f"\n[BLOCKED] Chua dang nhap Telegram tai session '{session_file}'.")
        print("Vui long chay lenh sau de dang nhap truoc:")
        print("  python -m cli.main telegram-login\n")
        return

    from telegram.listener import TelegramSignalListener
    client_wrapper = TelegramUserClient(config)
    client = client_wrapper.get_client()
    db = DatabaseManager(config.database_file)

    listener = TelegramSignalListener(config, client, db, is_shadow=is_shadow)

    async def _start():
        await client.connect()
        if not await client.is_user_authorized():
            print("\n[BLOCKED] Session Telegram da het han hoac chua duoc uy quyen. Vui long chay `telegram-login` lai.\n")
            return
        await listener.start()

    asyncio.run(_start())


def cmd_gui(args):
    """CLI: gui - Launches PySide6 Desktop GUI"""
    from app_gui import main as gui_main
    gui_main()


def main():
    parser = argparse.ArgumentParser(description="Telegram Binance Signal Executor CLI")
    parser.add_argument("--config", "-c", default=None, help="Path to config.yaml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommands
    subparsers.add_parser("gui", help="Khoi dong giao dien Desktop App PySide6")
    subparsers.add_parser("telegram-login", help="Dang nhap interactive vao tai khoan Telegram MTProto")
    subparsers.add_parser("list-chats", help="Liet ke cac nhom va kenh de lay Chat ID cho allowlist")
    subparsers.add_parser("parse-samples", help="Phan tich 9 mau tin hieu thuc te va bao cao")
    subparsers.add_parser("doctor", help="Kiem tra chan doan toan bo he thong (preflight)")
    subparsers.add_parser("status", help="Hien thi trang thai he thong va tin hieu dang mo")
    subparsers.add_parser("listen", help="Lang nghe tin hieu tu cac kenh da allowlist")

    # History & audit commands
    p_export = subparsers.add_parser("export-history", help="Xuat toan bo du lieu SQLite (messages, versions, signals, orders, timeline) ra file JSON")
    p_export.add_argument("--output", "-o", default=None, help="Duong dan file JSON output")

    p_collect = subparsers.add_parser("collect-history", help="Thu thap lich su doc tin nhan tu 1 kenh Telegram (gioi han 7 ngay, max 1000 tin)")
    p_collect.add_argument("--chat-id", type=int, required=True, help="Chat ID cua kenh can thu thap lich su")
    p_collect.add_argument("--days", type=int, default=7, help="So ngay toi da quay ve qua khu (mac dinh 7 ngay)")
    p_collect.add_argument("--limit", type=int, default=1000, help="So tin nhan toi da thu thap (mac dinh 1000)")
    p_collect.add_argument("--checkpoint", default=None, help="Duong dan file checkpoint de resume")
    p_collect.add_argument("--output", "-o", default=None, help="Duong dan file JSON output")

    p_report = subparsers.add_parser("export-report", help="Xuat bao cao audit timeline va cac bat thuong ra Markdown")
    p_report.add_argument("--output", "-o", default=None, help="Duong dan file Markdown output")

    subparsers.add_parser("offline-replay", help="Replay offline cac tin nhan lich su ma khong goi bat ky write API nao")
    subparsers.add_parser("shadow-mode", help="Chay listener che do bong (shadow), chi danh gia khong dat lenh san")
    subparsers.add_parser("testnet-check", help="Kiem tra ket noi mang that den Binance Futures Testnet")

    args = parser.parse_args()

    cmd_map = {
        "gui": cmd_gui,
        "telegram-login": cmd_telegram_login,
        "list-chats": cmd_list_chats,
        "parse-samples": cmd_parse_samples,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "listen": cmd_listen,
        "export-history": cmd_export_history,
        "collect-history": cmd_collect_history,
        "export-report": cmd_export_report,
        "offline-replay": cmd_offline_replay,
        "shadow-mode": cmd_shadow_mode,
        "testnet-check": cmd_testnet_check,
    }

    func = cmd_map.get(args.command)
    if func:
        func(args)



if __name__ == "__main__":
    main()


