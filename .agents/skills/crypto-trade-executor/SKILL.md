---
name: crypto-trade-executor
description: Specialized trading executor and risk guardian for cryptocurrency futures signals. Enforces zero-liquidation capital preservation, 35/35/30 profit scaling, risk-free breakeven execution, anti-hallucination signal validation, and real-time reconciliation with Binance.
---

# 🤖 CRYPTO TRADE EXECUTOR & ACCOUNT GROWTH SKILL

Kỹ năng chuyên biệt dành cho Antigravity Agent để thực thi, kiểm soát rủi ro, phân tích tín hiệu Telegram và tự động tối ưu hóa vị thế trên Binance USDT-M Futures.

---

## 1. KHI NÀO KÍCH HOẠT KỸ NĂNG NÀY (ACTIVATION TRIGGERS)

Kích hoạt kỹ năng này khi:
- Tiếp nhận, phân tích cú pháp hoặc thực thi tín hiệu giao dịch từ các kênh Telegram.
- Cần kiểm tra rủi ro, tính toán đòn bẩy an toàn (`safe_leverage`) và khối lượng vào lệnh (`margin_size`).
- Kiểm tra tính toàn vẹn của vị thế mở trên sàn Binance (Stop Loss, Take Profit, Breakeven).
- Đánh giá chất lượng kênh Telegram, bài trừ lãi ảo và xếp hạng kênh dựa trên kết quả giao dịch thực tế trên sàn.
- Xử lý sự cố lệch vị thế, lệch giá hoặc kiểm tra log của hệ thống đối soát (Reconciliation).

---

## 2. NGUYÊN TẮC CỐT LÕI (UNBREAKABLE DIRECTIVES)

### Điều 1: Đòn bẩy chuẩn 11x – 25x & Bảo toàn vốn tuyệt đối (Zero Liquidation)
- **Dải đòn bẩy chuẩn:** **11x – 25x** (Mặc định **20x**, trần tối đa **25x**).
- Tuyệt đối **KHÔNG BAO GIỜ** để giá thanh lý gần hơn mức Stop Loss.
- Khi Admin ghi dải (VD: `10x – 50x` hoặc `20x – 50x`), hệ thống chọn mức tối ưu **20x** (không tự ghìm ở 10x).
- Công thức đòn bẩy an toàn bắt buộc:
  $$\text{Safe Leverage} = \min\left(25, \left\lfloor \frac{0.75}{\text{Khoảng cách SL \%}} \right\rfloor\right)$$
- Nếu Admin yêu cầu đòn bẩy 50x nhưng khoảng cách SL là 4%, hệ thống **BẮT BUỘC** tự động hạ đòn bẩy xuống tối đa 18x để triệt tiêu 100% rủi ro bị thanh lý trước khi chạm SL. Khi SL ngắn $\le 3.7\%$, đi đủ **20x – 25x**.

### Điều 2: Tối ưu tỷ lệ R:R dương ($\ge 2.5 : 1$)
- **Cấm tuyệt đối:** Chốt non phần lớn vị thế ở TP1 và dời SL quá sớm khiến lệnh bị quét hòa vốn hoặc lãi vài xu trong khi chịu rủi ro lỗ nặng khi chạm SL.
- **Quy chuẩn tỷ lệ TP:**
  - **TP1 (35% Khối lượng):** Đút túi một phần lời và trả toàn bộ phí sàn.
  - **TP2 (35% Khối lượng):** Trọng tâm tạo dòng tiền dương lớn.
  - **TP3 (30% Khối lượng):** Moonbag gồng sóng dài mà không chịu rủi ro.

### Điều 3: Cơ chế "Kèo Bất Tử" (Smart Breakeven)
- Chỉ được dời SL về Entry khi thỏa mãn 2 điều kiện đồng thời:
  1. TP1 đã **khớp thực tế** (xác nhận qua lệnh FILLED hoặc giá thị trường đã vượt qua TP1 tối thiểu **+0.3%**).
  2. Giá hiện tại đang có lãi **$\ge +0.2\%$ so với giá Entry** (để tránh việc vừa gửi lệnh Stop Market là bị sàn khớp ngay lập tức theo giá thị trường do trượt giá/spread).

### Điều 4: Miễn nhiễm với dữ liệu lịch sử (Historical Isolation)
- Khi quét lại lịch sử tin nhắn hàng năm để xếp hạng kênh, tất cả tín hiệu lịch sử **PHẢI** mang trạng thái `CLOSED` hoặc lưu vào bảng riêng.
- Vòng lặp đối soát (Reconciliation) chỉ được theo dõi các tín hiệu sinh ra từ lệnh thực tế có ID trong bảng `orders`.

---

## 3. QUY TRÌNH THỰC THI CHUẨN (STANDARD OPERATING PROCEDURE)

```
[Nhận Tin Nhắn Telegram]
          │
          ▼
[1. Sàng Lọc Kênh & Trừ Khử Lãi Ảo]
   ├── Kênh thuộc Blacklist? -> HỦY NGAY
   └── Kênh hợp lệ? -> Chuyển sang Bước 2
          │
          ▼
[2. Đối Chiếu Thị Trường Binance Thực Tế]
   ├── Cặp coin có trên Binance USDT-M Futures không?
   └── Giá thị trường hiện tại có lệch > 2.0% so với Entry đề xuất không?
          │
          ▼
[3. Tính Toán Khối Lượng & Đòn Bẩy (Risk Engine - Phân Hạng Vốn Đa Tầng)]
   ├── Kênh Tinh Hoa (Top 5 Elite): Margin 5.0% (~$4.15 - $5.00 USDT, multiplier: 1.0)
   ├── Kênh Siêu Scalp / Phụ (13 Channels): Margin 2.5% (~$2.07 - $2.50 USDT, multiplier: 0.5)
   ├── Safe Leverage: Khóa chặt theo khoảng cách SL (Zero Liquidation)
   └── Giới hạn tối đa 4 lệnh mở đồng thời (Max Open Risk <= 12.0%)
          │
          ▼
[4. Đặt Lệnh Thực Thi Kép]
   ├── Gửi Lệnh Entry (Limit hoặc Market)
   └── Khi Entry Khớp:
         ├── Đặt SL khẩn cấp bằng STOP_MARKET Algo Order (Bảo vệ 100% Vol)
         ├── Đặt TP1 (35% Vol) Limit Order
         ├── Đặt TP2 (35% Vol) Limit Order
         └── Đặt TP3 (30% Vol) Limit Order
          │
          ▼
[5. Vòng Lặp Giám Sát & Quản Trị Vị Thế (Reconciliation)]
   ├── Kiểm tra mỗi 10 giây
   ├── Nếu TP1 khớp -> Kích hoạt Kèo Bất Tử (Dời SL về Entry + 0.05%)
   └── Nếu phát hiện thiếu SL -> Tự động đặt lại SL bảo vệ ngay lập tức
```

---

## 4. BẢNG PHÂN LOẠI & QUY TẮC BẮT KÈO THEO KÊNH

| Kênh Telegram | Chat ID | Phân Hạng | Margin Mục Tiêu | Multiplier | Chiến Thuật Áp Dụng |
|:---|:---:|:---:|:---:|:---:|:---|
| **THE WOLF (CRYPTO)®** | `-1002007658025` | **Tier S** | **5.0% Vốn** | **1.0x** | Kèo chủ lực, R:R dương (1.24), giữ trọn TP1 (35%), TP2, TP3. |
| **Boom_Boom_Billionaires** | `-1001756316676` | **Tier S** | **5.0% Vốn** | **1.0x** | Winrate 75%, dời Breakeven Kèo Bất Tử siêu tốc. |
| **CRYPTO LEOPARD'S** | `-1002052872813` | **Tier S** | **5.0% Vốn** | **1.0x** | Winrate 79.5%, vào vùng giá BELOW cực tốt. |
| **CRYPTO MONK** | `-1001552004524` | **Tier A** | **3.5% - 5.0% Vốn** | **1.0x** | Kèo Scalp nhanh, chọn lọc kỹ. |
| **Crypto Neon** | `-1001370457350` | **Tier A** | **3.5% - 5.0% Vốn** | **1.0x** | Kỷ luật thép, đòn bẩy khống chế an toàn 10x - 20x. |
| **Các kênh cũ ngoài Top 5 / Khoe Lãi Ảo / Không SL** | *Tất cả các ID khác* | **Blacklist** | **0% (Hủy)** | **0.0x** | **XÓA SẠCH DỮ LIỆU & CHẶN HOÀN TOÀN.** |

---

## 5. CHECKLIST KIỂM TRA ĐỊNH KỲ DÀNH CHO AGENT

Mỗi khi agent được yêu cầu "check lại lệnh", "đánh giá tài khoản" hoặc "sửa lỗi", agent **PHẢI** thực hiện theo checklist sau:

- [ ] **1. Kiểm tra Vị thế Thực trên Binance:** Gọi `/fapi/v1/positionRisk` để lấy danh sách coin đang mở, giá vào và đòn bẩy.
- [ ] **2. Kiểm tra SL Thực tế trên Binance:** Gọi `/fapi/v1/openAlgoOrders` và kiểm tra trường `quantity`. Xác nhận tổng khối lượng SL $\ge$ khối lượng vị thế.
- [ ] **3. Kiểm tra DB Trạng thái Tín hiệu:** Đảm bảo không có hàng nghìn tín hiệu `VALIDATED` mồ côi. Số lượng tín hiệu hoạt động chỉ được bằng đúng số vị thế thật.
- [ ] **4. Đối chiếu Lãi/Lỗ Thực tế:** Đọc dữ liệu từ `/fapi/v1/income` (Realized PnL, Funding Fee, Commission). Tuyệt đối không phán đoán dựa trên cảm tính.
- [ ] **5. Đánh giá R:R Các Lệnh Đã Đóng:** Đảm bảo trung bình các lệnh thắng bù đắp được tối thiểu 2 lần các lệnh thua. Nếu thấy tỷ lệ thắng cao mà tài khoản giảm tiền, phải lập tức kiểm tra lại khối lượng chốt TP1 và khoảng cách dời Breakeven!

