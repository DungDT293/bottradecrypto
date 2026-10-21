# DANH SÁCH CHÍNH SÁCH VÀ QUY TẮC XỬ LÝ (POLICY SPECIFICATIONS v1.3.1)

Hệ thống tuân thủ nguyên tắc cốt lõi: **Không tự đoán, không tự tiện sửa số, không giả định dữ liệu mơ hồ, triệt tiêu rủi ro thanh lý (Zero Liquidation)**.

---

## 1. PHÂN LOẠI NGUỒN CỦA CÁC GIÁ TRỊ (FIELD SOURCE TRACKING)

Mọi trường dữ liệu của tín hiệu khi bóc tách phải có nguồn gốc xác thực rõ ràng:
- `EXPLICIT_SIGNAL`: Dữ liệu được ghi rõ ràng, không mơ hồ trong tin nhắn gốc của Admin.
- `SOURCE_POLICY`: Chính sách được người dùng phê duyệt riêng cho kênh/nguồn đó trong `source_registry.py` hoặc `config.yaml`.
- `GLOBAL_POLICY`: Chính sách mặc định toàn hệ thống trong `config.yaml` / `policy_defaults.py`.
- `UNRESOLVED`: Không có trong tin và chưa có chính sách nào được duyệt $\rightarrow$ Chuyển trạng thái `NEEDS_POLICY` hoặc `NEEDS_REVIEW`.

---

## 2. CHÍNH SÁCH VÙNG ENTRY (RANGE ENTRY POLICY)

Khi tín hiệu cung cấp một vùng giá Entry (ví dụ: `Short BELOW (0.2125)(0.2150)` hoặc `Entry: 0.8960 - 0.9160`):
- `BEST_PRICE` (Mặc định & Khuyến nghị): Đặt 1 lệnh limit ở mức giá tối ưu nhất cho vị thế:
  - Lệnh **LONG**: Đặt ở đáy vùng giá (giá thấp nhất).
  - Lệnh **SHORT**: Đặt ở đỉnh vùng giá (giá cao nhất).
  - Giúp tối ưu hóa tỷ lệ Risk/Reward (R:R) và mức giá khớp lệnh đẹp nhất.
- `MID_POINT`: Đặt 1 lệnh limit ở mức giá trung bình `(min + max) / 2`.
- `SPLIT_2_LIMITS`: Chia đều 50/50 khối lượng thành 2 lệnh limit ở 2 đầu của vùng giá.
- **Bảo vệ chống rượt giá (Price Chase Protection):** Nếu thị giá hiện tại đã chạy trượt qua vùng Entry $> 1.0\%$ theo hướng bất lợi, hệ thống tự động từ chối (`REJECTED`) để tránh đu đỉnh/đu đáy.

---

## 3. CHÍNH SÁCH CHỐT LỜI ĐA TẦNG (MULTI-TP ALLOCATION & GEOMETRIC DECAY)

Khi tín hiệu có nhiều mốc chốt lời Take Profit:
- **Chế độ mặc định (`CUSTOM_TP1_RATIO`):**
  - **Mức TP1 (Chủ lực):** Luôn khóa cố định **35% khối lượng vị thế**. Ngay khi khớp TP1, bot tự động kích hoạt **Kèo Bất Tử** (dời Stop Loss về `Entry + 0.05%` để bảo vệ tài khoản).
  - **Phần còn lại (65%):** Được phân bổ giảm dần theo luật hàm mũ (Geometric Decay Factor = 0.6) cho các mốc TP tiếp theo:
    - **Kèo 2 TP:** TP1: 35% | TP2: 65%
    - **Kèo 3 TP:** TP1: 35% | TP2: 35% | TP3: 30%
    - **Kèo 4 TP:** TP1: 35.0% | TP2: 33.2% | TP3: 19.9% | TP4: 11.9%
    - **Kèo 5 TP:** TP1: 35.0% | TP2: 29.9% | TP3: 17.9% | TP4: 10.8% | TP5: 6.4%
    - **Kèo 6 TP:** TP1: 35.0% | TP2: 28.2% | TP3: 16.9% | TP4: 10.1% | TP5: 6.1% | TP6: 3.7%
- **Cơ chế chống tồn dư coin lẻ (Anti-Dust Protection):**
  - Trước khi gửi lệnh Limit TP lên Binance, bot đối chiếu từng mốc với bộ lọc `LOT_SIZE` (minQty) và `MIN_NOTIONAL` của sàn.
  - Nếu mốc TP cuối cùng có khối lượng quá nhỏ không đủ điều kiện sàn, bot tự động gộp khối lượng đó vào mốc TP liền kề trước đó.

---

## 4. CHÍNH SÁCH DỜI HÒA VỐN TỨC THÌ (KÈO BẤT TỬ - SMART BREAKEVEN)

- **Thời điểm kích hoạt:** Ngay khi nhận được sự kiện lệnh **TP1 FILLED** trên sàn Binance (hoặc thông qua luồng đối soát trạng thái định kỳ).
- **Quy tắc dời:**
  1. Hủy lệnh Stop Loss cũ ở mức giá ban đầu.
  2. Gửi lệnh `STOP_MARKET` mới với `reduceOnly=true` tại mức giá:
     $$\text{Breakeven Price} = \text{Entry} \pm (\text{Entry} \times 0.05\%)$$
     *(Dương cho lệnh Long, Âm cho lệnh Short để bù đắp toàn bộ phí taker 2 chiều).*
  3. Sau khi lệnh SL mới được xác nhận trên server Binance, vị thế chính thức trở thành **Kèo Bất Tử** (Risk = 0, đảm bảo có lãi ròng).

---

## 5. CHÍNH SÁCH KẸP ĐÒN BẨY AN TOÀN (SAFE LEVERAGE LIQUIDATION CLAMP)

- **Trần đòn bẩy tối đa:** **25x**.
- **Công thức kẹp đòn bẩy chống cháy:**
  $$\text{Safe Leverage} = \min\left(25, \left\lfloor \frac{0.75}{\text{Khoảng cách SL \%}} \right\rfloor\right)$$
- **Mục đích:** Đảm bảo mức giá thanh lý (Liquidation Price) luôn luôn nằm xa hơn mức Stop Loss ít nhất **25% biên độ an toàn**.
  - Ví dụ: Kèo có SL cách 6.6% $\rightarrow$ Bot tự động hạ đòn bẩy xuống tối đa **11x**. Tuyệt đối không cho phép dùng 25x-50x để tránh bị sàn thanh lý cưỡng bức trước khi chạm SL.
  - Khi kèo có SL ngắn (1.5% - 3.0%) $\rightarrow$ Bot đi trọn vẹn **20x - 25x**.

---

## 6. DANH SÁCH 5 NHÓM TINH HOA ĐƯỢC CẤP PHÉP (TOP 5 ELITE WHITELIST)

Hệ thống chỉ tiếp nhận và xử lý tín hiệu từ 5 kênh có tỷ lệ thắng và kỷ luật cao nhất:
1. **THE WOLF (CRYPTO)®** (`-1002007658025`)
2. **Boom_Boom_Billionaires** (`-1001756316676`)
3. **CRYPTO LEOPARD'S** (`-1002052872813`)
4. **CRYPTO MONK** (`-1001552004524`)
5. **Crypto Neon** (`-1001370457350`)

Toàn bộ các kênh ngoài danh sách trên đều bị cô lập và từ chối xử lý ở mọi tầng hệ thống.
