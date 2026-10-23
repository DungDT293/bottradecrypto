# HƯỚNG DẪN THƯƠNG MẠI HÓA & PHÁT HÀNH TRỰC TIẾP (COMMERCIAL RELEASE v1.3.3)

Tài liệu này hướng dẫn mô hình thương mại hóa trực tiếp không cần server quản lý bản quyền: **Phân phối bộ cài độc lập — Người dùng tự kết nối Telegram & Binance — 1-Click Tham Gia 5 Nhóm Tinh Hoa — Tự Động Giao Dịch 24/7**.

---

## 1. MÔ HÌNH THƯƠNG MẠI TRỰC TIẾP (ZERO SERVER REQUIREMENT)

Khách hàng chỉ cần tải file cài đặt `.exe`, không cần liên hệ xin cấp key bản quyền hay kích hoạt phức tạp:

```mermaid
flowchart TD
    User["Khách Hàng Tải App (.exe)"] --> Step1["1. Đăng nhập Telegram cá nhân (SĐT + OTP)"]
    Step1 --> Step2["2. Bấm 'Tham Gia Nhanh 5 Kênh Tinh Hoa' (1-Click Auto-Join)"]
    Step2 --> Step3["3. Nhập API Key & Secret Binance (Quyền Futures)"]
    Step3 --> Step4["4. Bật công tắc 'Giao dịch Live'"]
    Step4 --> AutoTrade["5. Bot tự săn lệnh, tự chốt lời, tự dời Breakeven hòa vốn 24/7"]
```

---

## 2. TRẢI NGHIỆM NGƯỜI DÙNG: CỰC KỲ ĐƠN GIẢN

### Bước 1: Đăng nhập Telegram & Tự Động Join 5 Kênh Tinh Hoa
- Người dùng mở tab **Kết nối (Connections)** -> Nhập Số điện thoại Telegram -> Nhập mã OTP.
- Ngay sau khi kết nối, tại giao diện xuất hiện thẻ tính năng:
  `⚡ Tham Gia Nhanh 5 Kênh Tinh Hoa (1-Click Auto-Join)`.
- Người dùng chỉ cần bấm nút **"Tham Gia 5 Kênh Ngay"**:
  - Bot dùng tài khoản Telegram của họ tự động tham gia cả 5 kênh:
    1. **THE WOLF (CRYPTO)®** (`-1002007658025`)
    2. **Boom_Boom_Billionaires** (`-1001756316676`)
    3. **CRYPTO LEOPARD'S** (`-1002052872813`)
    4. **CRYPTO MONK** (`-1001552004524`)
    5. **Crypto Neon** (`-1001370457350`)
  - Đồng thời tự động kích hoạt whitelist giám sát tín hiệu cho 5 kênh này. Người dùng không phải tìm link hay bấm vào từng kênh.

### 1.1. Cơ Chế Chống FloodWait / Khóa Tài Khoản & Cấu Hình Link Từ Xa (Remote Dynamic JSON)
1. **Độ trễ ngẫu nhiên an toàn (`8 - 15 giây`):**
   - Giữa mỗi lần join từng kênh mới, bot tự động chèn độ trễ ngẫu nhiên `asyncio.sleep(random.uniform(8.0, 15.0))` nhằm mô phỏng hành vi người thật, bảo vệ tuyệt đối tài khoản Telegram của người dùng khỏi các bộ lọc spam tự động của Telegram MTProto (`FloodWaitError`, `PEER_FLOOD`).
2. **Thanh tiến trình thời gian thực (Real-time Progress Bar):**
   - Trên giao diện Connections và Groups hiển thị Progress Bar động:
     `"Đang tham gia kênh 1/5 (THE WOLF)... vui lòng chờ 12s để bảo vệ tài khoản Telegram"`.
   - Giúp người dùng nắm rõ tiến độ, an tâm chờ đợi mà không bấm lại liên tục.
3. **Cấu hình link từ xa chống đứt gãy link Private (Remote Dynamic JSON):**
   - Toàn bộ danh sách kênh và link mời được lưu tại `config/elite_channels.json` và hỗ trợ nạp động từ xa qua GitHub Gist / GitHub Raw / Cloudflare Pages (thông qua trường `remote_channels_url` trong `config.yaml` hoặc biến môi trường `TELEGRAM_REMOTE_CHANNELS_URL`).
   - Bot tự động ưu tiên fetch link mới nhất từ Cloud $\rightarrow$ Lưu cache cục bộ `data/remote_elite_channels_cache.json` $\rightarrow$ Tự động fallback về file nội bộ nếu offline.
   - **Lợi ích thực chiến:** Khi admin các nhóm Telegram đổi link private mới, người vận hành chỉ cần cập nhật file JSON trên Cloud, toàn bộ app người dùng khắp nơi sẽ tự động lấy link mới nhất mà **không cần build lại file `.exe`**.

### Bước 2: Nhập API Binance & Bật Live Trading
- Người dùng nhập `API Key` & `Secret Key` tài khoản Binance của họ (Chỉ cần cấp quyền Futures Trading, không cho rút tiền).
- Bật công tắc **Giao dịch Live**.
- Bot tự động:
  - Khống chế đòn bẩy an toàn với cơ chế `Safe Leverage Clamp` ($\min(25, \lfloor 0.75 / \text{SL dist} \rfloor)$).
  - Quản lý vốn rủi ro nghiêm ngặt dưới 2% equity.
  - Phân bổ chốt lời 3 mốc 35% / 35% / 30%.
  - Tự động kéo Stop Loss về **Entry + 0.05%** (Breakeven) ngay khi khớp TP1 để triệt tiêu 100% rủi ro thị trường đảo chiều.

---

## 3. FILE CÀI ĐẶT WINDOWS NSIS SETUP ĐÃ XUẤT XƯỞNG

File cài đặt Windows chuẩn thương mại đã sẵn sàng để gửi cho khách hàng:

- **Đường dẫn file cài đặt:**
  `telegram-binance-signal-executor_1.3.3_x64-setup.exe` (hoặc `desktop/src-tauri/target/release/bundle/nsis/telegram-binance-signal-executor_1.3.3_x64-setup.exe`)
- **Dung lượng:** `101.1 MB`
- **Tương thích:** Windows 10, Windows 11 (64-bit).
- **Cài đặt:** Khách hàng chỉ cần tải file `.exe`, nhấp đúp và nhấn `Next -> Install -> Finish` là ứng dụng tự khởi động cùng khay hệ thống (System Tray).
