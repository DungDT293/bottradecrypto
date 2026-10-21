"""Read-only live runtime diagnostic. Never places, cancels, or changes orders."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

RUNTIME_DB = Path(os.environ.get(
    "APPDATA", str(Path.home() / "AppData" / "Roaming")
)) / "telegram_binance_signal_executor" / "data" / "trading_state.db"


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def db_rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def source_candidates(signals: list[dict[str, Any]], symbol: str, position_amt: Decimal) -> list[dict[str, Any]]:
    side = "LONG" if position_amt > 0 else "SHORT"
    rows = [
        s for s in signals
        if s.get("symbol") == symbol and s.get("side") == side
        and s.get("state") in {"ENTRY_PENDING", "PARTIALLY_FILLED", "OPEN_PROTECTED", "EXITING"}
    ]
    rows.sort(key=lambda s: s.get("updated_at") or s.get("created_at") or "", reverse=True)
    return rows


def algo_qty(order: dict[str, Any]) -> Decimal:
    return dec(order.get("quantity") or order.get("origQty") or order.get("actualQty") or "0")


async def diagnose() -> Path:
    started = datetime.now(timezone.utc)
    out = PROJECT_ROOT / "audit_output" / f"system_understanding_{started.strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "generated_at_utc": started.isoformat(),
        "safety": {
            "read_only": True,
            "writes_attempted": False,
            "binance_write_endpoints_called": [],
            "telegram_write_endpoints_called": [],
            "secrets_included": False,
        },
        "runtime_db": str(RUNTIME_DB),
        "errors": [],
    }

    if not RUNTIME_DB.exists():
        result["errors"].append(f"Runtime DB not found: {RUNTIME_DB}")
        (out / "LIVE_STATE_READONLY.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return out

    conn = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["runtime_db_integrity"] = integrity
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result["runtime_db_tables"] = tables
        result["db_counts"] = {
            table: conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            for table in tables
        }
        signals = db_rows(conn, "SELECT * FROM signals")
        active_signals = [s for s in signals if s.get("state") in {"ENTRY_PENDING", "PARTIALLY_FILLED", "OPEN_PROTECTED", "EXITING"}]
        db_orders = db_rows(conn, "SELECT * FROM orders")
        result["active_signals"] = [
            {k: v for k, v in s.items() if k in {
                "signal_id", "chat_id", "message_id", "symbol", "side", "state", "entries_json",
                "stop_loss", "take_profits_json", "leverage", "margin_mode", "created_at", "updated_at"
            }} for s in active_signals
        ]
    finally:
        conn.close()

    config = load_config()
    result["effective_config"] = {
        "mode": config.mode.value,
        "live_trading_enabled": config.live_trading_enabled,
        "margin_mode": str(config.risk.margin_mode),
        "risk_per_signal_pct": str(config.risk.risk_per_signal_pct),
        "max_total_open_risk_pct": str(config.risk.max_total_open_risk_pct),
        "max_active_signals": config.risk.max_active_signals,
        "default_leverage": config.risk.default_leverage,
        "max_leverage": config.risk.max_leverage,
        "tp1_target_weight_pct": str(config.execution.tp1_target_weight_pct),
        "breakeven_after_tp1": config.risk.breakeven_after_tp1_default,
        "reconciliation_interval_seconds": 20,
        "telegram_sync_interval_seconds": 60,
    }

    client = BinanceFuturesClient(config)
    try:
        result["exchange"] = {
            "base_url": client.base_url,
            "mode": config.mode.value,
            "positions": [],
            "open_standard_orders": [],
            "open_algo_orders": [],
        }
        positions = await client.get_open_positions()
        open_standard = await client.get_open_orders()
        open_algo = await client.get_open_algo_orders()
        result["exchange"]["positions"] = positions
        result["exchange"]["open_standard_orders"] = open_standard or []
        result["exchange"]["open_algo_orders"] = open_algo or []

        live_map = []
        for position in positions or []:
            symbol = str(position.get("symbol"))
            amount = dec(position.get("positionAmt"))
            if amount == 0:
                continue
            candidates = source_candidates(active_signals, symbol, amount)
            symbol_algos = [
                a for a in (open_algo or [])
                if a.get("symbol") == symbol and (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
            ]
            symbol_standard = [
                o for o in (open_standard or [])
                if o.get("symbol") == symbol and o.get("reduceOnly") in [True, "true", "True"]
            ]
            sl_qty = sum(algo_qty(a) for a in symbol_algos)
            tp_qty = sum(dec(o.get("origQty") or o.get("quantity") or "0") for o in symbol_standard)
            sls = [a for a in symbol_algos if str(a.get("side")) == ("SELL" if amount > 0 else "BUY")]
            live_map.append({
                "symbol": symbol,
                "side": "LONG" if amount > 0 else "SHORT",
                "position_qty": str(abs(amount)),
                "entry_price": str(position.get("entryPrice")),
                "mark_price": str(position.get("markPrice")),
                "leverage": position.get("leverage"),
                "margin_type": position.get("marginType"),
                "source_candidates": candidates,
                "active_algo_count": len(symbol_algos),
                "active_sl_count": len(sls),
                "active_sl_qty": str(sl_qty),
                "sl_qty_coverage": str((sl_qty / abs(amount) * 100) if amount else Decimal("0")),
                "active_tp_count": len(symbol_standard),
                "active_tp_qty": str(tp_qty),
                "tp_qty_coverage": str((tp_qty / abs(amount) * 100) if amount else Decimal("0")),
                "protection_status": (
                    "FULL" if sl_qty >= abs(amount) and tp_qty >= abs(amount)
                    else "SL_ONLY" if sl_qty >= abs(amount)
                    else "MISSING_OR_UNDERSIZED_SL"
                ),
                "active_sl_orders": symbol_algos,
                "active_tp_orders": symbol_standard,
            })
        result["signal_to_position_map"] = live_map
    except Exception as exc:
        result["errors"].append(f"Read-only exchange diagnostic failed: {type(exc).__name__}: {exc}")
    finally:
        await client.close()

    out_file = out / "LIVE_STATE_READONLY.json"
    out_file.write_text(json.dumps(json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = out / "FILE_MANIFEST.md"
    manifest.write_text(
        "# Read-only system understanding run\n\n"
        f"Generated: {result['generated_at_utc']}\n\n"
        "No order/cancel/replace/Telegram-write endpoint called.\n\n"
        "Files:\n- LIVE_STATE_READONLY.json\n",
        encoding="utf-8",
    )
    return out


if __name__ == "__main__":
    print(asyncio.run(diagnose()))
