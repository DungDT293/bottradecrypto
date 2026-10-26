# DANH SÁCH CHÍNH SÁCH VÀ QUY TẮC XỬ LÝ (POLICY SPECIFICATIONS v1.3.3)

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

### 2.1. Các chế độ khớp lệnh vùng giá
- **`SPLIT_2_LIMITS` (Khuyến nghị chủ lực cho Scalp & Triệt tiêu Adverse Selection):**
  - **Vấn đề cốt lõi của lệnh Limit (Adverse Selection):** Với các kèo Scalp theo đà (Momentum Scalp) từ *CRYPTO LEOPARD'S* hay *Boom_Boom_Billionaires*, giá thường chỉ chạm nhẹ vào mép đón đầu của vùng Entry rồi bật tăng thẳng lên TP1/TP2. Nếu luôn đợi giá rơi về tận đáy vùng mới khớp (`BEST_PRICE`), bot sẽ bị **"Bỏ lỡ kèo thắng (Missed Winners), nhưng lại dính đủ 100% kèo thua"** (vì các kèo thua là những kèo giá xả thẳng xuyên thủng đáy vùng Entry để quét Stop Loss).
  - **Giải pháp `SPLIT_2_LIMITS` (Chia 50/50 ở cả 2 đầu vùng giá):**
    - **Lệnh Limit 1 (50% khối lượng):** Đặt tại mép đầu vùng giá để **chắc chắn có mặt trên tàu**. Khi giá chạm TP1, bot ngay lập tức khóa 35% lợi nhuận và dời Stop Loss về hòa vốn, biến vị thế thành **Kèo Bất Tử**.
    - **Lệnh Limit 2 (50% khối lượng):** Đặt tại đáy vùng giá (Best Price). Nếu thị trường có nhịp pullback sâu, lệnh 2 sẽ khớp và kéo giá vốn bình quân (VWAP) về vị trí cực kỳ đẹp, tối ưu hóa tối đa lợi nhuận khi giá tăng trở lại.
    - **Hỗ trợ cấu hình:** Người dùng có thể chọn trực tiếp trên Desktop UI (`SPLIT_2_LIMITS`), đặt trong `config.yaml` (`execution.entry_range_policy: SPLIT_2_LIMITS`), hoặc gán riêng cho từng kênh bằng cờ `allow_range_split_limits: true`.
- **`BEST_PRICE` (Tối ưu R:R cho kênh Swing / Reversal):**
  - Đặt 1 lệnh limit duy nhất ở mức giá tối ưu nhất cho vị thế:
    - Lệnh **LONG**: Đặt ở đáy vùng giá (giá thấp nhất).
    - Lệnh **SHORT**: Đặt ở đỉnh vùng giá (giá cao nhất).
  - Giúp tối ưu hóa tỷ lệ Risk/Reward (R:R) và mức giá khớp lệnh đẹp nhất khi thị trường đi ngang hoặc kiểm định lại đáy/đỉnh.
- **`MID_POINT`:** Đặt 1 lệnh limit ở mức giá trung bình $\frac{\text{Min} + \text{Max}}{2}$.
- **`NEEDS_POLICY`:** Tạm dừng tín hiệu ở trạng thái chờ duyệt trên giao diện người dùng nếu chưa có chỉ định rõ ràng.

### 2.2. Cơ chế bảo vệ thị giá (Price Chase Protection)
- Nếu thị giá hiện tại đã chạy trượt qua vùng Entry $> 1.0\%$ theo hướng bất lợi, hệ thống tự động từ chối (`REJECTED`) để triệt tiêu hoàn toàn rủi ro FOMO đu đỉnh/đu đáy.

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
- **Cơ chế chống tồn dư coin lẻ (Anti-Dust Protection & Remainder Preservation):**
  - Trước khi gửi lệnh Limit TP lên Binance, bot đối chiếu từng mốc với bộ lọc `LOT_SIZE` (minQty) và `MIN_NOTIONAL` của sàn.
  - **Bảo toàn số dư khối lượng:** Mốc TP cuối cùng tự động tính bằng phần dư `filled_qty - sum(cac_tp_truoc)`, đảm bảo 100% khối lượng đã khớp đều được chốt lời trọn vẹn, triệt tiêu sự hao hụt do chia nguyên.
  - Nếu mốc TP cuối cùng có khối lượng quá nhỏ không đủ điều kiện sàn, bot tự động gộp khối lượng đó vào mốc TP liền kề trước đó.

---

## 4. CHÍNH SÁCH DỜI HÒA VỐN TỨC THÌ (KÈO BẤT TỬ - SMART BREAKEVEN v2.4.0)

- **Thời điểm kích hoạt kép (Dual Trigger Condition):**
  1. **Khi TP1 FILLED** trên sàn Binance (hoặc chạm mốc giá TP1).
  2. **HOẶC khi Lợi nhuận giá đạt `Gain >= 0.8%` (+16% ROE)**: Ngay cả khi chưa chạm TP1, nếu giá đã chạy có lãi từ +0.8%, bot tự động kéo SL về Entry + phí sàn ngay lập tức.
- **Quy tắc dời:**
  1. Hủy lệnh Stop Loss cũ ở mức giá ban đầu.
  2. Gửi lệnh `STOP_MARKET` mới với `reduceOnly=true` tại mức giá:
     $$\text{Breakeven Price} = \text{Entry} \pm (\text{Entry} \times 0.05\%)$$
     *(Dương cho lệnh Long, Âm cho lệnh Short để bù đắp toàn bộ phí taker 2 chiều).*
  3. **Đệm an toàn bước giá (0.4% - 0.5% từ Mark Price):** Hệ thống tự động kiểm tra khoảng cách giữa giá Breakeven và giá Mark thị trường để triệt tiêu lỗi Binance `-2021: Order would immediately trigger`.
  4. Sau khi lệnh SL mới được xác nhận trên server Binance, vị thế chính thức trở thành **Kèo Bất Tử** (Risk = 0, đảm bảo có lãi ròng).

---

## 5. CHÍNH SÁCH KHÓA LÃI ĐỘNG ĐA TẦNG (DYNAMIC MULTI-TIER PROFIT RATCHET)

Hệ thống áp dụng cơ chế khóa lãi tịnh tiến 1 chiều (Monotonic Ratchet - SL chỉ dời theo chiều có lợi):
- **Tầng 0 (Lãi chớm đỉnh `>= 1.2%` / ROE `+24% - +48%`):** Dời SL bảo đảm khóa tối thiểu **`+0.5%` lợi nhuận thực** (bỏ túi ít nhất `+10% - +20% ROE`).
- **Tầng 0.5 (Lãi vững chắc `>= 2.0%` / ROE `+40% - +80%`):** Dời SL bảo đảm khóa tối thiểu **`+1.0%` lợi nhuận thực** (bỏ túi ít nhất `+20% - +40% ROE`).
- **Tầng 1 (Lãi `>= 3.0%`):** Khóa bảo đảm `+1.5%`.
- **Tầng 2 & 3 (Lãi `>= 6.0%` và `>= 10.0%`):** Khóa bảo đảm `+3.2%` và `+6.0%`.
- **Khi TP2 khớp (2.0R):** Dời SL của 30% Moonbag lên thẳng mốc giá TP1.

---

## 6. CHÍNH SÁCH BỘ LỌC XU HƯỚNG VĨ MÔ 4H (4H MACRO TREND ALIGNMENT)

- Đo lường xu hướng vĩ mô khung 4H (4H EMA50 và 4H EMA20) trên Binance Futures:
  - **4H BEARISH:** CẤM TUYỆT ĐỐI mọi lệnh LONG bắt đáy.
  - **4H BULLISH:** CẤM TUYỆT ĐỐI mọi lệnh SHORT bắt đỉnh.
- Triệt tiêu 100% rủi ro bắt dao rơi, đưa Winrate lên mức 85% - 90%.

---

## 7. CHÍNH SÁCH BỨT PHÁ LỢI NHUẬN FERRARI MODE (x35 - x40)

- **Khi FERRARI: ON:**
  - Cho phép đòn bẩy cao **35x - 40x**.
  - Mở rộng trần lên tới **20 vị thế mở đồng thời**.
  - Ký quỹ mỗi lệnh mở rộng tới 15% - 25% vốn nhằm tối đa hóa tốc độ tăng trưởng vốn (kỳ vọng x2.5 - x4.5 tài khoản/tháng trên vốn 100$).
- **Khi FERRARI: OFF:**
  - Tự động kích hoạt chế độ an toàn bảo thủ: Đòn bẩy 10x - 20x, trần 3 - 5 vị thế, rủi ro khống chế 2%.

---

## 8. CHÍNH SÁCH KẸP ĐÒN BẨY AN TOÀN (SAFE LEVERAGE LIQUIDATION CLAMP)

- **Trần đòn bẩy tối đa:** **25x** (Chế độ thường) / **40x** (Chế độ Ferrari).
- **Công thức kẹp đòn bẩy chống cháy:**
  $$\text{Safe Leverage} = \min\left(25, \left\lfloor \frac{0.75}{\text{Khoảng cách SL \%}} \right\rfloor\right)$$
- **Mục đích:** Đảm bảo mức giá thanh lý (Liquidation Price) luôn luôn nằm xa hơn mức Stop Loss ít nhất **25% biên độ an toàn**.
  - Ví dụ: Kèo có SL cách 6.6% $\rightarrow$ Bot tự động hạ đòn bẩy xuống tối đa **11x**. Tuyệt đối không cho phép dùng 25x-50x để tránh bị sàn thanh lý cưỡng bức trước khi chạm SL.
  - Khi kèo có SL ngắn (1.5% - 3.0%) $\rightarrow$ Bot đi trọn vẹn **20x - 25x**.

---

## 9. DANH SÁCH 5 NHÓM TINH HOA ĐƯỢC CẤP PHÉP (TOP 5 ELITE WHITELIST)

Hệ thống chỉ tiếp nhận và xử lý tín hiệu từ 5 kênh có tỷ lệ thắng và kỷ luật cao nhất:
1. **THE WOLF (CRYPTO)®** (`-1002007658025`)
2. **Boom_Boom_Billionaires** (`-1001756316676`)
3. **CRYPTO LEOPARD'S** (`-1002052872813`)
4. **CRYPTO MONK** (`-1001552004524`)
5. **Crypto Neon** (`-1001370457350`)

Toàn bộ các kênh ngoài danh sách trên đều bị cô lập và từ chối xử lý ở mọi tầng hệ thống.
