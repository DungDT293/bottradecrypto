import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from config.policy_defaults import ExecutionPolicyConfig, RiskPolicy, SourcePolicyOverride
from core.enums import ExecutionMode

# Load local .env if present
load_dotenv()


class TelegramConfig(BaseModel):
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    phone: Optional[str] = None
    session_name: str = "./data/telegram_user"
    allowed_chat_ids: List[int] = Field(default_factory=list)
    reconnect_max_backlog_seconds: int = 300
    sanitize_input: bool = True


class BinanceConfig(BaseModel):
    testnet_base_url: str = "https://testnet.binancefuture.com"
    live_base_url: str = "https://fapi.binance.com"
    recv_window: int = 5000
    request_timeout_seconds: int = 10
    max_retries: int = 3
    testnet_api_key: Optional[str] = None
    testnet_api_secret: Optional[str] = None
    live_api_key: Optional[str] = None
    live_api_secret: Optional[str] = None
    algo_order_endpoint: str = "/fapi/v1/algoOrder"
    standard_order_endpoint: str = "/fapi/v1/order"


class NotificationsConfig(BaseModel):
    console_logging: bool = True
    log_level: str = "INFO"
    telegram_notification_enabled: bool = False
    notification_bot_token: Optional[str] = None
    notification_chat_id: Optional[int] = None


class AppConfig(BaseModel):
    mode: ExecutionMode = ExecutionMode.READ_ONLY
    live_trading_enabled: bool = False
    data_dir: str = "./data"
    database_file: str = "./data/trading_state.db"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    risk: RiskPolicy = Field(default_factory=RiskPolicy)
    execution: ExecutionPolicyConfig = Field(default_factory=ExecutionPolicyConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    sources: Dict[int, SourcePolicyOverride] = Field(default_factory=dict)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    data: Dict[str, Any] = {}

    # Find configuration file
    potential_paths = [
        config_path,
        "config.yaml",
        "config.example.yaml",
    ]
    actual_path = None
    for p in potential_paths:
        if p and Path(p).exists():
            actual_path = p
            break

    if actual_path:
        with open(actual_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
            data.update(yaml_data)

    # Inject env secrets
    tg_data = data.setdefault("telegram", {})
    if os.getenv("TELEGRAM_API_ID"):
        try:
            tg_data["api_id"] = int(os.environ["TELEGRAM_API_ID"].strip())
        except ValueError:
            pass
    if os.getenv("TELEGRAM_API_HASH"):
        tg_data["api_hash"] = os.environ["TELEGRAM_API_HASH"].strip()
    if os.getenv("TELEGRAM_PHONE"):
        tg_data["phone"] = os.environ["TELEGRAM_PHONE"].strip()

    bn_data = data.setdefault("binance", {})
    if os.getenv("BINANCE_TESTNET_API_KEY"):
        bn_data["testnet_api_key"] = os.environ["BINANCE_TESTNET_API_KEY"].strip()
    if os.getenv("BINANCE_TESTNET_API_SECRET"):
        bn_data["testnet_api_secret"] = os.environ["BINANCE_TESTNET_API_SECRET"].strip()
    if os.getenv("BINANCE_LIVE_API_KEY"):
        bn_data["live_api_key"] = os.environ["BINANCE_LIVE_API_KEY"].strip()
    if os.getenv("BINANCE_LIVE_API_SECRET"):
        bn_data["live_api_secret"] = os.environ["BINANCE_LIVE_API_SECRET"].strip()

    notif_data = data.setdefault("notifications", {})
    if os.getenv("NOTIFICATION_BOT_TOKEN"):
        notif_data["notification_bot_token"] = os.environ["NOTIFICATION_BOT_TOKEN"].strip()
    if os.getenv("NOTIFICATION_CHAT_ID"):
        try:
            notif_data["notification_chat_id"] = int(os.environ["NOTIFICATION_CHAT_ID"].strip())
        except ValueError:
            pass

    return AppConfig.model_validate(data)

