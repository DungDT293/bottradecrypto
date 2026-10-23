export interface BackendInfo {
  instance_id?: string;
  host: string;
  port: number;
  session_token: string;
  pid?: number;
  status: string;
}

export interface StandardErrorResponse {
  code: string;
  user_message: string;
  technical_details?: string;
  retryable: boolean;
  correlation_id: string;
}

export interface TelegramProfile {
  status: string;
  connected?: boolean;
  first_name?: string | null;
  username_masked?: string | null;
  phone_masked?: string | null;
  error?: string | null;
}

export interface TelegramCredentialsStatus {
  has_credentials: boolean;
  api_id_configured: boolean;
  api_hash_configured: boolean;
  status: string;
}

export interface TelegramLoginResponse {
  success: boolean;
  already_authorized?: boolean;
  auth_attempt_id?: string;
  phone_masked?: string;
  timeout_seconds?: number;
  needs_2fa?: boolean;
  first_name?: string;
  error?: string;
  error_code?: string;
}

export interface TelegramFolder {
  id: number;
  title: string;
  emoticon?: string;
  chat_ids: number[];
  pinned_chat_ids: number[];
  chat_count: number;
}

export interface TelegramDialog {
  id: number;
  title: string;
  is_channel: boolean;
  is_group: boolean;
  pinned: boolean;
  unread_count: number;
  folder_ids?: number[];
  folder_pinned_in?: number[];
}

export interface BinanceAccountSnapshot {
  connected?: boolean;
  is_connected?: boolean;
  mode: string;
  base_url: string;
  last_sync?: string;
  total_margin_balance?: string | null;
  equity?: string | null;
  wallet_balance?: string | null;
  available_balance?: string | null;
  total_unrealized_pnl?: string | null;
  unrealized_pnl?: string | null;
  total_maint_margin?: string | null;
  margin_ratio_pct?: string | null;
  open_positions_count: number;
  can_trade?: boolean;
}

export interface BenchmarkAccuracyData {
  test_cases: number;
  passed_cases: number;
  accuracy_pct: number;
  description: string;
}

export interface TelemetryData {
  messages_received: number;
  messages_processed: number;
  edit_events: number;
  signals_detected: number;
  signals_validated: number;
  signals_needs_review: number;
  needs_review: number;
  needs_policy: number;
  rejected_signals: number;
  active_signals: number;
  admin_updates: number;
  benchmark_accuracy?: BenchmarkAccuracyData;
}

export interface PnLSummary {
  period_label: string;
  start_time_vn: string;
  end_time_vn: string;
  has_data: boolean;
  realized_pnl?: string | null;
  commission?: string | null;
  funding_fee?: string | null;
  net_pnl?: string | null;
  total_closed_trades: number;
  win_count: number;
  loss_count: number;
  breakeven_count: number;
  win_rate_pct: number;
  data_completeness: string;
  last_sync_time?: string;
}

export interface TradeRecord {
  id: string;
  order_id?: string;
  symbol: string;
  side: string;
  price: string;
  qty: string;
  commission?: string | null;
  realized_pnl?: number | string | null;
  time: string;
  channel_name?: string | null;
  chat_id?: number | null;
}

export interface SignalRecord {
  signal_id: string;
  chat_id: number;
  message_id: number;
  symbol: string;
  side: "BUY" | "SELL" | "LONG" | "SHORT" | string;
  state: string;
  entry_mode: string;
  entries: string[];
  stop_loss?: string;
  take_profits: string[];
  leverage: number;
  margin_mode: MarginMode;
  risk_pct: string;
  channel_name?: string;
  source_type?: "AI" | "TELEGRAM" | string;
  blocking_reason?: string;
  telegram_timestamp?: string;
  created_at: string;
  updated_at?: string;
}

export interface TelegramMessageVersion {
  version: number;
  event_date: string;
  received_at: string;
  raw_text: string;
  is_edit: boolean | number;
  reply_to_msg_id?: number;
}

export interface TelegramChannelMessage {
  chat_id: number;
  message_id: number;
  sender_id?: number;
  telegram_timestamp: string;
  received_at: string;
  edit_timestamp?: string;
  raw_text: string;
  signal_id?: string;
  symbol?: string;
  side?: string;
  state?: string;
  entry_mode?: string;
  entries?: string[];
  stop_loss?: string;
  take_profits?: string[];
  leverage?: number;
  blocking_reason?: string;
  signal_created_at?: string;
  versions: TelegramMessageVersion[];
  has_edits: boolean;
}

export interface TelegramChannelMessagesResponse {
  success: boolean;
  chat_id: number;
  total: number;
  total_signals: number;
  validated_signals: number;
  rejected_signals: number;
  messages: TelegramChannelMessage[];
}

export interface PositionRecord {
  symbol: string;
  side: "LONG" | "SHORT";
  amount: string;
  entry_price: string;
  mark_price?: string;
  unrealized_pnl?: string;
  roe_pct?: string;
  initial_margin?: string;
  notional?: string;
  leverage: number;
  margin_type: string;
  sl_order_id?: string;
  sl_price?: string;
  tp_order_ids: string[];
  source_type?: "AI" | "TELEGRAM" | "MANUAL" | string;
  source_label?: string;
}

export interface OrderRecord {
  order_id: string;
  client_order_id?: string;
  symbol: string;
  side: "BUY" | "SELL";
  type: string;
  status: string;
  price: string;
  orig_qty: string;
  executed_qty: string;
  created_at: string;
}

export interface AlertRecord {
  id: string;
  level: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  message: string;
  source: string;
  timestamp: string;
  read: boolean;
}

export type ExecutionMode = "READ_ONLY" | "SHADOW" | "PAPER" | "TESTNET" | "LIVE";
export type MarginMode = "ISOLATED" | "CROSSED";
export type EntryRangePolicy = "BEST_PRICE" | "MID_POINT" | "SPLIT_2_LIMITS" | "NEEDS_POLICY";
export type MultiTPWeightMode =
  | "EXPLICIT"
  | "EQUAL_SPLIT"
  | "FRONT_LOADED_50_30_20"
  | "FIXED_20_40_40"
  | "FIXED_35_35_30"
  | "CUSTOM_TP1_RATIO"
  | "NEEDS_POLICY";

export interface AppSettings {
  mode: ExecutionMode;
  live_trading_enabled: boolean;
  risk_per_signal_pct: number;
  max_daily_loss_pct: number;
  max_leverage: number;
  margin_mode: MarginMode;
  entry_range_policy: EntryRangePolicy;
  multi_tp_default_weight_mode: MultiTPWeightMode;
  tp1_target_weight_pct?: number;
  breakeven_after_tp1?: boolean;
  sl_buffer_pct?: number;
  max_active_signals?: number;
}

export interface AppSnapshot {
  mode: string;
  live_trading_enabled: boolean;
  engine_status: string;
  entry_enabled: boolean;
  account: BinanceAccountSnapshot;
  telemetry: TelemetryData;
  pnl_today: PnLSummary;
  pnl_7d: PnLSummary;
  positions: PositionRecord[];
  orders: OrderRecord[];
  alerts: AlertRecord[];
  unread_alerts_count?: number;
}

export interface ChannelLeaderboardItem {
  rank: number;
  chat_id: number;
  channel_name: string;
  tier: "S" | "A" | "B" | "C" | "D" | "BLOCKED" | string;
  verdict: string;
  verdict_color: "success" | "primary" | "warning" | "error";
  badge_desc: string;
  is_blacklisted?: boolean;
  total_messages: number;
  total_signals: number;
  validated_signals: number;
  rejected_signals: number;
  needs_review_signals: number;
  quality_rate_pct: number;
  rejection_rate_pct: number;
  frequencies: {
    per_day: number;
    per_week: number;
    per_month: number;
    span_days: number;
  };
  performance: {
    total_trades: number;
    win_trades: number;
    loss_trades: number;
    win_rate_pct: number;
    loss_rate_pct: number;
    avg_risk_reward: number;
    gross_profit_usd: number;
    gross_loss_usd: number;
    net_pnl_usd: number;
    roi_pct: number;
    profit_factor: number;
  };
}

export interface ChannelLeaderboardSummary {
  total_channels?: number;
  total_pinned_channels: number;
  active_trading_channels: number;
  total_signals_validated: number;
  total_net_pnl_usd: number;
  overall_win_rate_pct: number;
  best_channel_name: string;
  best_channel_pnl: number;
  best_channel_winrate: number;
  worst_channel_name: string;
  worst_channel_rejection_rate: number;
}

export interface ChannelLeaderboardResponse {
  success: boolean;
  timeframe: string;
  bankroll_usd: number;
  margin_per_trade_pct?: number;
  margin_per_trade_usd?: number;
  summary: ChannelLeaderboardSummary;
  channels: ChannelLeaderboardItem[];
}

export interface ChannelDetailResponse {
  success: boolean;
  chat_id: number;
  channel_name: string;
  signal_count: number;
  signals: any[];
}

export interface LicenseInfo {
  is_active: boolean;
  status: "ACTIVE" | "EXPIRED" | "UNLICENSED" | "ERROR" | string;
  plan: string;
  days_remaining: number | null;
  expires_at: string | null;
  is_lifetime: boolean;
  hwid: string;
  message: string;
}

export interface AutoJoinResult {
  name: string;
  chat_id: number;
  status: "JOINED" | "ALREADY_JOINED" | "LINK_EXPIRED" | "RATE_LIMITED" | "ERROR" | string;
  message: string;
}

export interface AutoJoinResponse {
  success: boolean;
  joined_count: number;
  already_count: number;
  failed_count: number;
  total_channels: number;
  message: string;
  results: AutoJoinResult[];
}

export interface AISetup {
  has_setup: boolean;
  symbol: string;
  direction: "LONG" | "SHORT";
  confidence: number;
  bull_arguments?: string;
  bear_arguments?: string;
  risk_verdict?: string;
  rationale: string;
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  take_profit_3: number;
  estimated_rr?: number;
  source: string;
}

export interface AIStatusResponse {
  enabled: boolean;
  has_gemini_key: boolean;
  gemini_key_masked: string | null;
  preferred_model?: string;
  scan_interval_minutes: number;
  min_confidence: number;
  watchlist: string[];
  last_scan_time: string | null;
  last_scan_results: AISetup[];
  is_scanning: boolean;
  quota_status?: string;
  cooldown_remaining_seconds?: number;
  daily_api_calls?: number;
  last_scan_skipped_symbols?: string[];
  last_scan_symbol_validation_error?: string | null;
}

export interface AIConfigPayload {
  enabled?: boolean;
  gemini_api_key?: string;
  preferred_model?: string;
  scan_interval_minutes?: number;
  min_confidence?: number;
  watchlist?: string[];
}
