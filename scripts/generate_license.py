#!/usr/bin/env python3
"""
CLI Tool for Admin to Generate Cryptographic License Keys for Customers.
Usage:
    python scripts/generate_license.py --hwid HWID-XXXX-XXXX-XXXX-XXXX --days 30 --plan VIP_MONTHLY
    python scripts/generate_license.py --hwid HWID-XXXX-XXXX-XXXX-XXXX --days 365 --plan VIP_YEARLY
    python scripts/generate_license.py --hwid HWID-XXXX-XXXX-XXXX-XXXX --lifetime
    python scripts/generate_license.py --hwid ANY --days 7 --plan MASTER_DEMO
"""
import argparse
import sys
from pathlib import Path

# Fix import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.license_service import LicenseService

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser(description="Bộ Sinh Khóa Bản Quyền Thương Mại (License Key Generator)")
    parser.add_argument("--hwid", required=True, help="Mã máy Hardware ID của khách hàng (hoặc 'ANY' cho key dùng chung)")
    parser.add_argument("--days", type=int, default=30, help="Số ngày sử dụng (mặc định 30 ngày)")
    parser.add_argument("--plan", default="VIP_MONTHLY", help="Tên gói (VIP_MONTHLY, VIP_YEARLY, TRIAL, PRO, LIFETIME)")
    parser.add_argument("--lifetime", action="store_true", help="Cấp bản quyền vĩnh viễn (không bao giờ hết hạn)")

    args = parser.parse_args()

    svc = LicenseService()
    days = 0 if args.lifetime else args.days
    plan = "LIFETIME" if args.lifetime else args.plan

    key = svc.generate_license_key(args.hwid, days=days, plan=plan)

    print("\n" + "=" * 65)
    print("💎 TELEGRAM BINANCE SIGNAL EXECUTOR - COMMERCIAL KEY ISSUER")
    print("=" * 65)
    print(f"👤 Target HWID   : {args.hwid.strip().upper()}")
    print(f"📦 Gói Bản Quyền : {plan}")
    print(f"⏳ Thời hạn      : {'VĨNH VIỄN (LIFETIME)' if args.lifetime else f'{args.days} Ngày'}")
    print("-" * 65)
    print("🔑 LICENSE KEY DÀNH CHO KHÁCH:")
    print(f"\n{key}\n")
    print("=" * 65)
    print("Hướng dẫn: Gửi mã trên cho khách hàng, khách chỉ cần dán vào mục Bản Quyền trong App.")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()

