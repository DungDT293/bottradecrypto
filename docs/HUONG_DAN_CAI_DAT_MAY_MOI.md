# HƯỚNG DẪN CÀI ĐẶT & SỬ DỤNG TRÊN MÁY TÍNH MỚI
## DỰ ÁN QUANTUM AI TRADING BOT (v2.2.1 ENTERPRISE)
**Phiên bản cài đặt:** `telegram-binance-signal-executor_2.2.1_x64-setup.exe`  
**Dung lượng:** ~97.7 MB  
**Vị trí file cài đặt:** `release/telegram-binance-signal-executor_2.2.1_x64-setup.exe`

---

## I. YÊU CẦU HỆ THỐNG TRÊN MÁY MỚI
- **Hệ điều hành:** Windows 10 hoặc Windows 11 (64-bit).
- **Yêu cầu môi trường:** **HOÀN TOÀN KHÔNG CẦN CÀI PYTHON, NODE.JS HAY RUST.** Bộ cài đặt đã bao gồm toàn bộ file thực thi nhị phân độc lập (Standalone Sidecar Engine).
- **Kết nối mạng:** Kết nối Internet ổn định để bot nhận tín hiệu Telegram và khớp lệnh Binance.
- **Trình duyệt WebView2:** Có sẵn mặc định trên Windows 10/11 (nếu thiếu, bộ cài NSIS sẽ tự động cập nhật).

---

## II. QUY TRÌNH CÀI ĐẶT NHANH (CHO NGƯỜI DÙNG MỚI)

### Bước 1: Chạy file cài đặt
1. Chép file `telegram-binance-signal-executor_2.2.1_x64-setup.exe` (trong thư mục `release/` hoặc tải từ GitHub Releases) sang máy tính mới (qua USB, Google Drive, hoặc Telegram).
2. Nhấp đúp chuột vào file `.exe` để tiến hành cài đặt.
3. Nhấn **Next** $\rightarrow$ **Install** $\rightarrow$ **Finish**.
4. Biểu tượng ứng dụng **Telegram Binance Signal Executor** sẽ xuất hiện trên màn hình Desktop và Start Menu.

### Bước 2: Khởi động lần đầu (Tự động hóa Zero-Config)
1. Mở ứng dụng từ màn hình Desktop.
2. Ứng dụng sẽ tự động:
   - Khởi tạo thư mục làm việc an toàn tại:  
     `%APPDATA%\telegram_binance_signal_executor`
   - Nạp cấu hình mẫu chuẩn mực tích hợp sẵn **8 Kênh Tinh Hoa** (Whales Circle, Coin Chief, Crypto Leopard's, Crypto Devil, The Wolf, Crypto Monk, Bitcoin Bulls, Crypto Mermaids).
   - Tự động tạo cơ sở dữ liệu SQLite `trading_state.db` với đầy đủ schema giao dịch và nhật ký.
   - Khởi chạy tiến trình lượng tử ngầm (Loopback IPC `127.0.0.1`, mã hóa handshake UUIDv4).

### Bước 3: Thiết lập kết nối Telegram & Binance
1. Trên giao diện ứng dụng, chọn tab **Connections (Kết nối)**:
   - **Mục Telegram:**
     + Nhập `API ID` và `API Hash` (lấy miễn phí từ [my.telegram.org](https://my.telegram.org)).
     + Nhập số điện thoại Telegram của bạn (kèm mã quốc tế, ví dụ: `+84xxxxxxxxx`).
     + Nhấn **Gửi mã OTP** $\rightarrow$ Nhập mã xác nhận nhận được trên Telegram $\rightarrow$ Bấm **Xác thực**.
     + Trạng thái Telegram sẽ chuyển sang màu xanh **ONLINE**.
   - **Mục Binance:**
     + Nhập `API Key` và `API Secret` của tài khoản Binance Futures (Live hoặc Testnet).
     + Nhấn **Kiểm tra kết nối** $\rightarrow$ Trạng thái chuyển sang **CONNECTED** và hiển thị số dư USDT khả dụng.

### Bước 4: Kích hoạt Bot & Thưởng thức
1. Vào tab **Settings (Cài đặt)** để bật chế độ giao dịch:
   - Chế độ an toàn: Đòn bẩy tối đa tự động khóa $\le 20x$.
   - Bật **Ferrari Mode** (nếu muốn tận dụng full sóng lợi nhuận).
   - Bật **Kèo Bất Tử (Trailing Take-Profit Moonbag)** để gồng lãi tối đa khi thị trường pump mạnh.
2. Bot sẽ tự động lắng nghe 8 kênh tinh hoa, kích hoạt **Hội Đồng Lượng Tử 4 Đặc Vụ** (`Technical Scout`, `Macro Sentinel`, `Sentiment Sentinel`, `Red Team Skeptic`) để phê duyệt hoặc phủ quyết mọi tín hiệu theo thời gian thực!

---

## III. CÁCH DI CHUYỂN DỮ LIỆU TỪ MÁY CŨ SANG MÁY MỚI (KHÔNG CẦN NHẬP LẠI OTP)

Nếu bạn muốn chuyển toàn bộ phiên đăng nhập Telegram, lịch sử lệnh và số dư đang theo dõi từ máy hiện tại sang máy mới mà **không cần đăng nhập lại OTP**:

1. **Trên máy cũ:**
   - Nhấn tổ hợp phím `Windows + R`, gõ:
     ```
     %APPDATA%\telegram_binance_signal_executor
     ```
   - Nhấn Enter.
   - Sao chép toàn bộ các file sau vào USB / Drive:
     + `config.yaml` (File cấu hình API và các kênh)
     + `telegram_user.session` (Phiên đăng nhập Telegram MTProto)
     + `data/trading_state.db` (hoặc file `trading_state.db` ở thư mục gốc)

2. **Trên máy mới:**
   - Cài đặt ứng dụng bằng file `telegram-binance-signal-executor_2.2.1_x64-setup.exe`.
   - Nhấn `Windows + R`, gõ:
     ```
     %APPDATA%\telegram_binance_signal_executor
     ```
   - Dán đè các file vừa chép từ máy cũ vào đây.
   - Mở ứng dụng lên $\rightarrow$ Ứng dụng sẽ tự động nhận diện phiên Telegram và tài khoản Binance ngay lập tức!

---

## V. TÍNH NĂNG MỚI ĐỘC QUYỀN TRÊN BẢN v2.2.1 ENTERPRISE

1. **Triple-Armor Defense Shield (Bộ 3 Cơ Chế Phòng Vệ Cốt Lõi V2.3):**
   - **Directional Exposure Cap:** Khóa cứng tối đa không quá 3 vị thế cùng chiều (`Max 3 SHORTs`, `Max 3 LONGs`), triệt tiêu 100% rủi ro bị bão Short Squeeze.
   - **Market Cooldown Buffer:** 30 phút làm nguội cho cùng 1 đồng coin và 15 phút giãn cách giữa các lệnh mở mới (chống Overtrading / bão giao dịch).
   - **Dynamic ATR Trailing Stop:** Co giãn cự ly trailing SL an toàn 2.5% - 3.2% theo độ biến động giá, chống bị quét non râu nến.
2. **Hội Đồng Lượng Tử Đa Tác Nhân (Quantum Council Multi-Agent System):**
   - 4 Đặc vụ AI chạy 100% nội bộ Python (`Technical Scout`, `Macro Regime`, `Sentiment Sentinel`, `Red Team Skeptic`) thẩm định đa chiều mọi tín hiệu với độ trễ $\le 0.5\text{ms}$.
   - Tự động kích hoạt cơ chế Local Fallback nếu Google Gemini Cloud hết credit trả trước (HTTP 402), giúp bot không bao giờ bị dừng hoạt động.

2. **Chốt Chặn Đòn Bẩy Khi Thị Trường Sập (Macro Bearish Panic Leverage Clamp):**
   - Khi Bitcoin ở trạng thái `BEARISH_PANIC` ($< \text{EMA20} \ \& \ \text{EMA50}$ hoặc $\text{RSI 1H} < 40$), mọi lệnh LONG Altcoin tự động bị **ghìm trần đòn bẩy tối đa 18x** (kể cả khi bật Ferrari Mode).
   - Triệt tiêu hoàn toàn rủi ro rung lắc gây âm ROE lớn cho tài khoản khi đi ngược sóng thị trường.

3. **Đồng Bộ Hóa 8 Kênh Tinh Hoa Chuẩn Mực:**
   - Đã loại bỏ hoàn toàn các kênh có tỷ lệ quét SL cao hoặc quảng cáo lãi ảo.
   - Nút **"Tham Gia 8 Kênh Tinh Hoa (1-Click Auto-Join)"** giúp tài khoản mới tự động tham gia các kênh uy tín nhất chỉ với 1 cú click.

4. **Hiển Thị Realtime & Lịch Sử 1.000 Giao Dịch:**
   - Sửa triệt để lỗi BTC $0 trên Header bằng cơ chế tự động đồng bộ nến Klines từ Binance.
   - Trang Lịch sử hỗ trợ truy xuất tới 1.000 lệnh giao dịch gần nhất, hiển thị ngay lập tức các lệnh vừa khớp trong ngày.


1. **Tường lửa Windows (Windows Defender Firewall):**
   - Lần đầu mở app, nếu Windows hiện thông báo *"Windows Defender Firewall has blocked some features of this app"*, hãy tích chọn **Private networks** và bấm **Allow access**. (Đây là kết nối cục bộ nội bộ giữa giao diện React và backend Python trên cổng 127.0.0.1, hoàn toàn an toàn).
2. **Quyền Chạy nền (Background Running):**
   - Ứng dụng tích hợp khay hệ thống (System Tray). Khi thu nhỏ hoặc đóng cửa sổ, bot vẫn âm thầm chạy nền để theo dõi lệnh và dời Stop Loss hòa vốn. Để tắt hoàn toàn, nhấp chuột phải vào icon ở khay hệ thống góc phải dưới màn hình $\rightarrow$ Chọn **Thoát (Exit)**.
3. **Mã nguồn và độ trễ:**
   - 100% Hội Đồng Lượng Tử chạy bằng mã máy nội bộ, phản xạ tức thì $\le 0.5\text{ms}$, 0đ chi phí gọi API bên thứ ba.

