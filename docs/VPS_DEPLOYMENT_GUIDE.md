# 🚀 HƯỚNG DẪN TRIỂN KHAI JARVIS QUANTUM AI CHẠY 24/7 TRÊN VPS

> **Hệ Thống Trợ Lý AI Giao Dịch Binance Futures & Quản Trị Rủi Ro Độc Lập**  
> **Phiên bản:** v2.5.0 (Jarvis Stark Protocol Mark 85)  
> **Kiến trúc:** Python 3.11+ / AsyncIO / Zero-Liquidation Engine / Telegram Telemetry

---

## 1. TỔNG QUAN KIẾN TRÚC

Khi triển khai trên **VPS (Virtual Private Server)**, bot sẽ:
1. **Chạy liên tục 24/7** kể cả khi Ngài tắt máy tính cá nhân hoặc mất mạng internet ở nhà.
2. **Độ trễ siêu thấp (< 50ms):** Máy chủ đặt gần datacenter Binance (Tokyo hoặc Singapore) giúp khớp lệnh Market và cài SL/TP nhanh như chớp.
3. **Giám sát & Điều khiển từ xa 100% qua Telegram:** Đóng lệnh, dời BE, bật/tắt Ferrari, xem sao kê PnL, đo sức khỏe ký quỹ trực tiếp từ điện thoại.
4. **Tự động phục hồi (Self-Healing):** Nếu VPS bị reboot do bảo trì, `systemd` sẽ tự động khởi động lại bot ngay lập tức mà không cần can thiệp.

---

## 2. CHỌN MUA VPS TỐI ƯU CHI PHÍ ($3 - $5 / THÁNG)

Ngài có thể chọn bất kỳ nhà cung cấp VPS nào có datacenter tại **Châu Á (Singapore / Tokyo)** hoặc **Châu Âu (Đức / Phần Lan)**:

| Nhà cung cấp | Gói đề xuất | Cấu hình | Datacenter khuyến nghị | Giá tham khảo |
| :--- | :--- | :--- | :--- | :--- |
| **Hetzner Cloud** | CX22 / CPX11 | 2 vCPU, 2GB - 4GB RAM, 40GB NVMe | Singapore hoặc Falkenstein | ~€3.79 - €4.50 / tháng |
| **Contabo** | Cloud VPS S | 4 vCPU, 8GB RAM, 50GB NVMe | Singapore hoặc Germany | ~$5.50 / tháng |
| **Vultr** | Regular Cloud | 1 vCPU, 2GB RAM, 55GB SSD | Singapore / Tokyo | ~$5.00 / tháng |
| **DigitalOcean** | Basic Droplet | 1 vCPU, 2GB RAM, 50GB SSD | Singapore | ~$6.00 / tháng |

> [!TIP]
> **Hệ điều hành khuyến nghị:** Chọn **Ubuntu 22.04 LTS** hoặc **Ubuntu 24.04 LTS (64-bit)**.

---

## 3. BƯỚC 1: KẾT NỐI VÀO VPS QUA SSH

Từ máy tính Windows của Ngài:
1. Nhấn `Windows + R`, gõ `wt` (hoặc `powershell`) và nhấn Enter.
2. Gõ lệnh kết nối SSH:
   ```bash
   ssh root@<IP_CỦA_VPS>
   # Ví dụ: ssh root@128.199.123.45
   ```
3. Nhập mật khẩu VPS được cấp khi mua (lưu ý khi gõ mật khẩu Linux sẽ không hiện ký tự, cứ gõ đúng rồi Enter).

---

## 4. BƯỚC 2: CÀI ĐẶT MÔI TRƯỜNG 1-DÒNG LỆNH

Dán nguyên khối lệnh sau vào terminal VPS để cập nhật hệ điều hành và cài Python 3:

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git curl screen htop
```

---

## 5. BƯỚC 3: TẢI MÃ NGUỒN VÀ CẤU HÌNH

### 5.1. Tải dự án từ GitHub
```bash
cd /root
git clone https://github.com/leonguyen2025/bottradecrypto.git
cd bottradecrypto
```

### 5.2. Cấu hình thông tin API Binance & Telegram
Chỉnh sửa file cấu hình:
```bash
nano config/config.yaml
```
*(Nếu chưa có, copy từ file mẫu: `cp config/config.yaml.example config/config.yaml`)*

Điền các thông tin quan trọng:
```yaml
mode: LIVE                          # Chế độ giao dịch tiền thật
live_trading_enabled: true          # Bật quyền can thiệp lệnh thật sàn Binance
ferrari_mode_enabled: true          # Bật Ferrari Mode x35-x40, max 20 lệnh

binance:
  api_key: "ĐIỀN_BINANCE_API_KEY_CỦA_NGÀI"
  api_secret: "ĐIỀN_BINANCE_API_SECRET_CỦA_NGÀI"

notifications:
  notification_bot_token: "ĐIỀN_TELEGRAM_BOT_TOKEN_TỪ_BOTFATHER"
  notification_chat_id: 123456789   # ID Telegram của Ngài
```
> *Nhấn `Ctrl + O` rồi Enter để Lưu, sau đó `Ctrl + X` để Thoát.*

---

## 6. BƯỚC 4: TRIỂN KHAI CHẠY 24/7 BẰNG SYSTEMD (KHUYÊN DÙNG)

Sử dụng `systemd` là giải pháp tiêu chuẩn của các hệ thống tài chính chuyên nghiệp: tự khởi động cùng VPS, tự hồi sinh khi gặp sự cố, ghi log chi tiết.

### 6.1. Cài đặt môi trường ảo Python
```bash
cd /root/bottradecrypto
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 6.2. Kích hoạt Jarvis Service
```bash
# Copy file cấu hình service vào hệ thống Linux
sudo cp deploy/jarvis.service /etc/systemd/system/jarvis.service

# Tải lại cấu hình systemd
sudo systemctl daemon-reload

# Kích hoạt để bot tự động chạy khi bật VPS
sudo systemctl enable jarvis

# Khởi động bot ngay lập tức
sudo systemctl start jarvis
```

### 6.3. Kiểm tra trạng thái và xem nhật ký (Logs)
```bash
# Xem trạng thái đang chạy
sudo systemctl status jarvis

# Xem log thời gian thực (nhấn Ctrl + C để thoát xem log)
journalctl -u jarvis -f
```

---

## 7. CÁC LỆNH ĐIỀU HÀNH THÔNG MINH QUA TELEGRAM

Sau khi bot đã khởi động trên VPS, Ngài mở Telegram và nhắn tin với Bot:

| Nhu cầu của Ngài | Lệnh gõ hoặc bấm nút | Mô tả hoạt động của Jarvis |
| :--- | :--- | :--- |
| **Đo tốc độ VPS & Mạng** | `/ping` hoặc `📡 Ping & VPS Health` | Đo RTT Binance API, RTT Telegram, Uptime VPS, mức ngốn RAM & CPU |
| **Sức khỏe Ký Quỹ** | `/margin` hoặc `🏥 Sức Khỏe Ký Quỹ` | Xem Margin Ratio, Số dư khả dụng, Khoảng cách thanh lý từng coin |
| **Đóng 1 vị thế cụ thể** | `đóng sol` hoặc bấm `🛑 Đóng SOL` | Bán Market ngay lập tức, hủy sạch SL/TP chờ, báo cáo Realized PnL |
| **Đóng toàn bộ khẩn cấp** | `/closeall` hoặc bấm `🚨 ĐÓNG TOÀN BỘ` | Jarvis hỏi xác nhận 2 bước, sau đó thanh lý toàn bộ về 100% USDT |
| **Khóa lãi Kèo Bất Tử** | `be sol` hoặc bấm `🛡️ BE SOL` | Dời SL về Entry (+0.05% bù phí), triệt tiêu 100% rủi ro thua lỗ |
| **Bật/Tắt Ferrari Mode** | `ferrari` hoặc bấm `⚡ Bật/Tắt Ferrari` | Chuyển đổi giữa Chế độ Đua x35-x40 và Chế độ An toàn 20x |
| **Sao kê chi tiết PnL** | `/pnl` hoặc bấm `📈 Lãi Lỗ Chi Tiết` | Sao kê từng đồng coin đã chốt hôm nay và tổng hợp 7 ngày qua |
| **Quét kèo bằng Radar** | `/scan` hoặc bấm `🎯 Jarvis Radar` | Quét cấu trúc SMC, Phân kỳ RSI nến 1H trên toàn bộ các cặp coin |

---

## 8. LỊCH PHÁT SÓNG TỰ ĐỘNG 24/7 TRÊN VPS

Hệ thống daemon tích hợp sẵn Scheduler thời gian thực theo múi giờ Việt Nam (UTC+7):
* **08:00 AM MỖI SÁNG:** Bản tin tình báo mở phiên, tóm tắt nhịp thở Bitcoin đêm qua và điểm danh các coin tiềm năng nhất.
* **23:00 PM MỖI ĐÊM:** Báo cáo tăng trưởng ngày, tổng Realized PnL, Winrate và dự báo số ngày chạm mốc **$300 / $500 / $1000 USDT**.
* **CẢNH BÁO BIẾN ĐỘNG (FLASH ALERT):** Tự động phát loa đỏ cảnh báo nếu Bitcoin giật râu quét thanh khoản $\ge 1.8\%$ trong 5 phút.

---

## 9. HƯỚNG DẪN CẬP NHẬT KHI CÓ PHIÊN BẢN MỚI

Mỗi khi hệ thống có bản nâng cấp tính năng mới trên GitHub, Ngài chỉ cần gõ 2 lệnh trên VPS:

```bash
cd /root/bottradecrypto
git pull origin main
sudo systemctl restart jarvis
```
*Jarvis sẽ cập nhật mã nguồn mới và tiếp tục canh gác tài khoản mà không làm mất trạng thái lệnh!*

