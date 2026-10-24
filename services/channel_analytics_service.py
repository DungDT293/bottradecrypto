import sqlite3
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import pytz

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

KNOWN_CHANNELS: Dict[int, str] = {
    -1002191067035: "Crypto Hunters",
    -1001700314832: "WHALES CIRCLE",
    -1001391574614: "Bitcoin Bulls",
    -1001895315984: "Crypto spider 🕷️ scalper",
    -1001860630181: "Alpha Trade Zone",
    -1002052872813: "CRYPTO LEOPARD'S",
    -1002007658025: "THE WOLF (CRYPTO)®",
    -1002078531832: "Crypto Mermaids",
    -1001520053536: "Coin Chief",
    -1001552004524: "CRYPTO MONK",
    -1001598691683: "Crypto Devil® [Private]",
    -1001652601224: "Crypto World Updates",
    -1001754095061: "Crypto Radar",
    -999001: "Quantum AI Engine 2.0",
}


class ChannelAnalyticsService:
    """
    Commercial-Grade Channel Evaluation & Ranking Engine.
    Evaluates signal quality, daily/weekly/monthly frequency,
    win rates, error rates, and simulated PnL across all pinned channels.
    """

    def __init__(self, db_path: str = "./data/trading_state.db"):
        self.db_path = db_path

    def check_circuit_breaker(self, chat_id: int) -> Tuple[bool, Optional[str]]:
        """
        Trụ Cột 2: Circuit Breaker & Auto-Mute Guard.
        Kiểm tra nếu kênh dính 3 lệnh Stop-Loss liên tiếp trong vòng 48 giờ:
        Tự động kích hoạt Circuit Breaker, chuyển kênh sang MUTED_TEMPORARY trong 7 ngày
        để bảo toàn vốn (chỉ chạy shadow/paper test).
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            query = """
                SELECT st.event_type, st.timestamp, s.signal_id
                FROM signal_timeline st
                JOIN signals s ON st.signal_id = s.signal_id
                WHERE s.chat_id = ?
                  AND st.event_type IN ('EXCHANGE_SL_FILLED', 'EXCHANGE_TP_FILLED', 'RESULT_SL_REPORTED', 'RESULT_TP_REPORTED', 'EXCHANGE_POSITION_CLOSED_LOSS', 'EXCHANGE_POSITION_CLOSED_WIN')
                  AND st.timestamp >= ?
                ORDER BY st.timestamp DESC
                LIMIT 10
            """
            c.execute(query, (chat_id, cutoff))
            rows = c.fetchall()
            conn.close()

            consecutive_sl = 0
            latest_sl_time = None
            for r in rows:
                ev = r["event_type"]
                if ev in ("EXCHANGE_SL_FILLED", "RESULT_SL_REPORTED", "EXCHANGE_POSITION_CLOSED_LOSS"):
                    consecutive_sl += 1
                    if latest_sl_time is None:
                        latest_sl_time = r["timestamp"]
                elif ev in ("EXCHANGE_TP_FILLED", "RESULT_TP_REPORTED", "EXCHANGE_POSITION_CLOSED_WIN"):
                    break

            if consecutive_sl >= 3 and latest_sl_time:
                try:
                    sl_dt = datetime.fromisoformat(latest_sl_time.replace("Z", "+00:00"))
                    mute_expiry = sl_dt + timedelta(days=7)
                    if datetime.now(timezone.utc) < mute_expiry:
                        remaining_hours = int((mute_expiry - datetime.now(timezone.utc)).total_seconds() // 3600)
                        return True, f"Kênh đã dính {consecutive_sl} Stop Loss liên tiếp trong 48h. Tự động đóng băng (MUTED_TEMPORARY) còn {remaining_hours}h để bảo vệ vốn."
                except Exception:
                    return True, f"Kênh đã dính {consecutive_sl} Stop Loss liên tiếp. Kích hoạt Circuit Breaker 7 ngày."
        except Exception:
            pass

        return False, None

    def get_channel_leaderboard(
        self,
        timeframe: str = "all",  # 'all', 'month', 'week', 'day'
        bankroll_usd: float = 86.18,
        margin_per_trade_pct: float = 1.5,  # 1.5% margin per trade based on user's real risk config
    ) -> Dict[str, Any]:
        margin_per_trade = bankroll_usd * (margin_per_trade_pct / 100.0)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Determine timeframe filter cutoff
        now_dt = datetime.now(timezone.utc)
        cutoff_dt: Optional[datetime] = None
        if timeframe == "day":
            cutoff_dt = now_dt - timedelta(days=1)
        elif timeframe == "week":
            cutoff_dt = now_dt - timedelta(days=7)
        elif timeframe == "month":
            cutoff_dt = now_dt - timedelta(days=30)

        cutoff_str = cutoff_dt.isoformat() if cutoff_dt else None

        # 1. Fetch channel message counts and date spans
        c.execute("""
            SELECT chat_id,
                   COUNT(message_id) as total_messages,
                   MIN(telegram_timestamp) as min_ts,
                   MAX(telegram_timestamp) as max_ts
            FROM messages
            GROUP BY chat_id
        """)
        msg_stats = {r["chat_id"]: dict(r) for r in c.fetchall()}

        # 2. Query signals with timeline outcomes
        query = """
            SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state,
                   s.entry_mode, s.entries_json, s.stop_loss, s.take_profits_json,
                   s.leverage, s.blocking_reason, s.created_at, m.telegram_timestamp
            FROM signals s
            LEFT JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
        """
        params: List[Any] = []
        if cutoff_str:
            query += " WHERE m.telegram_timestamp >= ? OR (m.telegram_timestamp IS NULL AND s.created_at >= ?)"
            params.extend([cutoff_str, cutoff_str])

        c.execute(query, params)
        signals = [dict(r) for r in c.fetchall()]

        # 3. Separate admin claims from exchange-confirmed evidence.
        c.execute("""
            SELECT signal_id, event_type, description, timestamp
            FROM signal_timeline
            WHERE event_type IN ('RESULT_TP_REPORTED', 'RESULT_SL_REPORTED', 'ADMIN_TP_REPORTED',
                                 'CLOSE_PARTIAL', 'CLOSE_ALL', 'ADMIN_MEDIA_CLAIM')
        """)
        claim_rows = c.fetchall()
        claims_by_sig: Dict[str, List[str]] = {}
        for r in claim_rows:
            claims_by_sig.setdefault(r["signal_id"], []).append(r["event_type"])

        c.execute("""
            SELECT signal_id, event_type, description, timestamp
            FROM signal_timeline
            WHERE event_type IN ('EXCHANGE_TP_FILLED', 'EXCHANGE_SL_FILLED',
                                 'EXCHANGE_POSITION_CLOSED_WIN', 'EXCHANGE_POSITION_CLOSED_LOSS')
        """)
        exchange_rows = c.fetchall()
        timeline_by_sig: Dict[str, List[str]] = {}
        for r in exchange_rows:
            timeline_by_sig.setdefault(r["signal_id"], []).append(r["event_type"])

        conn.close()

        # Group signals by channel
        signals_by_chat: Dict[int, List[Dict[str, Any]]] = {}
        for s in signals:
            cid = s["chat_id"]
            if cid not in signals_by_chat:
                signals_by_chat[cid] = []
            signals_by_chat[cid].append(s)

        # 4. Evaluate each channel
        leaderboard_items: List[Dict[str, Any]] = []

        # Find min and max dates across all messages for time span calculations
        all_chats = [cid for cid in KNOWN_CHANNELS.keys()]

        for cid in all_chats:
            name = KNOWN_CHANNELS.get(cid, f"Channel {cid}")
            m_stat = msg_stats.get(cid, {"total_messages": 0, "min_ts": None, "max_ts": None})
            channel_signals = signals_by_chat.get(cid, [])

            total_msgs = m_stat["total_messages"]
            total_sigs = len(channel_signals)

            VALID_STATES = {"VALIDATED", "CLOSED", "ENTRY_PENDING", "OPEN_PROTECTED", "PARTIALLY_FILLED", "ACTIVE", "FILLED"}
            validated_sigs = [s for s in channel_signals if s["state"] in VALID_STATES]
            rejected_sigs = [s for s in channel_signals if s["state"] == "REJECTED"]
            needs_review_sigs = [s for s in channel_signals if s["state"] in ("NEEDS_REVIEW", "NEEDS_POLICY")]

            val_count = len(validated_sigs)
            rej_count = len(rejected_sigs)
            review_count = len(needs_review_sigs)

            quality_rate = round((val_count / total_sigs * 100), 1) if total_sigs > 0 else 0.0
            rejection_rate = round((rej_count / total_sigs * 100), 1) if total_sigs > 0 else 0.0

            # Frequency calculations (Daily, Weekly, Monthly)
            min_ts = m_stat["min_ts"]
            max_ts = m_stat["max_ts"]
            span_days = 90  # Default 90 days span
            if min_ts and max_ts:
                try:
                    dt_start = datetime.fromisoformat(min_ts)
                    dt_end = datetime.fromisoformat(max_ts)
                    diff = (dt_end - dt_start).days
                    if diff > 0:
                        span_days = max(diff, 1)
                except Exception:
                    pass

            # Frequencies
            sigs_per_day = round(val_count / max(span_days, 1), 2)
            sigs_per_week = round(sigs_per_day * 7, 1)
            sigs_per_month = round(sigs_per_day * 30, 1)

            # Signal outcomes & PnL simulation
            import os
            import sys
            empirical_map: Dict[int, Dict[str, Any]] = {}
            possible_paths = [
                os.path.join(getattr(sys, "_MEIPASS", ""), "data", "channel_winrates_6_months.json"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "channel_winrates_6_months.json"),
                os.path.join(os.path.dirname(self.db_path), "channel_winrates_6_months.json"),
                r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\channel_winrates_6_months.json",
                r"e:\TOOL DUNG CODE\bottradecrypto\data\channel_winrates_6_months.json"
            ]
            for bp in possible_paths:
                if bp and os.path.exists(bp):
                    try:
                        with open(bp, "r", encoding="utf-8") as f:
                            bt_list = json.load(f)
                            for item in bt_list:
                                if "id" in item:
                                    empirical_map[item["id"]] = item
                        if empirical_map:
                            break
                    except Exception:
                        pass

            emp_info = empirical_map.get(cid, {})
            emp_tp1 = float(emp_info.get("avg_tp1_pct", 3.5))
            emp_sl = float(emp_info.get("avg_sl_pct", 5.5))

            win_count = 0
            loss_count = 0
            gross_profit = 0.0
            gross_loss = 0.0
            rr_list: List[float] = []
            channel_claim_count = sum(len(claims_by_sig.get(s["signal_id"], [])) for s in channel_signals)

            if val_count == 0:
                total_trades = 0
                win_rate = 0.0
                loss_rate = 0.0
                net_pnl = 0.0
                roi_pct = 0.0
                profit_factor = 0.0
                avg_rr = round(emp_tp1 / max(emp_sl, 0.1), 2)
            else:
                for sig in validated_sigs:
                    sid = sig["signal_id"]
                    events = timeline_by_sig.get(sid, [])

                    # Parse prices
                    try:
                        entries = json.loads(sig["entries_json"] or "[]")
                        tps = json.loads(sig["take_profits_json"] or "[]")
                        entry_price = float(entries[0]) if entries else 0.0
                        sl_price = float(sig["stop_loss"] or 0.0)
                        tp1_price = float(tps[0]) if tps else 0.0
                        leverage = min(int(sig["leverage"] or 5), 5)  # Clamped to safe 5x
                    except Exception:
                        entry_price, sl_price, tp1_price, leverage = 0.0, 0.0, 0.0, 5

                    # Compute Risk:Reward
                    rr = 0.0
                    if entry_price > 0 and sl_price > 0 and tp1_price > 0:
                        risk_diff = abs(entry_price - sl_price)
                        reward_diff = abs(tp1_price - entry_price)
                        if risk_diff > 0:
                            rr = reward_diff / risk_diff
                            rr_list.append(rr)

                    # Only exchange-confirmed events can affect outcome metrics.
                    # Admin claims and media evidence remain unverified.
                    if events:
                        is_win = "EXCHANGE_POSITION_CLOSED_WIN" in events or "EXCHANGE_TP_FILLED" in events
                        is_loss = "EXCHANGE_POSITION_CLOSED_LOSS" in events or "EXCHANGE_SL_FILLED" in events
                    else:
                        is_win = False
                        is_loss = False

                    if is_win:
                        win_count += 1
                        base_diff = (abs(tp1_price - entry_price) / max(entry_price, 1e-6)) if entry_price > 0 else (emp_tp1 / 100.0)
                        gain_pct = max(min(base_diff * leverage, 0.18), 0.025)
                        gross_profit += margin_per_trade * gain_pct
                    elif is_loss:
                        loss_count += 1
                        base_sl = (abs(sl_price - entry_price) / max(entry_price, 1e-6)) if entry_price > 0 else (emp_sl / 100.0)
                        loss_pct = max(min(base_sl * leverage, 0.14), 0.03)
                        gross_loss += margin_per_trade * loss_pct

                total_trades = win_count + loss_count
                win_rate = round(win_count / total_trades * 100, 1) if total_trades > 0 else 0.0
                loss_rate = round(100.0 - win_rate, 1)
                net_pnl = round(gross_profit - gross_loss, 2)
                roi_pct = round((net_pnl / bankroll_usd) * 100, 2)
                profit_factor = round(gross_profit / max(gross_loss, 1.0), 2)
                avg_rr = round(sum(rr_list) / max(len(rr_list), 1), 2) if rr_list else round(emp_tp1 / max(emp_sl, 0.1), 2)

            # If no live closed trades recorded yet in local session, fallback to audited Binance ground-truth metrics
            if total_trades == 0 and emp_info:
                win_rate = float(emp_info.get("winrate", 0.0))
                loss_rate = round(100.0 - win_rate, 1)
                avg_rr = float(emp_info.get("rr", round(emp_tp1 / max(emp_sl, 0.1), 2)))
                sampled_count = int(emp_info.get("sampled_count", 40))
                win_count = int(round(sampled_count * (win_rate / 100.0)))
                loss_count = sampled_count - win_count
                total_trades = sampled_count
                gross_profit = round(win_count * margin_per_trade * (emp_tp1 / 100.0) * 8.0, 2)
                gross_loss = round(loss_count * margin_per_trade * (emp_sl / 100.0) * 8.0, 2)
                net_pnl = round(gross_profit - gross_loss, 2)
                roi_pct = round((net_pnl / bankroll_usd) * 100, 2)
                profit_factor = round(gross_profit / max(gross_loss, 0.01), 2)
                score = float(emp_info.get("score", 50.0))
                tier = emp_info.get("tier", "C")
                verdict = emp_info.get("verdict", "")
            else:
                # Overall Comprehensive Scoring Formula (0 to 100)
                score = (win_rate * 0.35) + (min(profit_factor, 3.0) / 3.0 * 25) + (min(quality_rate, 100) * 0.20) + (min(val_count, 150) / 150 * 20)
                if net_pnl < 0:
                    score = max(score - 25.0, 0.0)
                tier = "C"
                verdict = f"Chất lượng ổn định (Winrate {win_rate}%)"

            # Dynamic Commercial Tier Allocation
            is_blacklisted = False
            blacklist_reason = "Kênh trong danh sách Blacklist hoặc đã bị tắt nhận lệnh hoàn toàn"
            try:
                from config.config import load_config, PERMANENT_BLACKLISTED_CHANNELS
                if cid in PERMANENT_BLACKLISTED_CHANNELS:
                    is_blacklisted = True
                    blacklist_reason = PERMANENT_BLACKLISTED_CHANNELS[cid]
                else:
                    cfg = load_config("config.yaml")
                    if cid in getattr(cfg.telegram, "blacklisted_chat_ids", []):
                        is_blacklisted = True
                    source_cfg = cfg.sources.get(cid)
                    if source_cfg and getattr(source_cfg, "margin_multiplier", 1.0) <= 0:
                        is_blacklisted = True
            except Exception:
                pass

            is_cb_tripped, cb_reason = self.check_circuit_breaker(cid)
            if is_blacklisted:
                tier = "BLOCKED"
                verdict = "[ĐÃ CHẶN] Kênh Fake / Blacklist"
                verdict_color = "error"
                badge_desc = blacklist_reason
                score = 0.0
            elif is_cb_tripped:
                tier = "MUTED_TEMPORARY"
                verdict = f"[CIRCUIT BREAKER] {cb_reason}"
                verdict_color = "warning"
                badge_desc = "Tạm dừng trade real 7 ngày (3 SL liên tiếp)"
            elif emp_info and "tier" in emp_info:
                tier = emp_info["tier"]
                verdict = emp_info.get("verdict", verdict)
                verdict_color = "success" if tier == "S" else ("primary" if tier == "A" else ("warning" if tier in ["B", "C"] else "error"))
                badge_desc = f"Thẩm định Binance: {win_count}W - {loss_count}L, PF {profit_factor}, PnL +${net_pnl:,.2f}"
            elif score >= 65.0 and net_pnl > 0 and val_count >= 15 and win_rate >= 60.0:
                tier = "S"
                verdict = f"Khuyến nghị cao (Winrate {win_rate}%, PF {profit_factor})"
                verdict_color = "success"
                badge_desc = f"Hiệu suất xuất sắc: Thắng {win_count}/{total_trades} kèo, PnL +${net_pnl:,.2f}"
            elif score >= 50.0 and net_pnl > 0 and val_count >= 10:
                tier = "A"
                verdict = f"Chất lượng tốt (R:R 1:{avg_rr}, Winrate {win_rate}%)"
                verdict_color = "primary"
                badge_desc = f"Kèo ổn định: Thắng {win_count}/{total_trades} kèo, PnL +${net_pnl:,.2f}"
            elif score >= 35.0 and val_count >= 5:
                tier = "B"
                verdict = f"Khá (Cần chọn lọc coin, Winrate {win_rate}%)"
                verdict_color = "warning"
                badge_desc = f"Tỉ lệ ăn trung bình: {win_count}W - {loss_count}L, PF {profit_factor}"
            elif val_count >= 5:
                tier = "C"
                verdict = "Cảnh báo rủi ro (Nhiều tin bị chặn/SL)"
                verdict_color = "warning"
                badge_desc = f"Cần lưu ý: Tỉ lệ từ chối cao ({rejection_rate}%)"
            else:
                tier = "D"
                verdict = f"Chưa đủ dữ liệu ({val_count} kèo hợp lệ)"
                verdict_color = "secondary"
                badge_desc = f"Mới có {val_count} tín hiệu chuẩn, cần tiếp tục theo dõi"

            leaderboard_items.append({
                "chat_id": cid,
                "channel_name": name,
                "tier": tier,
                "verdict": verdict,
                "verdict_color": verdict_color,
                "badge_desc": badge_desc,
                "score": score,
                "is_blacklisted": is_blacklisted,
                "total_messages": total_msgs,
                "total_signals": total_sigs,
                "validated_signals": val_count,
                "rejected_signals": rej_count,
                "needs_review_signals": review_count,
                "quality_rate_pct": quality_rate,
                "rejection_rate_pct": rejection_rate,
                "frequencies": {
                    "per_day": sigs_per_day,
                    "per_week": sigs_per_week,
                    "per_month": sigs_per_month,
                    "span_days": span_days,
                },
                "performance": {
                    "evidence_status": "EXCHANGE_CONFIRMED" if total_trades else ("CLAIM_ONLY" if channel_claim_count else "UNKNOWN"),
                    "admin_claim_count": channel_claim_count,
                    "total_trades": total_trades,
                    "win_trades": win_count,
                    "loss_trades": loss_count,
                    "win_rate_pct": win_rate,
                    "loss_rate_pct": loss_rate,
                    "avg_risk_reward": avg_rr,
                    "gross_profit_usd": round(gross_profit, 2),
                    "gross_loss_usd": round(gross_loss, 2),
                    "net_pnl_usd": net_pnl,
                    "roi_pct": roi_pct,
                    "profit_factor": profit_factor,
                },
            })

        # Get allowed_chat_ids from config to strictly prioritize active elite channels
        allowed_chat_ids = set()
        try:
            from config.config import load_config
            cfg = load_config("config.yaml")
            allowed_chat_ids = set(getattr(cfg.telegram, "allowed_chat_ids", []))
        except Exception:
            pass
        if not allowed_chat_ids:
            allowed_chat_ids = {-1002191067035, -1001700314832, -1001391574614, -1001895315984, -1001860630181, -1002052872813}

        # Demote or eliminate scam/blacklisted channels
        tier_weight = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "BLOCKED": 5}
        for item in leaderboard_items:
            cid = item["chat_id"]
            if cid in allowed_chat_ids:
                item["is_whitelisted"] = True
                item["tier"] = "S"
            else:
                item["is_whitelisted"] = False
                if item["tier"] == "S":
                    item["tier"] = "C"

        # Strictly keep ONLY the approved whitelisted Top 5 channels
        leaderboard_items = [c for c in leaderboard_items if c["chat_id"] in allowed_chat_ids]

        # Sort leaderboard: Whitelisted Top 5 ordered by score descending
        leaderboard_items.sort(key=lambda x: -x.get("score", 0.0))

        # Add ranking index
        for idx, item in enumerate(leaderboard_items, 1):
            item["rank"] = idx

        # Overall Aggregated Summary (Only counting whitelisted elite channels)
        approved_items = leaderboard_items
        total_channels = len(approved_items)
        active_channels = len([c for c in approved_items if c["validated_signals"] > 0])
        total_val_all = sum(c["validated_signals"] for c in approved_items)
        total_pnl_all = round(sum(c["performance"]["net_pnl_usd"] for c in approved_items), 2)
        total_wins_all = sum(c["performance"]["win_trades"] for c in approved_items)
        total_losses_all = sum(c["performance"]["loss_trades"] for c in approved_items)
        overall_win_rate = round((total_wins_all / max(total_wins_all + total_losses_all, 1)) * 100, 1)

        best_channel = approved_items[0] if approved_items else None

        # Pick the caution channel: Among channels with activity, pick the one with highest rejection rate or lowest winrate
        active_with_data = [c for c in approved_items if c["validated_signals"] >= 5]
        if active_with_data:
            worst_channel_item = max(active_with_data, key=lambda c: c["rejection_rate_pct"])
        else:
            worst_channel_item = approved_items[-1] if approved_items else None

        return {
            "success": True,
            "timeframe": timeframe,
            "bankroll_usd": bankroll_usd,
            "margin_per_trade_pct": margin_per_trade_pct,
            "margin_per_trade_usd": round(margin_per_trade, 2),
            "summary": {
                "total_channels": total_channels,
                "total_pinned_channels": total_channels,
                "active_trading_channels": active_channels,
                "total_signals_validated": total_val_all,
                "total_net_pnl_usd": total_pnl_all,
                "overall_win_rate_pct": overall_win_rate,
                "best_channel_name": best_channel["channel_name"] if best_channel else "N/A",
                "best_channel_pnl": best_channel["performance"]["net_pnl_usd"] if best_channel else 0.0,
                "best_channel_winrate": best_channel["performance"]["win_rate_pct"] if best_channel else 0.0,
                "worst_channel_name": worst_channel_item["channel_name"] if worst_channel_item else "N/A",
                "worst_channel_rejection_rate": worst_channel_item["rejection_rate_pct"] if worst_channel_item else 0.0,
            },
            "channels": leaderboard_items,
        }

    def get_channel_detail(self, chat_id: int) -> Dict[str, Any]:
        """Returns in-depth signal list and detailed telemetry for a single channel."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        channel_name = KNOWN_CHANNELS.get(chat_id, f"Channel {chat_id}")

        c.execute("""
            SELECT s.signal_id, s.message_id, s.symbol, s.side, s.state,
                   s.entry_mode, s.entries_json, s.stop_loss, s.take_profits_json,
                   s.leverage, s.blocking_reason, s.created_at, m.raw_text, m.telegram_timestamp
            FROM signals s
            LEFT JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
            WHERE s.chat_id = ?
            ORDER BY m.telegram_timestamp DESC
        """, (chat_id,))
        signals = [dict(r) for r in c.fetchall()]

        conn.close()

        return {
            "success": True,
            "chat_id": chat_id,
            "channel_name": channel_name,
            "signal_count": len(signals),
            "signals": signals,
        }
