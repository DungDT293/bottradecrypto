import yaml

sources_dict = {
  '-1001756316676': {
    'chat_id': -1001756316676,
    'name': 'Boom_Boom_Billionaires',
    'margin_multiplier': 1.0,
    'max_leverage_override': 12,
    'default_leverage_override': 10,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_range_split_limits': True,
    'allow_tp_equal_split': True
  },
  '-1002052872813': {
    'chat_id': -1002052872813,
    'name': "CRYPTO LEOPARD'S",
    'margin_multiplier': 1.0,
    'max_leverage_override': 15,
    'default_leverage_override': 10,
    'allow_below_pattern': True,
    'allow_buy_as_short_exception': True,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_range_split_limits': True,
    'allow_tp_equal_split': True
  },
  '-1002007658025': {
    'chat_id': -1002007658025,
    'name': 'THE WOLF (CRYPTO)®',
    'margin_multiplier': 1.0,
    'max_leverage_override': 12,
    'default_leverage_override': 10,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': True,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': True
  },
  '-1001552004524': {
    'chat_id': -1001552004524,
    'name': 'CRYPTO MONK',
    'margin_multiplier': 1.0,
    'max_leverage_override': 15,
    'default_leverage_override': 12,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': True,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_range_split_limits': True,
    'allow_tp_equal_split': True
  },
  '-1001370457350': {
    'chat_id': -1001370457350,
    'name': 'Crypto Neon',
    'margin_multiplier': 1.0,
    'max_leverage_override': 10,
    'default_leverage_override': 8,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': True
  },
  '-1001895315984': {
    'chat_id': -1001895315984,
    'name': 'Crypto spider 🕷️ scalper',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1002266035358': {
    'chat_id': -1002266035358,
    'name': 'THE MASTER (CRYPTO)',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1001161683441': {
    'chat_id': -1001161683441,
    'name': 'Global Crypto Research',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1001966506182': {
    'chat_id': -1001966506182,
    'name': 'Whale Crypto Signals',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1002191067035': {
    'chat_id': -1002191067035,
    'name': 'Crypto Hunters',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1001860630181': {
    'chat_id': -1001860630181,
    'name': 'Alpha Trade Zone',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1001652601224': {
    'chat_id': -1001652601224,
    'name': 'Crypto World Updates',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  },
  '-1001781413045': {
    'chat_id': -1001781413045,
    'name': 'Binance 360 VIP',
    'margin_multiplier': 0.5,
    'max_leverage_override': 25,
    'default_leverage_override': 20,
    'allow_below_pattern': False,
    'allow_buy_as_short_exception': False,
    'allow_multi_entry_equal_split': False,
    'allow_range_midpoint': False,
    'allow_tp_equal_split': False
  }
}

with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

cfg['risk']['max_daily_loss_pct'] = '15.0'
cfg['risk']['max_total_open_risk_pct'] = '12.0'
cfg['sources'] = sources_dict
cfg['telegram']['allowed_chat_ids'] = [
    -1002052872813,
    -1001756316676,
    -1001370457350,
    -1002007658025,
    -1001552004524
]

with open('config.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)

print('config.yaml restored with full sources!')
