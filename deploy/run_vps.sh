#!/usr/bin/env bash
# =============================================================================
# deploy/run_vps.sh
# JARVIS QUANTUM AI TRADING BOT - VPS BOOTSTRAPPER & DAEMON RUNNER
# =============================================================================
set -e

echo "====================================================================="
echo "  JARVIS QUANTUM AI MARK 85 - VPS PRODUCTION RUNNER"
echo "  Zero-Liquidation Autonomous Futures Trading Daemon"
echo "====================================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# 1. Kiểm tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "[!] Lỗi: python3 chưa được cài đặt. Vui lòng chạy: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[+] Phát hiện phiên bản Python: $PY_VER"

# 2. Khởi tạo Virtual Environment
if [ ! -d "venv" ]; then
    echo "[*] Đang khởi tạo môi trường ảo (venv)..."
    python3 -m venv venv
fi

# 3. Kích hoạt Virtual Environment & Cài đặt thư viện
echo "[*] Kích hoạt venv và cập nhật dependencies..."
source venv/bin/activate
pip install --upgrade pip --quiet
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
fi

# 4. Kiểm tra cấu hình config.yaml hoặc .env
if [ ! -f "config/config.yaml" ] && [ ! -f ".env" ]; then
    echo "[!] CẢNH BÁO: Chưa tìm thấy config/config.yaml hoặc file .env!"
    echo "    Vui lòng copy file mẫu: cp config/config.yaml.example config/config.yaml"
    echo "    Sau đó điền Binance API Key/Secret và Telegram Bot Token."
fi

# 5. Chạy test xác nhận hệ thống
echo "[*] Kiểm tra nhanh tính toàn vẹn hệ thống (Pytest)..."
python -m pytest tests/test_dedicated_bot.py -q || {
    echo "[!] Cảnh báo: Test chưa đạt. Hãy kiểm tra lại môi trường."
}

# 6. Khởi động Jarvis Dedicated Bot Daemon
echo "====================================================================="
echo "  KHỞI ĐỘNG JARVIS TELEGRAM BOT 24/7..."
echo "  Bấm Ctrl+C để dừng bot."
echo "====================================================================="
exec python -u -m telegram.dedicated_bot "$@"

