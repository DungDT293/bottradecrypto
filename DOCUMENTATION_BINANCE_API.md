# TAI LIEU VA XAC MINH BINANCE USD-M FUTURES API

- **Ngay kiem tra:** 15/10/2026
- **Pham vi he thong:** Binance USD-M Futures (USDT-Margined Perpetual Contracts)
- **Tai lieu tham khao:** Binance Official Futures API Documentation (binance-docs.github.io/apidocs/futures/en)

---

## 1. THAY DOI QUAN TRONG: DIEU KIEN DAT LENH CONDITIONAL / ALGO (STOP_MARKET & TAKE_PROFIT_MARKET)

### Canh bao nghiem trong:
Truoc day tren thu vien cu, lenh conditional duoc gui truc tiep qua endpoint `/fapi/v1/order` voi parameter `type=STOP_MARKET`.
Hien tai, Binance da chuyen toan bo lenh conditional (Stop Market, Stop Limit, Take Profit Market, Trailing Stop) sang **Algo Service**:
- Neu gui `STOP_MARKET` qua `/fapi/v1/order`, san se tu choi ngay lap tuc voi ma loi:
  ```json
  {"code": -4120, "msg": "STOP_ORDER_SWITCH_ALGO"}
  ```
- Endpoint dung cho lenh dieu kien hien tai:
  - **POST `/fapi/v1/algoOrder`** (Dat lenh conditional/algo)
  - **GET `/fapi/v1/algoOrder`** (Tra cuu algo order bang `algoId` hoac `clientAlgoId`)
  - **DELETE `/fapi/v1/algoOrder`** (Huy algo order)
  - **GET `/fapi/v1/openAlgoOrders`** (Danh sach algo order dang cho kich hoat)

### Cac tham so chinh khi dat Stop Loss (`STOP_MARKET` qua `/fapi/v1/algoOrder`):
- `symbol`: Ma cap giao dich (vd: `BTCUSDT`, `ETHUSDT`)
- `side`: Huong nguoc lai voi vi the (`SELL` neu LONG, `BUY` neu SHORT)
- `type`: `STOP_MARKET`
- `triggerPrice`: Muc gia kich hoat (Mark Price hoac Last Price cham muc nay)
- `quantity`: So luong co so hoac `closePosition=true` (dong toan bo vi the)
- `reduceOnly`: `true` (dam bao chi giam vi the, khong mo vi the nguoc)
- `workingType`: `MARK_PRICE` (khuyen nghi de tranh scam wicks) hoac `CONTRACT_PRICE`
- `clientAlgoId`: ID duy nhat de chong trung lap (idempotency)
- `timestamp` & `signature`: HMAC SHA256

---

## 2. LENH STANDARD CHO ENTRY & TP LIMIT

### Endpoint:
- **POST `/fapi/v1/order`**
- **GET `/fapi/v1/order`**
- **DELETE `/fapi/v1/order`**
- **GET `/fapi/v1/openOrders`**

### Tham so chinh cho Entry Limit:
- `symbol`: `BTCUSDT`
- `side`: `BUY` (LONG) hoac `SELL` (SHORT)
- `type`: `LIMIT`
- `timeInForce`: `GTC` (Good Till Cancel)
- `quantity`: Khoi luong hop le theo filter `LOT_SIZE` (lam tron theo `stepSize`)
- `price`: Gia limit theo filter `PRICE_FILTER` (lam tron theo `tickSize`)
- `newClientOrderId`: Ma dinh danh duy nhat do bot tao de chong duplicate

### Tham so chinh cho TP Limit (khi vi the da mo):
- `side`: `SELL` (neu LONG) hoac `BUY` (neu SHORT)
- `type`: `LIMIT`
- `reduceOnly`: `true`
- `timeInForce`: `GTC`
- `quantity`: Khoi luong chia theo ty le TP, lam tron theo `stepSize`
- `price`: Gia chot loi

---

## 3. KIEM TRA DIEU KIEN TAI KHOAN VA VI THE (PRE-FLIGHT CHECKS)

### Position Mode (Bat buoc One-Way):
- Endpoint: `GET /fapi/v1/positionSide/dual`
- Ket qua hop le: `{"dualSidePosition": false}` (One-Way Mode).
- Neu `true` (Hedge Mode): He thong bao **BLOCKED**; khong tu y doi mode vi se anh huong cac vi the dang mo cua nguoi dung.

### Margin Type (Bat buoc ISOLATED):
- Endpoint kiem tra: `GET /fapi/v2/positionRisk` -> kiem tra truong `marginType` la `isolated`.
- Endpoint thiet lap neu chua co vi the: `POST /fapi/v1/marginType` (`marginType=ISOLATED`).
- Luu y: Binance chi cho phep doi margin type khi KHONG co vi the va KHONG co open orders tren symbol do. Neu da co vi the cross, he thong bao **BLOCKED**.

### Leverage Filter:
- Endpoint: `POST /fapi/v1/leverage`
- He thong luon ap dung `min(signal_leverage, max_leverage_policy)`. Vi du tin ghi 200X, bot chi dat toi da 5X theo config.

### Exchange Info & Filters:
- Endpoint: `GET /fapi/v1/exchangeInfo`
- Cac bo loc can xac thuc:
  - `PRICE_FILTER`: `tickSize`, `minPrice`, `maxPrice`
  - `LOT_SIZE`: `stepSize`, `minQty`, `maxQty`
  - `MIN_NOTIONAL`: Gia tri danh nghia toi thieu (vd: 5 USDT hoac 10 USDT tren Binance Futures). Neu `quantity * price < minNotional`, lenh bi san tu choi. Bot kiem tra truoc khi gui.

---

## 4. CO CHE FAIL-SAFE KHI ENTRY FILL NHUNG SL THAT BAI

Entry va Stop Loss tren san khong phai transaction nguyen tu (atomic). Do do co khoang thoi gian tre giua khi Entry fill va khi Stop Loss duoc xac nhan:
1. Neu Entry fill mot phan hoac toan bo, bot lap tuc gui Stop Loss qua `/fapi/v1/algoOrder`.
2. Neu lenh SL bi loi mang hoac bi san tu choi:
   - Lap tuc retry toi da 2 lan trong vong 1-2 giay.
   - Neu van that bai: Kich hoat **EMERGENCY CLOSE**:
     - Huy toan bo entry orders con cho tren symbol do (`DELETE /fapi/v1/order`).
     - Dat lenh `MARKET` voi `reduceOnly=true` de dong toan bo khoi luong vua khop.
     - Kiem tra lai positionRisk de xac nhan vi the da ve 0.
     - Ghi log canh bao: `BI CHAN: SL THAT BAI - DA DONG KHAN CAP VI THE`.

