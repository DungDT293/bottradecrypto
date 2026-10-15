# DANH SACH POLICY VA HUONG XU LY (POLICY SPECIFICATIONS)

He thong tuân thu nguyen tac: **Khong tu doan, khong tu tien sua so, khong gia dinh du lieu mo ho**.

---

## 1. PHAN LOAI NGUON CUA CAC GIA TRI (FIELD SOURCE TRACKING)

Moi truong du lieu cua tin hieu khi parse phai co nguon goc xac thuc:
- `EXPLICIT_SIGNAL`: Du lieu duoc ghi ro rang, khong mo ho trong tin nhan goc.
- `SOURCE_POLICY`: Chinh sach duoc nguoi dung phe duyet rieng cho kenh/nguon nay.
- `GLOBAL_POLICY`: Chinh sach mac dinh toan he thong trong `config.yaml`.
- `UNRESOLVED`: Khong co trong tin va chua co policy nao duoc duyet -> Chuyen trang thai `NEEDS_POLICY` hoac `NEEDS_REVIEW`.

---

## 2. CHINH SACH CHO NHIEU ENTRY (MULTI-ENTRY POLICY)

Khi tin co 2 hoac nhieu muc entry (vi du: GRASS co Entry 1: 0.5020, Entry 2: 0.4870; ETH co 2367, 2387):
- **Van de:** Tin hieu khong ghi ty le phan bo von giua Entry 1 va Entry 2.
- **Cac lua chon:**
  1. `EQUAL_RISK`: Chia rui ro bang nhau cho moi entry (Quantity tinh sao cho `Qty1 * |E1 - SL| == Qty2 * |E2 - SL|`).
  2. `EQUAL_NOTIONAL`: Chia gia tri danh nghia bang nhau (`Qty1 * E1 == Qty2 * E2`).
  3. `EQUAL_QUANTITY`: Chia so luong token bang nhau (`Qty1 == Qty2`).
  4. `NEEDS_POLICY` (Mac dinh): Neu nguoi dung chua chon 1 trong 3 cach tren cho nguon nay, tin hieu bi tam giu o trang thai `NEEDS_POLICY`.

---

## 3. CHINH SACH CHO VUNG ENTRY (ENTRY RANGE POLICY)

Khi tin co vung entry (vi du: QTUM co `Entries: 0.8960 - 0.9160`):
- **Van de:** Day la mot khoang gia, khong phai 1 muc gia limit cu the.
- **Cac lua chon:**
  1. `BEST_PRICE`: Chi dat 1 lenh limit o muc gia tot nhat cua vung (SHORT dat tai gia cao nhat cua vung, LONG dat tai gia thap nhat cua vung).
  2. `MID_POINT`: Dat 1 lenh limit o muc gia trung binh `(min + max) / 2`.
  3. `SPLIT_2_LIMITS`: Dat 2 lenh limit o 2 dau cua range.
  4. `NEEDS_POLICY` (Mac dinh): Neu chua duoc cau hinh, giu o trang thai `NEEDS_POLICY`.

---

## 4. CHINH SACH CHO NHIEU TP (MULTI-TP ALLOCATION)

Khi tin co 3 hoac 4 muc TP nhung khong ghi ty le chot:
- Neu tin co ghi ro (vi du: GRASS ghi "Close 50% at TP1 and 50% at TP2"): dung `EXPLICIT_SIGNAL`.
- Neu tin KHONG ghi ty le (vi du: ZEREBRO 3 TP, RSR 4 TP, ETH 3 TP, QTUM 3 TP):
  - Mac dinh he thong la `NEEDS_POLICY`.
  - Nguoi dung co the cau hinh: `EQUAL_SPLIT` (chia deu) hoac `FRONT_LOADED_50_30_20`.
  - Luu y: Phai kiem tra tung phan sau khi chia co dat `minQty` va `minNotional` cua san khong. Neu phan cuoi bi nho hon filter, tu dong gop vao phan truoc de tranh loi san.

---

## 5. CHINH SACH DOI BREAKEVEN (BREAKEVEN POLICY)

- "Consider moving SL to breakeven after TP1" (vi du: GRASS): Day la loi khuyen/goi y ("Consider"), KHONG phai chi dan bat buoc. Mac dinh khong tu dong doi SL tru khi nguoi dung bat `breakeven_after_tp1_default: true`.
- "Trailing Configuration: Stop: Breakeven - Trigger: Target (1)" (vi du: ETH): Day la chi dan ro rang tu tin hieu.
- Quy tac khi dời Breakeven:
  1. Dung gia khop thuc te binh quan (Weighted Average Fill Price), khong dung gia ly thuyet.
  2. Tinh them phi giao dich 2 chieu (phi mo + phi dong du kien) de dam bao hoa von thuc te.
  3. Truoc khi doi SL, phai huy cac pending entry con lai neu co.
  4. Gui algo order SL moi truoc, sau khi xac nhan thanh cong moi huy algo order SL cu (tranh khoang trong khong co SL bao ve).

---

## 6. XU LY BAT DONG NGHIA VA TIN MO HO (CONFLICT & AMBIGUITY RULES)

- **Mau ATOM:** Tieu de ghi `#SHORT`, nhung noi dung entry ghi `BUY : 1) 1.674 - 100%`. Day la mau thuan truc tiep ve huong lenh -> Bat buoc danh dau `NEEDS_REVIEW`, chan tuyet doi khong dat lenh.
- **Mau TRUTH:** `Short BELOW (0.02300)(0.02325)` -> Co 2 con so sau chu "BELOW", ngu nghia entry khong ro rang (la vung gia hay 2 muc gia) -> Bat buoc danh dau `NEEDS_REVIEW`.
- **Mau Q/USD:** SL ghi `052506` khong co dau cham thap phan. Trong boi canh crypto gia 0.05, khong duoc tu sua thanh 0.052506. Symbol Q/USD khong co quote USDT -> Bat buoc danh dau `REJECTED` (Symbol khong hop le / SL mo ho).
- **Don bay cao (200x trong ETH, 50-75x trong RSR):** San va chinh sach rui ro dat tran (vd: max 5x). He thong khong sao chep 200x ma luon ap tran an toan `min(requested_leverage, policy_max_leverage)`.

