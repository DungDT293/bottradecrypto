import yaml

config_paths = [
    r"e:\TOOL DUNG CODE\bottradecrypto\config.yaml",
    r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\config.yaml"
]

ELITE_5_CHANNELS = {
    -1001756316676: "Boom_Boom_Billionaires",
    -1002052872813: "CRYPTO LEOPARD'S",
    -1001754095061: "Crypto Radar",
    -1002007658025: "THE WOLF (CRYPTO)®",
    -1001552004524: "CRYPTO MONK",
}

SCALP_SECONDARY_CHANNELS = {
    -1001370457350: "Crypto Neon",
    -1001895315984: "Crypto spider 🕷️ scalper",
    -1002266035358: "THE MASTER (CRYPTO)",
    -1001161683441: "Global Crypto Research",
    -1001212188460: "Binance Team® - By Jhonny",
    -1001519589508: "Futures Crypto Signals",
    -1001966506182: "Whale Crypto Signals",
    -1002191067035: "Crypto Hunters",
    -1001860630181: "Alpha Trade Zone",
    -1001656921849: "ESTR",
    -1001652601224: "Crypto World Updates",
    -1001553551852: "Bitcoinsensus VIP",
    -1001781413045: "Binance 360 VIP",
}

for cp in config_paths:
    with open(cp, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 1. Update risk
    data["risk"]["target_margin_pct"] = "5.0"
    data["risk"]["max_margin_per_trade_pct"] = "7.0"
    data["risk"]["risk_per_signal_pct"] = "2.5"
    data["risk"]["max_total_open_risk_pct"] = "12.0"
    data["risk"]["default_leverage"] = 20
    data["risk"]["max_leverage"] = 25
    data["execution"]["tp1_target_weight_pct"] = "35.0"

    # 2. Build complete sources with margin_multiplier and 11x-25x leverage rules
    sources = {}
    # Elite channels: 1.0 (5% account)
    for cid, name in ELITE_5_CHANNELS.items():
        sources[str(cid)] = {
            "chat_id": cid,
            "name": name,
            "margin_multiplier": 1.0,
            "max_leverage_override": 25,
            "default_leverage_override": 20,
            "allow_below_pattern": False,
            "allow_buy_as_short_exception": False,
            "allow_multi_entry_equal_split": False,
            "allow_range_midpoint": False,
            "allow_tp_equal_split": False,
        }

    # Secondary/Scalp channels: 0.5 (2.5% account)
    for cid, name in SCALP_SECONDARY_CHANNELS.items():
        sources[str(cid)] = {
            "chat_id": cid,
            "name": name,
            "margin_multiplier": 0.5,
            "max_leverage_override": 25,
            "default_leverage_override": 20,
            "allow_below_pattern": False,
            "allow_buy_as_short_exception": False,
            "allow_multi_entry_equal_split": False,
            "allow_range_midpoint": False,
            "allow_tp_equal_split": False,
        }

    data["sources"] = sources

    with open(cp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    print("Updated config at:", cp)

