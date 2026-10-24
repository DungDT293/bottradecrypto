import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from config.policy_defaults import ExecutionPolicyConfig, RiskPolicy, SourcePolicyOverride
from core.enums import ExecutionMode

DEFAULT_ELITE_CHANNELS = [
    -1001520053536,  # Coin Chief (Tier 1 - Winrate 73.53%, R:R 1:2.0, Breakout chuẩn)
    -1002052872813,  # CRYPTO LEOPARD'S (Tier 1 - Winrate 79.5% - 81.8%, Short kiệt sức)
    -1001598691683,  # Crypto Devil® [Private] (Tier 1 - Winrate 71.4% - 88.9%, Mean Reversion)
    -1001700314832,  # WHALES CIRCLE (Tier 1 - Winrate 72.2%, R:R 1:2.5 - 1:3.2, Nến 4H/1D)
    -1001391574614,  # Bitcoin Bulls (Tier 2 - Winrate 68.42%, Cổ điển)
    -1002078531832,  # Crypto Mermaids (Tier 2 - Winrate 62.50%, Chuyên BTC)
    -1002007658025,  # THE WOLF (CRYPTO)® (Tier 2 - Winrate 65.00%, Dual-Entry)
    -1001552004524,  # CRYPTO MONK (Tier 2 - Winrate 62.50%, Bẫy thanh khoản)
]
DEFAULT_8_CHANNELS = DEFAULT_ELITE_CHANNELS
DEFAULT_22_CHANNELS = DEFAULT_ELITE_CHANNELS

PERMANENT_BLACKLISTED_CHANNELS: Dict[int, str] = {
    -1002191067035: "Crypto Hunters - Quét SL 77.5%, giấu số liệu lỗ, xóa tin nhắn thua",
    -1002266035358: "THE MASTER (CRYPTO) - Winrate 29%, R:R 0.43, lệnh gỡ SL/DCA, Fake Gap 69.4%",
    -1001903052876: "AISH CRYPTO - Lừa đảo ví cá nhân BEP20, khoe lãi ma, SL 15%",
    -1001390568202: "PRO TRADING - Stoploss theo admin (vi phạm Zero-Liquidation)",
    -1001756316676: "Boom_Boom_Billionaires - Suy thoái thành spam link đa cấp, teaser Targets 👇 rỗng",
    -1001370457350: "Crypto Neon - Kênh đã chết/dừng phát kèo, spam copy trade MEXC",
    -1001430928952: "Crypto Trading Signal - Kênh bỏ hoang",
    -1001899782732: "S1IMPLE CAPITAL - Kèo chat tự do không có cấu trúc",
    -1001966506182: "Crypto Pulse Matrix® - 90% teaser khoe lãi ảo 1636%",
    -1001982472141: "ÇRYPTO (BÈAST)™ - Tín hiệu không có Stop Loss",
    -1001120565155: "CFTopTrading - Nhật ký tự sự, không có thông số",
    -1002159998063: "Gold First - Kênh chết",
    -1001590450482: "THE CRYPTO TRADER - Format lỗi, không có Stop Loss",
    -1002134496030: "Crypto Time Hotel - Nhận định chung chung",
    -1001526156115: "RSR CRYPTO SIGNAL ™️ - 100% khoe VIP và teaser",
    -1001594522150: "Whales_Pumps - 100% teaser rác",
    -1002477619139: "Dahlia X Trader - 100% teaser rác",
    -1001591741285: "ASR CRYPTO SIGNAL - 100% teaser rác",
    -1002007699575: "Absolute Futures - Kèo demo không có SL",
    -1001652601224: "Crypto World Updates - Đòn bẩy 75x kết hợp SL 6% gây cháy tài khoản",
    -1001754095061: "Crypto Radar - R:R nghịch lý 1:0.09 (TP1 +0.58% vs SL -6.28%)",
}


class TelegramConfig(BaseModel):
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    phone: Optional[str] = None
    session_name: str = "./data/telegram_user"
    allowed_chat_ids: List[int] = Field(default_factory=lambda: list(DEFAULT_22_CHANNELS))
    blacklisted_chat_ids: List[int] = Field(default_factory=lambda: list(PERMANENT_BLACKLISTED_CHANNELS.keys()))
    admin_sender_ids: List[int] = Field(default_factory=list)
    reconnect_max_backlog_seconds: int = 300
    sanitize_input: bool = True
    remote_channels_url: Optional[str] = None


class BinanceConfig(BaseModel):
    testnet_base_url: str = "https://demo-fapi.binance.com"
    live_base_url: str = "https://fapi.binance.com"
    recv_window: int = 5000
    request_timeout_seconds: int = 15
    max_retries: int = 3
    testnet_api_key: Optional[str] = None
    testnet_api_secret: Optional[str] = None
    live_api_key: Optional[str] = None
    live_api_secret: Optional[str] = None
    algo_order_endpoint: str = "/fapi/v1/algoOrder"
    standard_order_endpoint: str = "/fapi/v1/order"
    live_user_stream_ws_url: str = "wss://fstream.binance.com/ws"


class NotificationsConfig(BaseModel):
    console_logging: bool = True
    log_level: str = "INFO"
    telegram_notification_enabled: bool = False
    notification_bot_token: Optional[str] = None
    notification_chat_id: Optional[int] = None


class GeminiAIConfig(BaseModel):
    enabled: bool = False
    api_key: Optional[str] = None
    preferred_model: str = "gemini-3.6-flash"
    scan_interval_minutes: int = 15
    min_confidence: int = 75
    watchlist: List[str] = Field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "DOGEUSDT", "SUIUSDT", "NEARUSDT", "AVAXUSDT", "PEPEUSDT",
    ])


class AppConfig(BaseModel):
    mode: ExecutionMode = ExecutionMode.READ_ONLY
    live_trading_enabled: bool = False
    ferrari_mode_enabled: bool = False
    data_dir: str = "./data"
    database_file: str = "./data/trading_state.db"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    ai: GeminiAIConfig = Field(default_factory=GeminiAIConfig)
    risk: RiskPolicy = Field(default_factory=RiskPolicy)
    execution: ExecutionPolicyConfig = Field(default_factory=ExecutionPolicyConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    sources: Dict[int, SourcePolicyOverride] = Field(default_factory=dict)


def exchange_writes_enabled(config: AppConfig) -> bool:
    """Return whether automatic exchange mutations are allowed for this config."""
    return config.mode == ExecutionMode.TESTNET or (
        config.mode == ExecutionMode.LIVE and config.live_trading_enabled
    )


def is_safe_testnet_url(config: AppConfig) -> bool:
    """Reject testnet writes pointed at the live Binance host."""
    testnet_host = (urlsplit(config.binance.testnet_base_url).hostname or "").lower()
    live_host = (urlsplit(config.binance.live_base_url).hostname or "").lower()
    return bool(testnet_host) and testnet_host != live_host and testnet_host in {
        "demo-fapi.binance.com",
        "testnet.binancefuture.com",
    }


def load_config(config_path: Optional[str] = None) -> AppConfig:
    data: Dict[str, Any] = {}

    # Load potential .env files
    env_candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "telegram_binance_signal_executor", ".env"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "telegram-binance-signal-executor", ".env"),
        os.path.join(os.path.dirname(sys.executable), ".env"),
        os.path.join(os.path.dirname(sys.executable), "resources", ".env"),
        ".env",
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

    # A config file must explicitly opt into live trading; missing flag stays safe.
    if data.get("mode") == ExecutionMode.LIVE.value and data.get("live_trading_enabled") is None:
        data["live_trading_enabled"] = False

    # If allowed_chat_ids is empty in loaded yaml, keep default 22 channels
    tg_data = data.setdefault("telegram", {})
    if not tg_data.get("allowed_chat_ids"):
        tg_data["allowed_chat_ids"] = list(DEFAULT_22_CHANNELS)

    # Initialize and merge blacklisted_chat_ids
    existing_bl = set(tg_data.get("blacklisted_chat_ids") or [])
    existing_bl.update(PERMANENT_BLACKLISTED_CHANNELS.keys())
    tg_data["blacklisted_chat_ids"] = list(existing_bl)

    # STRICT INVARIANT: Strip all blacklisted channels from allowed_chat_ids and sources
    current_allowed = tg_data.get("allowed_chat_ids") or []
    tg_data["allowed_chat_ids"] = [cid for cid in current_allowed if cid not in existing_bl]
    
    sources_data = data.get("sources") or {}
    for bl_cid in existing_bl:
        bl_str = str(bl_cid)
        if bl_str in sources_data:
            sources_data.pop(bl_str, None)
        if bl_cid in sources_data:
            sources_data.pop(bl_cid, None)

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

    ai_data = data.setdefault("ai", {})
    if os.getenv("GEMINI_API_KEY") and not ai_data.get("api_key"):
        ai_data["api_key"] = os.environ["GEMINI_API_KEY"].strip()

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



