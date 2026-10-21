import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from config.policy_defaults import ExecutionPolicyConfig, RiskPolicy, SourcePolicyOverride
from core.enums import ExecutionMode

DEFAULT_ELITE_CHANNELS = [
    -1001754095061,  # Crypto Radar (Tier S - Pure Binance Futures, 81.8% Winrate)
    -1001756316676,  # Boom_Boom_Billionaires (Tier S - Pure Binance Futures, 75.0% Winrate)
    -1001370457350,  # Crypto Neon (Tier A - Fixed 10x Leverage, Binance coins only, 71.4% Winrate)
    -1002052872813,  # CRYPTO LEOPARD'S (Tier A - Binance Futures coins only, 79.5% Winrate)
]
DEFAULT_8_CHANNELS = DEFAULT_ELITE_CHANNELS
DEFAULT_22_CHANNELS = DEFAULT_ELITE_CHANNELS


# Load local .env if present
load_dotenv()


class TelegramConfig(BaseModel):
    api_id: Optional[int] = 28680296
    api_hash: Optional[str] = "927e2da6e7d0ec3d97a79d11cc794e46"
    phone: Optional[str] = None
    session_name: str = "./data/telegram_user"
    allowed_chat_ids: List[int] = Field(default_factory=lambda: list(DEFAULT_22_CHANNELS))
    reconnect_max_backlog_seconds: int = 300
    sanitize_input: bool = True


class BinanceConfig(BaseModel):
    testnet_base_url: str = "https://demo-fapi.binance.com"
    live_base_url: str = "https://fapi.binance.com"
    recv_window: int = 5000
    request_timeout_seconds: int = 10
    max_retries: int = 3
    testnet_api_key: Optional[str] = "74OJJEcThtPKbWegQ8qNf4O4Ojav0oSExUnpvlo1Ud2z0LML9mUpQfLfHGKZlftb"
    testnet_api_secret: Optional[str] = "9C4cEFHbBgH6RtLPW37QkRJmKw6IjnJagYTmmkLB2AxRepl7opleMfxZmoPstbUF"
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
    mode: ExecutionMode = ExecutionMode.TESTNET
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

    # Load potential .env files
    env_candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "telegram_binance_signal_executor", ".env"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "telegram-binance-signal-executor", ".env"),
        os.path.join(os.path.dirname(sys.executable), ".env"),
        os.path.join(os.path.dirname(sys.executable), "resources", ".env"),
        ".env",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
        r"e:\TOOL DUNG CODE\bottradecrypto\.env",
    ]
    for env_p in env_candidates:
        if env_p and os.path.exists(env_p):
            load_dotenv(env_p, override=False)

    # Find configuration file
    if os.environ.get("PYTEST_CURRENT_TEST"):
        potential_paths = [
            config_path,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.example.yaml"),
            "config.example.yaml",
        ]
    else:
        potential_paths = [
            config_path,
            os.path.join(os.environ.get("APPDATA", ""), "telegram_binance_signal_executor", "config.yaml"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "telegram-binance-signal-executor", "config.yaml"),
            os.path.join(os.path.dirname(sys.executable), "config.yaml"),
            os.path.join(os.path.dirname(sys.executable), "resources", "config.yaml"),
            "config.yaml",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"),
            r"e:\TOOL DUNG CODE\bottradecrypto\config.yaml",
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

    # If allowed_chat_ids is empty in loaded yaml, keep default 22 channels
    tg_data = data.setdefault("telegram", {})
    if not tg_data.get("allowed_chat_ids"):
        tg_data["allowed_chat_ids"] = list(DEFAULT_22_CHANNELS)

    # Inject env secrets
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
    if os.getenv("BINANCE_TESTNET_BASE_URL"):
        bn_data["testnet_base_url"] = os.environ["BINANCE_TESTNET_BASE_URL"].strip()
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


def save_config(config: AppConfig, config_path: Optional[str] = None) -> bool:
    """
    Persists configuration to config.yaml across AppData and project root.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not config_path:
        return True

    target_paths = []
    if config_path:
        target_paths.append(config_path)

    appdata_p = os.path.join(os.environ.get("APPDATA", ""), "telegram_binance_signal_executor", "config.yaml")
    localappdata_p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "telegram-binance-signal-executor", "config.yaml")
    root_p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

    for cand in [appdata_p, localappdata_p, root_p]:
        if cand not in target_paths:
            target_paths.append(cand)

    cfg_dict = config.model_dump(mode="json")

    saved = False
    for p in target_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                yaml.dump(cfg_dict, f, default_flow_style=False, allow_unicode=True)
            saved = True
        except Exception:
            pass
    return saved



