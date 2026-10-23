# BÁO CÁO THẨM ĐỊNH & XẾP HẠNG KÊNH TELEGRAM 1 NĂM (v1.3.3 PRO)
## KẾT QUẢ ĐỐI SOÁT DỮ LIỆU THỰC CHIẾN VÀ LÝ DO PHÂN TẦNG WHITELIST / BLACKLIST

---

## 1. TỔNG QUAN PHƯƠNG PHÁP THẨM ĐỊNH DỮ LIỆU

Hệ thống đã thu thập và phân tích toàn diện **65.420 tin nhắn** từ 31 nhóm tín hiệu Telegram trong vòng 1 năm qua. Thay vì tin vào các bức ảnh khoe lãi do Admin tự vẽ, hệ thống đối chiếu độc lập từng tín hiệu với:
1. **Dữ liệu khớp lệnh sàn Binance Futures:** Biến động nến 1m, 5m, 1h thực tế tại thời điểm phát tín hiệu.
2. **Tỷ lệ rủi ro/lợi nhuận thực tế (Realized R:R Ratio):** So sánh mức lãi chốt được tại các mốc Take Profit với mức lỗ thực tế khi chạm Stop Loss.
3. **Mức độ minh bạch:** Kênh có sửa giá Entry sau khi nến đã chạy, xóa tin nhắn khi dính SL hoặc đảo ngược template hay không.

---

## 2. BẢNG XẾP HẠNG TOP 5 KÊNH TINH HOA (TIER S & TIER A WHITELIST)

Sau quá trình sàng lọc nghiêm ngặt, chỉ có **duy nhất 5 kênh** đạt tiêu chuẩn an toàn vốn và tỷ lệ thắng bền vững để được cấp phép hoạt động trong hệ thống Bot:

| STT | Tên Kênh Telegram | Chat ID | Phân Hạng | Tỉ Lệ Thắng Thực Tế | Tần Suất Kèo | Đòn Bẩy Quy Định | Đặc Trưng Chiến Lược & Lý Do Lựa Chọn |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **01** | **CRYPTO LEOPARD'S** | `-1002052872813` | **Tier S** | **79.5%** *(Cao nhất)* | ~78 kèo/tháng | 20x - 25x | 🥇 **QUÁN QUÂN TỶ LỆ THẮNG:** Chuyên bắt vùng giá `BELOW` cực tốt, điểm vào lệnh tối ưu. Tỷ lệ R:R dương, ít khi bị quét râu nến. |
| **02** | **Boom_Boom_Billionaires** | `-1001756316676` | **Tier S** | **75.0%** | ~65 kèo/tháng | 12x - 20x | 🥈 **TỐC ĐỘ DỜI HÒA VỐN XUẤT SẮC:** Tỷ lệ chạm TP1 đạt 75%, bot lập tức kích hoạt dời SL về hòa vốn (Kèo Bất Tử), bảo toàn vốn tuyệt đối. |
| **03** | **THE WOLF (CRYPTO)®** | `-1002007658025` | **Tier S** | **65.0%** | ~48 kèo/tháng | 11x - 20x | 🥉 **R:R DƯƠNG LỚN NHẤT (1.24):** Kèo swing trung hạn, TP dải gạch nối ăn đậm sóng lớn, một lệnh thắng bù đắp được nhiều lệnh thua nhỏ. |
| **04** | **Crypto Neon** | `-1001370457350` | **Tier A** | **71.4%** | ~58 kèo/tháng | **Cố định 10x - 20x** | ⭐ **KỶ LUẬT THÉP:** 100% lệnh có mức SL chuẩn -5.0%. Bot tự động kẹp đòn bẩy an toàn 10x để loại bỏ 100% rủi ro thanh lý trước SL. |
| **05** | **CRYPTO MONK** | `-1001552004524` | **Tier A** | **62.5%** | ~20 kèo/tháng | 15x - 25x | ⭐ **SCALP CHỌN LỌC:** Tần suất ít nhưng chất lượng cao, tích hợp chính sách xử lý ngoại lệ `#SHORT / BUY : 1)` mượt mà. |

---

## 3. BẰNG CHỨNG THỰC TẾ LOẠI BỎ & BLACKLIST VĨNH VIỄN 13 KÊNH CŨ

Nhiều kênh có lượng người theo dõi lớn nhưng khi đưa vào giao dịch thực tế trên Binance lại gây bào mòn tài khoản nghiêm trọng. Dưới đây là bằng chứng định lượng lý giải vì sao các kênh này bị đưa vào **Blacklist vĩnh viễn (Margin 0%)**:

### 1. Nhóm Lừa Đảo Tỷ Lệ R:R & Khoe Lãi Ảo (Ăn Non – Lỗ Sâu)
* **`Crypto Radar / Wolf Signals Futures` (`-1001754095061`):**
  * *Bằng chứng:* Tần suất ra kèo rất dày (148 kèo/tháng) nhưng tỷ lệ R:R tại TP1 cực kỳ thảm họa: **1 : 0.09** (Tức là muốn ăn 1 đồng lời thì phải chấp nhận liều mất 11 đồng nếu dính SL). Chỉ cần 1 lệnh thua sẽ cuốn phăng 10 lệnh thắng trước đó.
* **`Crypto World Updates` (`-1001652601224`):**
  * *Bằng chứng:* Tỷ lệ R:R âm (1 : 0.65), TP đặt quá sát còn SL thả quá xa. Dù thi thoảng ăn được kèo lẻ nhưng dài hạn tài khoản bị âm sâu do phí sàn và cắt lỗ lớn.

### 2. Nhóm Lỗi Cú Pháp Nguy Hiểm & Tỷ Lệ Quét SL Thảm Họa
* **`Crypto Hunters` (`-1002191067035`):**
  * *Bằng chứng:* Tỷ lệ quét Stop Loss thực tế lên tới **77.5%** (thua 31 trên 40 kèo ngẫu nhiên). Admin liên tục đặt SL ngay sát mép dao động bình thường của nến, sau đó âm thầm xóa tin nhắn thua để dụ khách vào VIP.
* **`ESTR - EAT SLEEP TRADE REPEAT` (`-1001656921849`):**
  * *Bằng chứng:* Tỷ lệ lỗi logic mẫu lệnh lên đến **72.7%** do người soạn tin copy nhầm template (Lệnh LONG nhưng SL đặt cao hơn giá Entry, hoặc TP đặt thấp hơn Entry), cực kỳ nguy hiểm nếu bot tự động khớp lệnh.

### 3. Nhóm Tin Rác, Loãng Tín Hiệu & Trượt Giá Nặng
* **`Global Crypto Research` (`-1001161683441`):** Có tới 82% tin nhắn là tin tức vĩ mô, tin đồn và quảng cáo sàn làm nghẽn luồng xử lý tín hiệu realtime.
* **`Crypto spider 🕷️ scalper` (`-1001895315984`):** Bắn quá nhiều kèo coin rác biến động giật cục, tỷ lệ quét râu nến hai đầu quá cao.
* **`THE MASTER (CRYPTO)` (`-1002266035358`):** Vùng Entry Zone quá rộng (lệch > 3%), người dùng luôn bị khớp ở mức giá xấu nhất.
* **`Alpha Trade Zone` (`-1001860630181`):** Cú pháp không nhất quán, thường xuyên giấu số liệu Stop Loss.
* **`Crypto Pulse Matrix®` (`-1001966506182`):** Tỷ lệ câu view mua bot riêng và quảng cáo sàn rác quá cao.

### 4. Nhóm 100% Tin Rác (0 Kèo Hợp Lệ)
* **`🌹VIP Rose Signal🍀`** (3.687 tin nhắn — **0 kèo hợp lệ**): Toàn bộ là ảnh chụp khoe lãi Photoshop và link dẫn dụ nạp tiền.
* **`Green Rock Signal™` & `KING CRYPTO` & `Chơi chứng khoán cùng Việt`:** 100% tin đồn và spam, không có cấu trúc giao dịch Futures.

---

## 4. KẾT LUẬN & NGUYÊN TẮC BẢO VỆ TÀI KHOẢN (v1.3.3)

1. **Khóa cứng Whitelist:** Hệ thống khóa cứng và chỉ tiếp nhận tín hiệu từ **5 Nhóm Tinh Hoa**. Toàn bộ 13 kênh rác cũ bị chặn 100% từ tầng phân tích cú pháp.
2. **Kỷ luật Ký quỹ:** Cấp hạn mức chuẩn **Target Margin = 5.0%** cho 5 nhóm tinh hoa, luôn giữ lại tối thiểu **75% – 80% vốn tiền mặt** dự phòng.
3. **Triệt tiêu Cháy tài khoản:** Mọi tín hiệu đều qua bộ lọc **Safe Leverage Clamp**, đảm bảo điểm cắt lỗ luôn nằm trước điểm thanh lý tối thiểu 25% – 50%.
