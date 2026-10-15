import getpass
import os
from typing import Optional
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config.config import AppConfig


class TelegramAuthHelper:
    """
    Helps user safely log into Telegram MTProto account from the local CLI.
    Never transmits or logs credentials, codes, or 2FA passwords.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.api_id = config.telegram.api_id
        self.api_hash = config.telegram.api_hash
        self.session_path = config.telegram.session_name

    async def login_interactive(self) -> bool:
        if not self.api_id or not self.api_hash:
            print("\n[BLOCKED] Thieu TELEGRAM_API_ID hoac TELEGRAM_API_HASH trong file .env")
            print("Vui long lay tai https://my.telegram.org va them vao file .env truoc khi dang nhap.\n")
            return False

        os.makedirs(os.path.dirname(os.path.abspath(self.session_path)), exist_ok=True)
        client = TelegramClient(self.session_path, self.api_id, self.api_hash)

        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"\n[DA DANG NHAP] Tai khoan Telegram hien tai: {me.first_name} (@{me.username or me.phone})")
            await client.disconnect()
            return True

        phone = self.config.telegram.phone
        if not phone:
            phone = input("\nNhap so dien thoai dang ky Telegram (dinh dang quoc te, vd: +84912345678): ").strip()

        print(f"Dang gui yeu cau ma xac thuc den so dien thoai {phone}...")
        try:
            sent = await client.send_code_request(phone)
        except Exception as e:
            print(f"\n[LOI GUI MA] {str(e)}")
            await client.disconnect()
            return False

        code = input("Nhap ma xac thuc nhan duoc tu Telegram: ").strip()

        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            print("Tai khoan co bat mat khau 2FA.")
            pwd = getpass.getpass("Nhap mat khau 2FA cua ban: ")
            await client.sign_in(password=pwd)
        except Exception as e:
            print(f"\n[LOI DANG NHAP] {str(e)}")
            await client.disconnect()
            return False

        me = await client.get_me()
        print(f"\n[DANG NHAP THANH CONG] Xin chao {me.first_name}! Session da duoc luu an toan tai: {self.session_path}.session\n")
        await client.disconnect()
        return True

