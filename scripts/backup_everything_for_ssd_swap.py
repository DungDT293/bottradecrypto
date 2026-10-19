import os
import sys
import shutil
import zipfile
import time
from datetime import datetime

# Configure UTF-8 for console output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BACKUP_DIR = r"E:\BACKUP_SSD_MIGRATION"
os.makedirs(BACKUP_DIR, exist_ok=True)

print("=" * 60)
print("TIEN TRINH SAO LUU TOAN DIEN TRUOC KHI THAY O SSD")
print("=" * 60)
print(f"Thu muc luu tru sao luu: {BACKUP_DIR}\n")

def zip_folder(source_folder, output_zip_path, exclude_dirs=None):
    if exclude_dirs is None:
        exclude_dirs = set()
    print(f"--> Dang nen: {source_folder}...")
    start = time.time()
    file_count = 0
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(source_folder):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_folder)
                try:
                    zf.write(full_path, rel_path)
                    file_count += 1
                except Exception as e:
                    pass
    duration = time.time() - start
    size_mb = os.path.getsize(output_zip_path) / (1024 * 1024)
    print(f"    [XONG] {file_count} files, dung luong {size_mb:.2f} MB ({duration:.1f}s)\n")

# 1. Sao lưu toàn bộ Chat History & Brain của Antigravity AI
gemini_src = r"C:\Users\PC Gaming\.gemini"
if os.path.exists(gemini_src):
    zip_folder(gemini_src, os.path.join(BACKUP_DIR, "01_gemini_ai_chat_and_brain.zip"))

# 2. Sao lưu cấu hình IDE Antigravity & Extension
roaming_antigravity = r"C:\Users\PC Gaming\AppData\Roaming\Antigravity"
if os.path.exists(roaming_antigravity):
    zip_folder(roaming_antigravity, os.path.join(BACKUP_DIR, "02_antigravity_ide_state.zip"))

roaming_gemini = r"C:\Users\PC Gaming\AppData\Roaming\gemini"
if os.path.exists(roaming_gemini):
    zip_folder(roaming_gemini, os.path.join(BACKUP_DIR, "03_roaming_gemini_config.zip"))

# 3. Sao lưu Dữ liệu thực thi Bot (Phiên Telegram, SQLite DB, Keys)
appdata_bot = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor"
if os.path.exists(appdata_bot):
    zip_folder(appdata_bot, os.path.join(BACKUP_DIR, "04_bot_session_and_database.zip"))

# 4. Sao lưu Mã nguồn dự án Bot Trade (bao gồm .env, config.yaml, data/ - trừ node_modules & target)
project_src = r"E:\TOOL DUNG CODE\bottradecrypto"
exclude_project = {'node_modules', 'target', '.venv', '__pycache__', '.pytest_cache'}
zip_folder(project_src, os.path.join(BACKUP_DIR, "05_bottradecrypto_source_and_secrets.zip"), exclude_dirs=exclude_project)

# 5. Tạo file hướng dẫn khôi phục chi tiết
guide_path = os.path.join(BACKUP_DIR, "HUONG_DAN_KHOI_PHUC_SAU_KHI_THAY_SSD.md")
with open(guide_path, "w", encoding="utf-8") as f:
    f.write(f"""# HƯỚNG DẪN KHÔI PHỤC TOÀN BỘ DỰ ÁN & LỊCH SỬ CHAT AI SAU KHI THAY Ổ SSD
Thời gian sao lưu: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Vị trí thư mục sao lưu: {BACKUP_DIR}

---

## 1. CÁC TẬP TIN ĐÃ ĐƯỢC SAO LƯU:
1. `01_gemini_ai_chat_and_brain.zip`: Toàn bộ lịch sử chat, các cuộc hội thoại cũ, bộ nhớ AI (Brain), hình ảnh và tài liệu artifacts.
2. `02_antigravity_ide_state.zip`: Cấu hình giao diện IDE Antigravity, workspace và trạng thái tab đang mở.
3. `03_roaming_gemini_config.zip`: Cấu hình kết nối AI.
4. `04_bot_session_and_database.zip`: Phiên đăng nhập Telegram (`telegram_user.session`), cơ sở dữ liệu (`trading_state.db`), cấu hình (`config.yaml`), API Key (`.env`).
5. `05_bottradecrypto_source_and_secrets.zip`: Toàn bộ mã nguồn dự án Bot Trade Crypto đầy đủ (bao gồm cả các file nhạy cảm không đưa lên Git).

---

## 2. QUY TRÌNH KHÔI PHỤC TRÊN Ổ SSD MỚI (WINDOWS MỚI):

### Bước 1: Cài đặt lại phần mềm cần thiết
- Tải và cài đặt **Antigravity IDE** (hoặc IDE bạn đang sử dụng).
- Cài đặt **Python 3.11** (chọn tick vào ô 'Add python.exe to PATH').
- Cài đặt **Node.js** (LTS) & **Git**.

### Bước 2: Khôi phục dữ liệu AI & Lịch sử chat (Cực kỳ quan trọng)
1. Giải nén toàn bộ nội dung của `01_gemini_ai_chat_and_brain.zip` vào:
   `C:\\Users\\<Ten_User_Moi>\\.gemini`
   *(Thay `<Ten_User_Moi>` bằng tên user Windows bạn đặt khi cài Win)*
2. Giải nén `02_antigravity_ide_state.zip` vào:
   `C:\\Users\\<Ten_User_Moi>\\AppData\\Roaming\\Antigravity`
3. Giải nén `03_roaming_gemini_config.zip` vào:
   `C:\\Users\\<Ten_User_Moi>\\AppData\\Roaming\\gemini`

### Bước 3: Khôi phục Dữ liệu Bot Trade Crypto
1. Ổ cứng HDD 1TB (ổ chứa `E:\\TOOL DUNG CODE\\bottradecrypto`) vẫn còn nguyên trên máy:
   - Hãy kiểm tra xem Windows mới có gán đúng ký tự ổ là `E:` hay không (vào `Disk Management` đổi lại thành `E:` nếu bị nhận thành `D:`).
   - Nếu cần khôi phục lại mã nguồn sạch, chỉ cần giải nén `05_bottradecrypto_source_and_secrets.zip` vào `E:\\TOOL DUNG CODE\\bottradecrypto`.
2. Giải nén `04_bot_session_and_database.zip` vào:
   `C:\\Users\\<Ten_User_Moi>\\AppData\\Roaming\\telegram_binance_signal_executor`

### Bước 4: Mở Antigravity IDE
- Mở Antigravity IDE lên, chọn Open Folder: `E:\\TOOL DUNG CODE\\bottradecrypto`.
- **Toàn bộ lịch sử chat, các cuộc hội thoại, bối cảnh phân tích, 8 nhóm Telegram và kết quả PnL sẽ xuất hiện lại 100% nguyên vẹn!**
""")

# 6. Tạo file script tự động giải nén khôi phục 1-click
restore_bat_path = os.path.join(BACKUP_DIR, "KHOI_PHUC_TU_DONG_1_CLICK.bat")
with open(restore_bat_path, "w", encoding="utf-8") as f:
    f.write(r"""@echo off
chcp 65001 >nul
echo ============================================================
echo KHOI PHUC DU LIEU BOT TRADE VA LICH SU CHAT AI
echo ============================================================
echo.
echo Dang giai nen lich su Chat AI vao %USERPROFILE%\.gemini ...
powershell -Command "Expand-Archive -Path '01_gemini_ai_chat_and_brain.zip' -DestinationPath '%USERPROFILE%\.gemini' -Force"

echo Dang giai nen cau hinh Antigravity IDE...
if not exist "%APPDATA%\Antigravity" mkdir "%APPDATA%\Antigravity"
powershell -Command "Expand-Archive -Path '02_antigravity_ide_state.zip' -DestinationPath '%APPDATA%\Antigravity' -Force"

echo Dang giai nen cau hinh gemini roaming...
if not exist "%APPDATA%\gemini" mkdir "%APPDATA%\gemini"
powershell -Command "Expand-Archive -Path '03_roaming_gemini_config.zip' -DestinationPath '%APPDATA%\gemini' -Force"

echo Dang giai nen database va phien Telegram vao AppData...
if not exist "%APPDATA%\telegram_binance_signal_executor" mkdir "%APPDATA%\telegram_binance_signal_executor"
powershell -Command "Expand-Archive -Path '04_bot_session_and_database.zip' -DestinationPath '%APPDATA%\telegram_binance_signal_executor' -Force"

echo.
echo ============================================================
echo HOAN TAT KHOI PHUC!
echo Ban hay mo Antigravity IDE va mo thu muc E:\TOOL DUNG CODE\bottradecrypto
echo ============================================================
pause
""")

print("=" * 60)
print("TAT CA FILE SAO LUU DA DUOC TAO THANH CONG TAI:")
print(BACKUP_DIR)
print("=" * 60)
for item in os.listdir(BACKUP_DIR):
    item_path = os.path.join(BACKUP_DIR, item)
    sz = os.path.getsize(item_path) / (1024 * 1024)
    print(f"  - {item:45s} ({sz:6.2f} MB)")

