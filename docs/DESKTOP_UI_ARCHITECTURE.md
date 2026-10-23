# TELEGRAM BINANCE SIGNAL EXECUTOR - DESKTOP DASHBOARD SHELL (v1.3.2)

Ứng dụng Desktop điều hành và quản trị giao dịch tín hiệu tự động thời gian thực (Real-time Trading Terminal), xây dựng trên nền tảng **Tauri v2 (Rust Core) + React 19 + TypeScript + Vite**.

---

## 1. KIẾN TRÚC TỔNG THỂ DESKTOP

```
desktop/
├── src/
│   ├── components/            # Sidebar điều hướng, Header, ConfirmModal, Toast, StatusPill
│   ├── context/               # AppContext (Quản lý state, live telemetry, snapshot, alerts)
│   ├── pages/                 # 11 Màn hình quản lý chuyên biệt:
│   │   ├── OverviewPage.tsx      # Tổng quan tài sản, PnL, trạng thái bot & kết nối
│   │   ├── ConnectionsPage.tsx   # Quản lý liên kết Telegram MTProto & Binance API
│   │   ├── GroupsPage.tsx        # Giám sát 5 nhóm tinh hoa, xem tin nhắn & lịch sử edit
│   │   ├── LeaderboardPage.tsx   # Bảng xếp hạng & đánh giá chất lượng 5 kênh tinh hoa
│   │   ├── SignalsPage.tsx       # Danh sách tín hiệu thời gian thực & chi tiết lệnh
│   │   ├── PositionsPage.tsx     # Quản lý vị thế đang mở, dời SL, đóng khẩn cấp
│   │   ├── OrdersPage.tsx        # Danh sách lệnh chờ Limit TP và Algo Stop Loss
│   │   ├── HistoryPage.tsx       # Lịch sử khớp lệnh & đối soát sàn Binance
│   │   ├── AnalyticsPage.tsx     # Thống kê hiệu suất PnL, Winrate, Profit Factor
│   │   ├── AlertsPage.tsx        # Nhật ký thông báo cảnh báo hệ thống
│   │   └── SettingsPage.tsx      # Cài đặt rủi ro, đòn bẩy 25x, Kèo Bất Tử, Autostart
│   ├── services/
│   │   ├── api.ts                # REST API client kết nối loopback tới Python backend
│   │   ├── websocket.ts          # WebSocket client nhận sự kiện real-time tức thì
│   │   └── bridge.ts             # Cầu nối IPC giao tiếp với Tauri Rust Supervisor
│   └── types/
│       └── api.ts                # Định nghĩa kiểu dữ liệu TypeScript (Channel, Signal, Order...)
└── src-tauri/
    ├── src/
    │   ├── lib.rs                # Khởi động tiến trình backend, giám sát cổng & handshake
    │   └── main.rs               # Điểm vào thực thi nhị phân của Tauri
    ├── tauri.conf.json           # Cấu hình cửa sổ 1280x820, security CSP, icon & bundles
    └── Cargo.toml                # Cấu hình package Rust (Tauri 2.12, plugins autostart)
```

---

## 2. NGUYÊN LÝ HOẠT ĐỘNG VÀ BẢO MẬT

1. **Giao tiếp an toàn nội bộ (Loopback IPC):**
   - Ứng dụng Desktop giao tiếp với Backend Python thông qua cổng cục bộ `127.0.0.1`.
   - Mỗi phiên khởi chạy sinh ngẫu nhiên một mã xác thực bảo mật `session_token` (UUIDv4) lưu trong file handshake `%APPDATA%\telegram_binance_signal_executor\backend_handshake.json`.
   - Mọi yêu cầu HTTP và kết nối WebSocket đều phải có header `X-Session-Token`, ngăn chặn hoàn toàn việc can thiệp trái phép từ bên ngoài.
2. **Cơ chế Real-time WebSocket:**
   - Khi có tin nhắn Telegram mới, tín hiệu được phân tích, hoặc lệnh TP/SL khớp trên Binance, Backend bắn sự kiện qua WebSocket tới Desktop UI trong vòng **< 5ms**.
   - Có cơ chế dự phòng tự động Polling mỗi 5 giây nếu WebSocket bị gián đoạn.
3. **Phòng thủ Whitelist 3 lớp (Defense-in-Depth):**
   - UI chỉ nạp và hiển thị **5 Nhóm Tinh Hoa** (`THE WOLF`, `Boom_Boom_Billionaires`, `CRYPTO LEOPARD'S`, `CRYPTO MONK`, `Crypto Neon`). Dữ liệu các nhóm cũ ngoài Whitelist bị chặn hoàn toàn ở cả backend và tầng render component.

---

## 3. HƯỚNG DẪN PHÁT TRIỂN & BIÊN DỊCH

### A. Chạy môi trường Dev:
```powershell
# Chạy toàn bộ ứng dụng desktop (Rust Shell + Webview):
npm run tauri dev

# Hoặc chỉ chạy giao diện Web trên trình duyệt:
npm run dev
```

### B. Biên dịch Bundle Frontend:
```powershell
npm run build
```

### C. Đóng gói bộ cài đặt Windows NSIS:
```powershell
cd src-tauri
cargo tauri build --bundles nsis
```
- File cài đặt tạo ra: `target/release/bundle/nsis/telegram-binance-signal-executor_1.3.2_x64-setup.exe`.
