# 🚀 Quantum AI Trading Bot v2.2.0 Enterprise

Phiên bản phát hành chính thức tích hợp Hội Đồng Lượng Tử AI Đa Tác Nhân (Quantum Council Multi-Agent System), bộ khóa đòn bẩy Bearish Panic Clamp và bộ cài đặt trọn gói Zero-Config cho Windows 10/11.

---

### 🌟 Tính Năng Mới & Nâng Cấp Đột Phá:

1. **🛡️ Macro Bearish Panic Leverage Clamp (Ghìm Trần Đòn Bẩy Khi Thị Trường Sập):**
   - Khi Bitcoin rơi vào trạng thái `BEARISH_PANIC` ($< \text{EMA20} \ \& \ \text{EMA50}$ hoặc $\text{RSI 1H} < 40$), hệ thống tự động khóa trần đòn bẩy mọi lệnh Altcoin LONG tối đa **18x** (dải 15x–20x), ngay cả khi đang bật chế độ Ferrari Mode.
   - Triệt tiêu hoàn toàn rủi ro rung lắc gây áp lực âm ROE lớn cho tài khoản khi đi ngược sóng thị trường.

2. **🧠 Hội Đồng Lượng Tử Đa Tác Nhân (Quantum Council Harness - 100% Python Local AI):**
   - 4 Đặc vụ AI độc lập thẩm định mọi tín hiệu giao dịch với độ trễ nội bộ $\le 0.5\text{ms}$:
     - `TechnicalScoutAgent`: Phân tích Smart Money Concepts (SMC), Order Block, quét thanh khoản (Liquidity Sweeps), đảm bảo $R:R \ge 2.0$.
     - `MacroRegimeAgent`: Đánh giá tương quan dòng tiền Bitcoin 4H/1H.
     - `SentimentSentinelAgent`: Quét từ khóa Thiên nga đen & tin tức FUD (SEC, Hack, Delist...).
     - `RedTeamSkepticAgent`: Phản biện bắt lỗi các bẫy bơm thổi (Pump Trap) và bắt dao rơi (Falling Knife).
   - Cơ chế **Autonomous Local Fallback**: Tự động chuyển giao quyền quyết định cho Hội Đồng Nội Bộ khi Google Gemini Cloud hết credit trả trước (mã 402), giúp bot hoạt động liên tục 24/7 mà không tốn chi phí API.

3. **💎 Đồng Bộ Hóa 8 Kênh Tinh Hoa (8 Elite Channels) & 1-Click Auto-Join:**
   - Cập nhật danh sách 8 kênh tín hiệu chuẩn mực (Whales Circle, Coin Chief, Crypto Leopard's, Crypto Devil, The Wolf, Crypto Monk, Bitcoin Bulls, Crypto Mermaids).
   - Nút bấm tham gia nhanh 8 kênh 1-Click Auto-Join tích hợp ngay trên giao diện Quản Lý Kết Nối.

4. **⚡ Sửa Lỗi Hiển Thị BTC $0 & Truy Xuất 1.000 Lệnh Lịch Sử:**
   - Cơ chế tự động fetch nến klines từ Binance định kỳ trong endpoint `/market-regime` giúp Header hiển thị chính xác giá BTC và trạng thái thị trường thời gian thực.
   - Mở rộng phân trang lịch sử lên 1.000 lượt khớp lệnh, sắp xếp lệnh mới nhất lên đầu danh sách.

5. **📦 Bộ Cài Đặt Zero-Config (Tự Động Hóa 100% Trên Máy Mới):**
   - Bộ cài đặt NSIS Standalone `telegram-binance-signal-executor_2.2.0_x64-setup.exe` (~97.7 MB) đã bao gồm đầy đủ Python runtime, WebView2 hooks và cơ sở dữ liệu `%APPDATA%`. Người dùng chỉ cần tải về, nhấn Install là có thể sử dụng ngay lập tức mà không cần cài thêm bất kỳ công cụ nào.

---

### 📦 Tải Về & Cài Đặt:
- **Tải file bộ cài đặt trực tiếp bên dưới:** `telegram-binance-signal-executor_2.2.0_x64-setup.exe`
- **Hướng dẫn chi tiết:** Xem file `docs/HUONG_DAN_CAI_DAT_MAY_MOI.md` trong mã nguồn.
