import { getBackendInfo, clearBackendCache } from "./backendBridge";
import type {
  AppSnapshot,
  TelegramProfile,
  TelegramCredentialsStatus,
  TelegramLoginResponse,
  BinanceAccountSnapshot,
  SignalRecord,
  PositionRecord,
  OrderRecord,
  AlertRecord,
  AppSettings,
  StandardErrorResponse,
  TelegramDialog,
  TelegramFolder,
  ChannelLeaderboardResponse,
  ChannelDetailResponse,
  TelegramChannelMessagesResponse,
  LicenseInfo,
  AutoJoinResponse,
  AIStatusResponse,
  AISetup,
  AIConfigPayload,
  PnLSummary,
  TradeRecord,
  PnLChartResponse,
} from "../types/api";

export class ApiError extends Error {
  code: string;
  user_message: string;
  technical_details?: string;
  retryable: boolean;
  correlation_id: string;

  constructor(err: StandardErrorResponse) {
    super(err.user_message);
    this.code = err.code;
    this.user_message = err.user_message;
    this.technical_details = err.technical_details;
    this.retryable = err.retryable;
    this.correlation_id = err.correlation_id;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const backend = await getBackendInfo();
  const baseUrl = `http://${backend.host}:${backend.port}`;
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Session-Token": backend.session_token,
    ...(options.headers as Record<string, string>),
  };

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err: any) {
    clearBackendCache();
    const errMsg = err?.message || String(err);
    if (errMsg.includes("Failed to fetch")) {
      throw new Error(
        `Không thể kết nối đến dịch vụ Backend tại cổng ${backend.port}. Vui lòng kiểm tra tiến trình nền đang chạy.`
      );
    }
    throw err;
  }

  if (!response.ok) {
    let errPayload: any;
    try {
      errPayload = await response.json();
    } catch {
      throw new Error(`HTTP Error ${response.status}: ${response.statusText}`);
    }

    if (errPayload && errPayload.detail && typeof errPayload.detail === "object") {
      throw new ApiError(errPayload.detail as StandardErrorResponse);
    }
    throw new Error(errPayload?.detail || `Yêu cầu thất bại (${response.status})`);
  }

  return response.json();
}

export const api = {
  // 1. Health & Snapshot
  getHealth: () => request<{ status: string; mode: string; live_trading_enabled: boolean }>("/health"),
  getSnapshot: () => request<AppSnapshot>("/snapshot"),

  // 2. Telegram
  getTelegramProfile: () => request<TelegramProfile>("/telegram/profile"),
  getTelegramCredentialsStatus: () => request<TelegramCredentialsStatus>("/telegram/credentials-status"),
  updateTelegramCredentials: (api_id: number, api_hash: string) =>
    request<{ success: boolean; message: string }>("/telegram/credentials", {
      method: "POST",
      body: JSON.stringify({ api_id, api_hash }),
    }),
  telegramRequestCode: (phone: string) =>
    request<TelegramLoginResponse>("/telegram/login/request-code", {
      method: "POST",
      body: JSON.stringify({ phone }),
    }),
  telegramSubmitCode: (code: string, auth_attempt_id?: string, password_2fa?: string) =>
    request<TelegramLoginResponse>("/telegram/login/submit-code", {
      method: "POST",
      body: JSON.stringify({ code, auth_attempt_id, password_2fa }),
    }),
  getTelegramDialogs: (refresh: boolean = false) =>
    request<{ dialogs: TelegramDialog[]; folders: TelegramFolder[]; allowed_chat_ids: number[] }>(
      `/telegram/dialogs${refresh ? "?refresh=true" : ""}`
    ),
  updateTelegramAllowlist: (allowed_chat_ids: number[]) => request<{ success: boolean; allowed_chat_ids: number[] }>("/telegram/allowlist", {
    method: "POST",
    body: JSON.stringify({ allowed_chat_ids }),
  }),
  collectTelegramHistory: (chat_id: number, days = 7, limit = 1000) => request<{ success: boolean; count: number; signals_detected?: number; signals_validated?: number; updates_recorded?: number }>("/telegram/collect-history", {
    method: "POST",
    body: JSON.stringify({ chat_id, days, limit }),
  }),
  cancelTelegramCollection: () => request<{ success: boolean }>("/telegram/cancel-collection", { method: "POST" }),
  telegramLogout: () => request<{ success: boolean }>("/telegram/logout", { method: "POST" }),
  getChannelMessages: (chatId: number, limit = 50, offset = 0, onlySignals = false) =>
    request<TelegramChannelMessagesResponse>(
      `/telegram/channels/${chatId}/messages?limit=${limit}&offset=${offset}&only_signals=${onlySignals}`
    ),

  // 3. Binance
  getBinanceCredentialsStatus: () => request<{
    has_testnet_credentials: boolean;
    testnet_api_key_masked: string | null;
    has_live_credentials: boolean;
    live_api_key_masked: string | null;
    mode: string;
  }>("/binance/credentials-status"),
  updateBinanceCredentials: (data: {
    testnet_api_key?: string;
    testnet_api_secret?: string;
    live_api_key?: string;
    live_api_secret?: string;
  }) => request<{
    has_testnet_credentials: boolean;
    testnet_api_key_masked: string | null;
    has_live_credentials: boolean;
    live_api_key_masked: string | null;
    mode: string;
  }>("/binance/credentials", {
    method: "POST",
    body: JSON.stringify(data),
  }),
  getBinanceStatus: () => request<BinanceAccountSnapshot>("/binance/status"),
  removeBinanceCredentials: (target: "testnet" | "live" | "all") =>
    request<{
      has_testnet_credentials: boolean;
      testnet_api_key_masked: string | null;
      has_live_credentials: boolean;
      live_api_key_masked: string | null;
      mode: string;
    }>(`/binance/credentials/remove?target=${target}`, {
      method: "POST",
    }),
  testBinanceConnection: (targetMode?: string) =>
    request<{ success: boolean; message?: string; error?: string; equity?: number; base_url?: string; target_mode?: string }>(
      `/binance/test-connection${targetMode ? `?target_mode=${targetMode}` : ""}`,
      { method: "POST" }
    ),
  syncBinanceAccount: () => request<BinanceAccountSnapshot>("/binance/sync", { method: "POST" }),


  // 4. Signals
  getSignals: (state?: string, symbol?: string, limit = 200) => {
    const params = new URLSearchParams();
    if (state) params.append("state", state);
    if (symbol) params.append("symbol", symbol);
    params.append("limit", limit.toString());
    return request<SignalRecord[]>(`/signals?${params.toString()}`);
  },
  getSignalDetail: (signal_id: string) => request<any>(`/signals/${signal_id}`),
  resolveSignal: (signal_id: string, new_state: string, reason: string) => request<{ success: boolean; signal_id: string; new_state: string }>(`/signals/${signal_id}/resolve`, {
    method: "POST",
    body: JSON.stringify({ new_state, reason }),
  }),

  // 5. Trading
  getPositions: () => request<PositionRecord[]>("/trading/positions"),
  getOrders: () => request<OrderRecord[]>("/trading/orders"),
  closePosition: (symbol: string) => request<{ success: boolean; symbol: string; message: string }>("/trading/close-position", {
    method: "POST",
    headers: {
      "X-Confirm-Live": "CONFIRM_CLOSE_POSITION",
    },
    body: JSON.stringify({ symbol }),
  }),
  closeAllBotPositions: () => request<{ success: boolean; message: string }>("/trading/close-all-bot", {
    method: "POST",
    headers: {
      "X-Confirm-Live": "CONFIRM_CLOSE_POSITION",
    },
  }),
  toggleEntry: (enabled: boolean) => request<{ success: boolean; entry_enabled: boolean }>("/trading/toggle-entry", {
    method: "POST",
    body: JSON.stringify({ entry_enabled: enabled }),
  }),
  toggleFerrariMode: (enabled: boolean) => request<{ success: boolean; ferrari_mode_enabled: boolean; message: string }>("/trading/toggle-ferrari-mode", {
    method: "POST",
    body: JSON.stringify({ ferrari_mode_enabled: enabled }),
  }),
  getTradeHistory: (limit = 100, daysBack = 0) => {
    const params = new URLSearchParams({ limit: String(limit), days_back: String(daysBack) });
    return request<TradeRecord[]>(`/trading/trades?${params.toString()}`);
  },

  // 6. Statistics
  getPnL: (daysBack = 0) => request<PnLSummary>(`/stats/pnl?days_back=${encodeURIComponent(daysBack)}`),
  getPnLChart: () => request<PnLChartResponse>("/stats/pnl-chart"),
  getCoinPnL: (daysBack = 0) => request<{ success: boolean; coins: any[] }>(`/stats/coins?days_back=${encodeURIComponent(daysBack)}`),
  syncPnL: () => request<{ success: boolean; message: string; details?: any }>("/stats/sync", { method: "POST" }),
  getTelemetry: () => request<any>("/stats/telemetry"),

  // 7. Alerts
  getAlerts: (limit = 50) => request<AlertRecord[]>(`/alerts?limit=${limit}`),
  markAllAlertsRead: () => request<{ success: boolean; marked_count: number }>("/alerts/mark-all-read", { method: "POST" }),

  // 8. Settings
  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (settings: AppSettings, confirmLive?: string) => {
    const headers: Record<string, string> = {};
    if (confirmLive) {
      headers["X-Confirm-Live"] = confirmLive;
    }
    return request<{ success: boolean; settings: AppSettings }>("/settings", {
      method: "POST",
      headers,
      body: JSON.stringify(settings),
    });
  },

  // 9. Lifecycle
  exitApplication: async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("exit_application");
    } catch {
      // Fallback in browser
      window.close();
    }
  },

  // 10. Channel Leaderboard & Performance
  getChannelLeaderboard: (timeframe = "all", bankroll?: number, marginPct?: number) => {
    const params = new URLSearchParams({ timeframe });
    if (bankroll !== undefined && bankroll !== null) params.append("bankroll", bankroll.toString());
    if (marginPct !== undefined && marginPct !== null) params.append("margin_pct", marginPct.toString());
    return request<ChannelLeaderboardResponse>(`/channels/leaderboard?${params.toString()}`);
  },
  getChannelDetail: (chatId: number) => request<ChannelDetailResponse>(`/channels/${chatId}/detail`),

  // 11. Commercial License & Auto-Join
  getLicenseStatus: () => request<LicenseInfo>("/license/status"),
  activateLicense: (key: string) => request<{ success: boolean; message: string; license: LicenseInfo }>("/license/activate", {
    method: "POST",
    body: JSON.stringify({ key }),
  }),
  activateTrial: () => request<{ success: boolean; message: string; license?: LicenseInfo }>("/license/trial", {
    method: "POST",
  }),
  autoJoinEliteChannels: () => request<AutoJoinResponse>("/telegram/auto-join-elite", {
    method: "POST",
  }),
  getPublicIp: () => request<{ ip: string; success: boolean }>("/system/public-ip"),

  // 12. Gemini Autonomous AI & Quant Trader
  getAIStatus: () => request<AIStatusResponse>("/ai/status"),
  updateAIConfig: (cfg: AIConfigPayload) => request<{
    success: boolean;
    enabled: boolean;
    has_gemini_key: boolean;
    gemini_key_masked: string | null;
    scan_interval_minutes: number;
    min_confidence: number;
    watchlist: string[];
  }>("/ai/config", {
    method: "POST",
    body: JSON.stringify(cfg),
  }),
  scanAIMarket: () => request<{
    success: boolean;
    count: number;
    setups: AISetup[];
    timestamp: string;
    message?: string;
  }>("/ai/scan-now", {
    method: "POST",
  }),
  executeAISetup: (setup: AISetup) => request<{
    success: boolean;
    result?: any;
    reason?: string;
  }>("/ai/execute-setup", {
    method: "POST",
    body: JSON.stringify({ setup }),
  }),

  // 13. Market Regime & Smart Queue (Trụ Cột 1 & 6)
  getMarketRegime: () => request<{
    status: string;
    btc_price: number;
    btc_4h_ema20: number;
    btc_4h_ema50: number;
    btc_1h_rsi: number;
    reason: string;
    timestamp: number;
  }>("/market-regime"),
  getSmartQueue: () => request<{
    items: Array<{
      signal_id: string;
      symbol: string;
      side: string;
      chat_id: number;
      channel_name: string;
      priority: number;
      enqueued_at: number;
      remaining_seconds: number;
    }>;
    count: number;
  }>("/trading/smart-queue"),
  getCapitalStage: () => request<{
    stage: number;
    label: string;
    current_equity: number;
    max_positions: number;
    recommended_risk_pct: number;
    max_total_risk_pct: number;
    target_equity: number;
    progress_pct: number;
    mission: string;
  }>("/capital-stage"),
};
