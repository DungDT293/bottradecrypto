# TELEGRAM BINANCE SIGNAL EXECUTOR

Hệ thống tự động tiếp nhận tín hiệu giao dịch từ các nhóm/kênh Telegram qua tài khoản cá nhân (MTProto Telethon), phân tích entry/SL/TP, kiểm soát rủi ro và quản lý lệnh trên sàn Binance USD-M Futures.

---

## 1. BỐI CẢNH VÀ NGUYÊN TẮC BẢO VỆ TỐI THƯỢNG

1. **Tài khoản người dùng (MTProto):** Bạn chỉ là thành viên tham gia nhóm tín hiệu, không có quyền thêm bot. Hệ thống sử dụng Telethon đăng nhập tài khoản Telegram thật của bạn, hoạt động ở chế độ **READ-ONLY** (chỉ đọc, tuyệt đối không gửi tin nhắn, không tự tham gia nhóm, không can thiệp vào nhóm).
2. **Binance USD-M Futures:**
   - Chỉ hỗ trợ hợp đồng Perpetual ký quỹ USDT.
   - Tài khoản Futures thông thường, **One-Way Position Mode**.
   - **ISOLATED margin** theo chính sách an toàn mặc định.
   - **Tối đa 1 tín hiệu đang hoạt động trên mỗi symbol**.
   - Nếu tài khoản sàn ở chế độ Hedge Mode hoặc có vị thế thủ công ngoài hệ thống trên symbol đó: Báo **BLOCKED**, không can thiệp.
3. **Mặc định an toàn:**
   - Mặc định khởi chạy ở chế độ **READ_ONLY**.
   - Không tự ý đặt lệnh thật, không hứa hẹn lợi nhuận, không tự ý nới lỏng rủi ro để vào nhiều lệnh hơn.

---

## 2. CẤU TRÚC DỰ ÁN

```
telegram_binance_signal_executor/
├── desktop/                   # Desktop App Shell (Tauri v2 + React + TypeScript)
│   ├── src/                   # React Frontend Source
│   │   ├── components/        # Sidebar, Header, ConfirmModal, Toast
│   │   ├── context/           # AppContext (real-time state & telemetry)
│   │   ├── pages/             # 10 Trang quản lý chuyên biệt (Overview, Connections, ...)
│   │   ├── services/          # HTTP API client, WebSocket stream client, BackendBridge
│   │   └── types/             # TypeScript definitions cho models & responses
│   └── src-tauri/             # Rust Process Supervisor (Tauri 2.12)
│       ├── src/lib.rs         # Khởi động child process, handshake file, kill on exit
│       └── tauri.conf.json    # Cấu hình cửa sổ 1280x820, quyền hạn & bảo mật
├── backend/                   # Python FastAPI Backend Layer
│   ├── api/                   # Router endpoints & Middleware xác thực Session Token
│   ├── events/                # EventBus & WebSocket pub/sub
│   ├── runtime/               # Handshake manager, port discovery, Uvicorn server
│   └── launcher.py            # CLI entrypoint khởi chạy backend độc lập hoặc qua Tauri
├── services/                  # Application Services Layer (Clean Architecture)
│   ├── telegram_service.py    # Quản lý MTProto connection, dialogs, history collection
│   ├── binance_service.py     # Đồng bộ số dư ký quỹ, vị thế, kiểm tra One-Way
│   ├── trading_service.py     # Trạng thái engine, signals, protection status
│   ├── stats_service.py       # PnL (00:00 Asia/Ho_Chi_Minh), win rate, telemetry
│   └── alert_service.py       # Hệ thống cảnh báo INFO/WARNING/CRITICAL chống spam
├── config/
│   ├── config.py              # Pydantic Settings & YAML loader
│   ├── policy_defaults.py     # Schema và giá trị mặc định cho Risk & Execution
│   └── source_registry.py     # Quản lý allowlist và override theo từng kênh
├── core/
│   ├── enums.py               # Side, OrderType, SignalState, ExecutionMode, FieldSource...
│   ├── models.py              # ParsedSignal, ValidatedSignal, Order, Position (Decimal)
│   └── exceptions.py          # Custom exceptions (SignalValidationError, RiskCheckError...)
├── parser/
│   ├── normalizer.py          # Xử lý Unicode NFKC, emoji keycaps, triệt tiêu mã độc/link
│   ├── signal_parser.py       # Parser tất định, bám sát nguồn dữ liệu (FieldSource)
│   ├── update_parser.py       # Phân tích 13 loại bản tin hành chính Telegram
│   └── validator.py           # Kiểm tra logic ngữ nghĩa (SL/TP vs Entry, khoảng cách SL)
├── risk/
│   ├── risk_engine.py         # Phân bổ khối lượng theo equity, dự phòng phí & trượt giá, chặn lỗ ngày
├── exchange/
│   ├── exchange_info.py       # Bộ lọc sàn (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL)
│   ├── binance_client.py      # Async client Binance USD-M (phân tách /order và /algoOrder)
│   ├── mock_exchange.py       # Mock sàn giả lập độ trung thực cao để test offline
│   └── paper_exchange.py      # Giả lập Paper Trading (tính spread, taker fees, slippage)
├── execution/
│   ├── position_manager.py    # Kiểm soát 1 signal/symbol, fail-safe đóng khẩn cấp
│   ├── order_manager.py       # Quản lý lifecycle lệnh, đặt SL algo, dời breakeven
│   └── reconciliation.py      # Đối chiếu trạng thái giữa SQLite và sàn khi khởi động lại
├── storage/
│   ├── database.py            # SQLite WAL mode, lưu messages, signals, orders, pnl
│   └── state_machine.py       # Máy trạng thái hữu hạn cho tín hiệu
├── telegram/
│   ├── auth_helper.py         # Hỗ trợ đăng nhập Telethon CLI an toàn tại local
│   ├── client.py              # Telethon client bọc an toàn read-only
│   └── listener.py            # Lắng nghe tin nhắn mới & chỉnh sửa, chống trùng lặp
├── cli/
│   └── main.py                # Điểm vào dòng lệnh (gui, telegram-login, list-chats...)
├── tests/                     # 55 bài kiểm thử đơn vị, dịch vụ và UI (100% PASS)
├── DOCUMENTATION_BINANCE_API.md
├── POLICY_SPECIFICATION.md
├── requirements.txt
├── config.example.yaml
├── .env.example
└── .gitignore
```

---

## 3. TÀI LIỆU VÀ ĐẶC THÙ BINANCE API HIỆN HÀNH

- **Ngày xác minh tài liệu:** 15/10/2026.
- **Cảnh báo lỗi `-4120` (`STOP_ORDER_SWITCH_ALGO`):**
  Trên Binance USD-M Futures hiện nay, các lệnh điều kiện Stop Loss (`STOP_MARKET`) hoặc Take Profit (`TAKE_PROFIT_MARKET`) **bắt buộc** phải gửi qua endpoint Algo:
  `POST /fapi/v1/algoOrder` với `triggerPrice`, `reduceOnly=true`, `workingType=MARK_PRICE`.
  Nếu gửi qua `/fapi/v1/order`, sàn sẽ từ chối ngay lập tức với mã lỗi `-4120`.
- **Cơ chế Fail-Safe khi Entry Fill nhưng SL thất bại:**
  Nếu Entry limit đã khớp nhưng lệnh Stop Loss bị sàn từ chối:
  1. Hủy ngay lập tức các pending entry còn lại của tín hiệu.
  2. Gửi lệnh `MARKET` với `reduceOnly=true` để đóng khẩn cấp toàn bộ khối lượng vừa khớp.
  3. Xác minh vị thế trên sàn đã về 0 và ghi log cảnh báo: `BI CHAN: SL THAT BAI - DA DONG KHAN CAP VI THE`.

---

## 4. HƯỚNG DẪN CÀI ĐẶT MÔI TRƯỜNG

### Trên Windows:
1. Mở PowerShell trong thư mục dự án:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Tạo file cấu hình từ mẫu:
   ```powershell
   Copy-Item .env.example .env
   Copy-Item config.example.yaml config.yaml
   ```

### Trên Linux (Ubuntu/Debian):
1. Cài đặt Python 3.11+:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Tạo file cấu hình:
   ```bash
   cp .env.example .env
   cp config.example.yaml config.yaml
   ```

---

## 5. HƯỚNG DẪN KẾT NỐI TELEGRAM (TẠI LOCAL)

> [!IMPORTANT]
> **Tuyệt đối không gửi OTP, mật khẩu 2FA, API secret hay session file cho AI hoặc bất kỳ ai.** Quá trình đăng nhập được thực hiện cục bộ trực tiếp trên terminal của bạn.

1. Lấy `TELEGRAM_API_ID` và `TELEGRAM_API_HASH` miễn phí từ cổng chính thức của Telegram: [my.telegram.org](https://my.telegram.org).
2. Điền 2 giá trị này vào file `.env`.
3. Chạy lệnh đăng nhập tương tác:
   ```bash
   python -m cli.main telegram-login
   ```
   Nhập số điện thoại, mã OTP Telegram gửi về app, và mật khẩu 2FA (nếu có). Session sẽ được lưu cục bộ tại `data/telegram_user.session` (đã được cấu hình trong `.gitignore`).
4. Xem danh sách các nhóm/kênh bạn đang tham gia để lấy `chat_id`:
   ```bash
   python -m cli.main list-chats
   ```
5. Mở file `config.yaml`, dán các `chat_id` bạn muốn bot theo dõi vào mục:
   ```yaml
   telegram:
     allowed_chat_ids:
       - -1001234567890
       - -1009876543210
   ```

---

## 6. DANH MỤC LỆNH DÒNG LỆNH (CLI COMMANDS)

| Lệnh | Ý nghĩa |
| :--- | :--- |
| `python app_gui.py` hoặc `python -m cli.main gui` | **Khởi chạy giao diện Desktop App PySide6** |
| `python -m cli.main telegram-login` | Đăng nhập tài khoản Telegram MTProto tại local |
| `python -m cli.main list-chats` | Hiển thị danh sách nhóm/kênh và Chat ID để cấu hình allowlist |
| `python -m cli.main parse-samples` | Phân tích 9 mẫu tín hiệu thực tế và hiển thị báo cáo |
| `python -m cli.main doctor` | Chẩn đoán toàn diện hệ thống (Python, DB, Config, API keys) |
| `python -m cli.main status` | Xem trạng thái hệ thống, số tin nhắn, các lệnh/vị thế đang mở |
| `python -m cli.main listen` | Khởi động trình lắng nghe tín hiệu Telegram |
| `python -m cli.main collect-history` | Thu thập lịch sử đọc tin nhắn từ kênh Telegram (giới hạn 7 ngày, max 1000 tin) |
| `python -m cli.main export-history` | Xuất lịch sử tín hiệu và cập nhật ra file JSON |
| `python -m cli.main export-report` | Xuất báo cáo audit timeline và các bất thường ra Markdown |
| `python -m cli.main offline-replay` | Giả lập phát lại offline chuỗi sự kiện tin nhắn & cập nhật |
| `python -m cli.main shadow-mode` | Chạy ngầm quan sát tín hiệu thị trường thực tế không đặt lệnh |
| `python -m cli.main testnet-check` | Kiểm tra kết nối và quyền hạn API trên Binance Testnet |

---

## 7. BÁO CÁO PHÂN TÍCH 9 MẪU TÍN HIỆU THỰC TẾ

Chạy lệnh `python -m cli.main parse-samples` để kiểm tra kết quả phân tích:

1. **GRASS/USDT (LONG):**
   - 2 entry (0.5020, 0.4870), 2 TP (0.5230, 0.5440), SL (0.4720).
   - TP weights được đọc rõ từ tin: 50% TP1, 50% TP2.
   - Nhận diện cảnh báo: "don't chase above ." bị thiếu giá chặn.
   - Chưa có entry weights: chuyển trạng thái `NEEDS_POLICY` chờ phê duyệt.
   - "Consider moving SL" là gợi ý tùy chọn, không bắt buộc dời SL.

2. **#ZEREBRO/USDT (LONG):**
   - 1 entry (0.04800), 3 TP (0.04905, 0.05100, 0.05500), SL (0.04480).
   - Leverage: Cross 20x to 50x -> Không chọn mức 50x nguy hiểm, áp trần theo chính sách rủi ro (max 5x).
   - Thiếu tỷ lệ TP -> chuyển `NEEDS_POLICY`.

3. **#RSRUSDT (LONG):**
   - 1 entry (0.002075), 4 TP, SL (0.001925).
   - Thiếu margin mode và tỷ lệ TP -> chuyển `NEEDS_POLICY`.

4. **#TRUTH /USDT (SHORT):**
   - Đúng 3 TP trích xuất: 0.02250, 0.02175, 0.019999.
   - Chứa câu: "Short BELOW (0.02300)(0.02325)". Ngữ nghĩa 2 mức giá sau chữ BELOW không rõ ràng -> chuyển `NEEDS_REVIEW` (chặn không đặt lệnh).
   - Link referral Bitunix được tự động loại bỏ.

5. **Q/USD (SHORT):**
   - Đúng 6 TP trích xuất: 0.04970, 0.04920, 0.04870, 0.04820, 0.04760, 0.04710.
   - Symbol có quote USD (không phải USDT) -> Bị chặn (`symbol_candidate = None`).
   - Stop Loss ghi `052506` là số mơ hồ, thiếu dấu chấm thập phân -> Tuyệt đối không tự sửa thành 0.052506 -> Bị chặn (`REJECTED`).

6. **$AKE/USDT (LONG):**
   - Hỗ trợ chuẩn xác các lỗi chính tả phổ biến: `ENTERY PRICE: 0.02923` và `STOPP LOSS: 0.02740`.
   - Leverage 25x-50x -> Không lấy mức cao nhất, áp trần an toàn.

7. **Coin #QTUM/USDT (SHORT):**
   - Entry là một vùng giá (`Entries: 0.8960 - 0.9160`) -> chuyển `NEEDS_POLICY`. Khi được người dùng duyệt chính sách (ví dụ: `MID_POINT`), hệ thống tính mức limit 0.9060.

8. **#ETH/USDT (SHORT):**
   - 2 entry (2367, 2387), 3 TP (2344, 2305, 2250), SL (2408).
   - Yêu cầu đòn bẩy 200X -> Áp trần an toàn xuống tối đa 5x theo cấu hình, không sao chép 200x.
   - Có chỉ dẫn Trailing Breakeven sau TP1 (`is_breakeven_mandatory = True`).

9. **#ATOM/USDT (Mâu thuẫn hướng lệnh):**
   - Tiêu đề ghi `#SHORT 🔴`, nhưng phần nội dung entry ghi `BUY : 1) 1.674 - 100%`.
   - Phát hiện xung đột hướng lệnh trực tiếp -> Chuyển `NEEDS_REVIEW`, chặn tuyệt đối không vào lệnh.

---

## 8. CÁC CHẾ ĐỘ HOẠT ĐỘNG VÀ KÍCH HOẠT LIVE TRADING

Hệ thống hỗ trợ 4 chế độ qua tham số `mode` trong `config.yaml`:
1. `READ_ONLY` (Mặc định): Chỉ nhận tin, chuẩn hóa, phân tích, đối chiếu và ghi log ra console/SQLite. Hoàn toàn không tương tác tài khoản sàn.
2. `PAPER`: Mô phỏng khớp lệnh thực tế bao gồm độ trượt giá (slippage) và phí giao dịch (taker fee 0.05%).
3. `TESTNET`: Gửi lệnh thực tế lên sàn Binance Futures Testnet (`https://testnet.binancefuture.com`).
4. `LIVE`: Giao dịch thật trên Binance Futures.

### Preflight Checklist trước khi kích hoạt LIVE:
- [ ] Đã chạy `python -m cli.main doctor` và toàn bộ các mục đều báo `[OK]`.
- [ ] Tài khoản Binance Futures đã được xác minh One-Way Position Mode.
- [ ] Đã kiểm tra số dư ký quỹ USDT khả dụng.
- [ ] Đã kiểm duyệt toàn bộ thông số trong `config.yaml` (`risk_per_signal_pct`, `max_daily_loss_pct`...).
- [ ] Đã thử nghiệm thành công trên chế độ PAPER hoặc TESTNET.
- [ ] Để kích hoạt, bạn tự mở file `config.yaml` tại máy local và sửa:
  ```yaml
  mode: LIVE
  live_trading_enabled: true
  ```
  *(Hệ thống mặc định khóa `live_trading_enabled: false` để bảo vệ an toàn vốn).*

---

## 9. BÁO CÁO KẾT QUẢ KIỂM THỬ THỰC TẾ

Toàn bộ kiểm thử được chạy bằng `pytest`:
- **Tổng số test:** 55/55 PASSED (100%).
- **Thời gian chạy:** ~4.63s.

### Phân loại phạm vi kiểm thử:
- **Offline / Mock & Service Testing (Đã kiểm thử toàn diện 55/55 PASS):**
  - Application Services (`StatsService` múi giờ Asia/Ho_Chi_Minh mốc 00:00, `AlertService` chống spam, `TradingService` kiểm tra bảo vệ SL, `BinanceService` đọc an toàn, `TelegramService` che thông tin nhạy cảm).
  - PySide6 UI Pages (khởi tạo 10 màn hình, layout và signal wiring off-screen không lỗi).
  - Parser logic (9/9 mẫu tin nhắn, Unicode NFKC, injection sanitization, edge cases).
  - Risk engine (tính size theo rủi ro equity, phí, trượt giá, chặn lỗ ngày).
  - State machine (chuyển đổi 12 trạng thái hợp lệ & chặn chuyển đổi phi logic).
  - Exchange mock (xác thực lỗi `-4120`, algo endpoint `/fapi/v1/algoOrder`, chặn thay đổi margin mode khi vị thế mở).
  - Differentiated TTL & Message Updates (phân tách TTL tin mới và TTL bản tin edit, phát hiện duplicate edit, out-of-order, unanchored edit).
  - Complex Event Chains (Happy path, Admin TP1 notification vs actual fill, pending entry cancel, partial fill cancel, reversal prevention, SL widening rejection, duplicate coin review, recursive reply linking, orphaned state reconciliation, idempotent algo order IDs, deleted message safety).
- **Live Network Testing (CHƯA CHẠY THẬT / BẢO VỆ MẶC ĐỊNH):**
  - Môi trường live chưa gửi bất kỳ lệnh thật nào (`live_trading_enabled: false`, `mode: READ_ONLY`).
  - Giao tiếp sàn thật chỉ được kích hoạt khi người dùng cung cấp API Key hợp lệ và chạy lệnh chẩn đoán `testnet-check` hoặc chuyển mode có chủ đích.

```
tests/test_binance_adapter_mock.py::test_error_4120_when_stop_market_sent_to_standard_endpoint PASSED
tests/test_binance_adapter_mock.py::test_algo_order_endpoint_accepts_stop_market PASSED
tests/test_binance_adapter_mock.py::test_cannot_change_margin_mode_when_position_open PASSED
tests/test_event_chains.py::test_scenario_1_happy_path_entry_to_be PASSED
tests/test_event_chains.py::test_scenario_2_admin_tp1_does_not_trigger_account_fill PASSED
tests/test_event_chains.py::test_scenario_3_pending_entry_admin_cancel PASSED
tests/test_event_chains.py::test_scenario_4_partial_fill_admin_cancel PASSED
tests/test_event_chains.py::test_scenario_5_admin_correction_does_not_reverse_position PASSED
tests/test_event_chains.py::test_scenario_6_sl_widening_increases_risk_rejected PASSED
tests/test_event_chains.py::test_scenario_7_unlinked_update_on_duplicate_coin_needs_review PASSED
tests/test_event_chains.py::test_scenario_8_recursive_reply_linking PASSED
tests/test_event_chains.py::test_scenario_9_restart_reconciliation_cleans_orphaned_state PASSED
tests/test_event_chains.py::test_scenario_10_idempotent_algo_order_id PASSED
tests/test_event_chains.py::test_scenario_11_deleted_message_handled_safely PASSED
tests/test_event_chains.py::test_scenario_12_old_signal_sl_edit_differentiated_ttl PASSED
tests/test_message_age_and_edits.py::test_new_signal_expired_is_blocked PASSED
tests/test_message_age_and_edits.py::test_old_signal_recent_edit_is_accepted PASSED
tests/test_message_age_and_edits.py::test_duplicate_edit_is_ignored PASSED
tests/test_message_age_and_edits.py::test_out_of_order_edit_is_flagged PASSED
tests/test_message_age_and_edits.py::test_unanchored_first_edit PASSED
tests/test_message_age_and_edits.py::test_reconnect_backlog_drops_stale_update PASSED
tests/test_order_manager.py::test_submit_entries_and_on_fill_sl_success PASSED
tests/test_order_manager.py::test_failsafe_emergency_close_when_sl_fails PASSED
tests/test_paper_simulation.py::test_paper_trading_market_order_with_slippage_and_fee PASSED
tests/test_parser_9_samples.py::test_sample_1_grass PASSED
tests/test_parser_9_samples.py::test_sample_2_zerebro PASSED
tests/test_parser_9_samples.py::test_sample_3_rsr PASSED
tests/test_parser_9_samples.py::test_sample_4_truth_ambiguous_entry PASSED
tests/test_parser_9_samples.py::test_sample_5_q_usd_unsupported_and_ambiguous_sl PASSED
tests/test_parser_9_samples.py::test_sample_6_ake_misspellings_and_leverage PASSED
tests/test_parser_9_samples.py::test_sample_7_qtum_range_entry PASSED
tests/test_parser_9_samples.py::test_sample_8_eth_200x_and_breakeven PASSED
tests/test_parser_9_samples.py::test_sample_9_atom_direction_contradiction PASSED
tests/test_parser_edge_cases.py::test_long_with_sl_above_entry_is_rejected PASSED
tests/test_parser_edge_cases.py::test_short_with_sl_below_entry_is_rejected PASSED
tests/test_parser_edge_cases.py::test_long_with_tp_below_entry_is_rejected PASSED
tests/test_parser_edge_cases.py::test_short_with_tp_above_entry_is_rejected PASSED
tests/test_parser_edge_cases.py::test_missing_sl_is_rejected PASSED
tests/test_parser_edge_cases.py::test_dangerous_content_and_links_are_neutralized PASSED
tests/test_parser_edge_cases.py::test_sl_distance_limits PASSED
tests/test_reconciliation.py::test_reconciliation_detects_external_close_and_cleans_orders PASSED
tests/test_reconciliation.py::test_reconciliation_blocks_if_hedge_mode PASSED
tests/test_risk_engine.py::test_calculate_position_size_single_entry PASSED
tests/test_risk_engine.py::test_calculate_position_size_multi_entry_worst_case PASSED
tests/test_risk_engine.py::test_reject_when_exceeds_max_total_open_risk PASSED
tests/test_risk_engine.py::test_reject_when_notional_below_min_notional PASSED
tests/test_risk_engine.py::test_daily_loss_limit PASSED
tests/test_backend_api.py::test_health_check_no_auth_required PASSED
tests/test_backend_api.py::test_auth_rejection_missing_or_invalid_token PASSED
tests/test_backend_api.py::test_snapshot_with_valid_token PASSED
tests/test_backend_api.py::test_read_only_strictly_blocks_write_operations PASSED
tests/test_backend_api.py::test_settings_get_and_update PASSED
tests/test_backend_api.py::test_websocket_auth PASSED
tests/test_state_machine.py::test_valid_state_transitions PASSED
tests/test_state_machine.py::test_invalid_state_transition_is_rejected PASSED
============================= 61 passed in 6.81s =============================
```

---

## 10. HƯỚNG DẪN KHỞI CHẠY DESKTOP APP (TAURI + REACT)

### A. Yêu cầu môi trường
- **Python:** 3.11+
- **Node.js:** v18+ (Đã xác minh v24.13.0, npm 11.6.2)
- **Rust & Cargo:** 1.80+ (Đã xác minh v1.94.0 x86_64-pc-windows-msvc)
- **Tauri CLI:** v2 (Đã xác minh v2.12.3)

### B. Chạy Desktop App trong môi trường phát triển (Dev Mode)
```powershell
# Chạy toàn bộ ứng dụng Tauri (tự động khởi động Vite dev server và Rust supervisor)
cd desktop
npm.cmd run tauri dev
```

### C. Chạy giao diện Web Frontend độc lập (Browser Dev)
```powershell
# Bước 1: Khởi động backend Python
python -m backend.launcher --port 8000

# Bước 2: Khởi động React Web Frontend
cd desktop
npm.cmd run dev
```
Truy cập: `http://localhost:5173`

### D. Biên dịch ứng dụng Desktop độc lập (Production Build) & Tạo Installer NSIS
```powershell
# 1. Build bundle React frontend
cd desktop
npm run build

# 2. Đóng gói Backend nhị phân độc lập
cd ..
pyinstaller --clean -y backend-x86_64-pc-windows-msvc.spec
copy dist\backend-x86_64-pc-windows-msvc.exe desktop\src-tauri\binaries\

# 3. Đóng gói bộ cài đặt Windows NSIS Setup (.exe)
cd desktop\src-tauri
cargo tauri build --bundles nsis
```
- **Tệp cài đặt đầu ra:** `desktop/src-tauri/target/release/bundle/nsis/telegram-binance-signal-executor_1.1.8_x64-setup.exe`
- **Tệp thực thi độc lập:** `desktop/src-tauri/target/release/app.exe`

---

## 11. NHẬT KÝ PHIÊN BẢN (CHANGELOG)

### Bản phát hành v1.1.8:
- **Triệt tiêu lỗi gửi lệnh Binance (UnboundLocalError `asyncio`):** Đưa `import asyncio` ra phạm vi module-level tại `binance_client.py` và `telegram/client.py`, giải quyết triệt để lỗi gián đoạn gửi lệnh khi rate-limiter không bị kích hoạt.
- **Sửa lỗi regex Bullet Parser:** Tách biệt rõ ràng chỉ mục bullet `\d+\)` và `\d+\.(?!\d)` với số thập phân, bảo toàn nguyên vẹn các mức giá như `0.04800` không bị nhận nhầm thành `4800`.
- **Kiểm soát chặt chẽ khoảng cách SL gốc:** Kiểm tra tỷ lệ khoảng cách `sl_dist_pct` trên giá SL nguyên bản của admin trước khi áp dụng đệm chống quét râu nến (anti-wick buffer).
- **Bộ cài đặt NSIS v1.1.8:** Đóng gói file cài đặt tự động `telegram-binance-signal-executor_1.1.8_x64-setup.exe`.

### Bản phát hành v1.1.7:
- **Single-entry Target Parser:** Khắc phục lỗi bóc tách khi tín hiệu chỉ có 1 mức entry dạng `Entry Targets: 1) 0.1160`.
- **Dynamic Auto-Entry:** Tự động bắt lệnh đón ngay khi giá thị trường tốt hơn hoặc bằng giá entry admin đưa ra.
- **Phân bổ Multi-TP (60% / 26% / 14%):** Tự động chia tỷ trọng khối lượng 3 bậc chốt lời, dời Stop Loss về Breakeven (Hòa vốn) ngay khi khớp TP1.
- **Tối ưu Rate Limiter Binance (2000 weight/phút):** Tách luồng ưu tiên cao nhất cho endpoint đặt lệnh `/order` và `/algoOrder`.
- **Self-Healing Reconciliation:** Tự động phát hiện vị thế mở và đối chiếu lệnh sàn, ngăn chặn tình trạng đặt lặp lệnh Stop Loss khi khởi động lại.



