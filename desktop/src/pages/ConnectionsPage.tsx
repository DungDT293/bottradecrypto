import React, { useState, useEffect, useCallback } from "react";
import {
  Send,
  CheckCircle2,
  Key,
  RefreshCw,
  LogOut,
  AlertTriangle,
  Lock,
  ShieldCheck,
  ArrowLeft,
  Settings,
  ExternalLink,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { api } from "../services/api";
import type { TelegramProfile, TelegramCredentialsStatus } from "../types/api";

export type TelegramLoginState =
  | "BACKEND_UNAVAILABLE"
  | "PHONE_INPUT"
  | "SENDING_CODE"
  | "CODE_REQUIRED"
  | "VERIFYING_CODE"
  | "PASSWORD_REQUIRED"
  | "VERIFYING_PASSWORD"
  | "AUTHORIZED"
  | "ERROR";

interface InlineError {
  code?: string;
  message: string;
  hint?: string;
}

export const ConnectionsPage: React.FC = () => {
  const { snapshot, refreshSnapshot, httpConnected, addToast } = useApp();

  // Telegram profile & credentials
  const [tgProfile, setTgProfile] = useState<TelegramProfile | null>(null);
  const [credentialsStatus, setCredentialsStatus] = useState<TelegramCredentialsStatus | null>(null);
  const [showApiConfig, setShowApiConfig] = useState<boolean>(false);
  const [apiIdInput, setApiIdInput] = useState<string>("");
  const [apiHashInput, setApiHashInput] = useState<string>("");
  const [savingCredentials, setSavingCredentials] = useState<boolean>(false);

  // Login state machine
  const [loginState, setLoginState] = useState<TelegramLoginState>("PHONE_INPUT");
  const [previousState, setPreviousState] = useState<TelegramLoginState | null>(null);
  const [inlineError, setInlineError] = useState<InlineError | null>(null);

  // Login credentials / session fields
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [password2FA, setPassword2FA] = useState("");
  const [authAttemptId, setAuthAttemptId] = useState<string | null>(null);
  const [phoneMasked, setPhoneMasked] = useState<string | null>(null);
  const [cooldownSeconds, setCooldownSeconds] = useState<number>(0);

  // Binance state
  const [binanceLoading, setBinanceLoading] = useState(false);
  const [binanceCredStatus, setBinanceCredStatus] = useState<{
    has_testnet_credentials: boolean;
    testnet_api_key_masked: string | null;
    has_live_credentials: boolean;
    live_api_key_masked: string | null;
    mode: string;
  } | null>(null);
  const [showBinanceConfig, setShowBinanceConfig] = useState(false);
  const [testnetKey, setTestnetKey] = useState("");
  const [testnetSecret, setTestnetSecret] = useState("");
  const [savingBinanceCreds, setSavingBinanceCreds] = useState(false);

  // Binance Live state
  const [showLiveBinanceConfig, setShowLiveBinanceConfig] = useState(false);
  const [liveKey, setLiveKey] = useState("");
  const [liveSecret, setLiveSecret] = useState("");
  const [savingLiveBinanceCreds, setSavingLiveBinanceCreds] = useState(false);

  // Cooldown countdown timer
  useEffect(() => {
    if (cooldownSeconds <= 0) return;
    const timer = setInterval(() => {
      setCooldownSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldownSeconds]);

  // Fetch status & profile
  const fetchStatusAndProfile = useCallback(async () => {
    if (!httpConnected && !snapshot) {
      setLoginState("BACKEND_UNAVAILABLE");
      return;
    }

    try {
      const [credStatus, profile, bnCreds] = await Promise.all([
        api.getTelegramCredentialsStatus().catch(() => null),
        api.getTelegramProfile().catch(() => null),
        api.getBinanceCredentialsStatus().catch(() => null),
      ]);

      if (bnCreds) {
        setBinanceCredStatus(bnCreds);
        if (!bnCreds.has_testnet_credentials) {
          setShowBinanceConfig(true);
        }
      }

      if (credStatus) {
        setCredentialsStatus(credStatus);
        if (!credStatus.has_credentials) {
          setShowApiConfig(true);
        }
      }

      if (profile) {
        setTgProfile(profile);
        if (profile.status === "CONNECTED" || profile.connected) {
          setLoginState("AUTHORIZED");
          setInlineError(null);
          return;
        }
      }
      if (snapshot?.engine_status === "RUNNING_LISTEN") {
        setLoginState("AUTHORIZED");
        setInlineError(null);
        return;
      }

      // If not authorized and currently in terminal/unconnected state, reset to phone input
      setLoginState((curr) => {
        if (curr === "BACKEND_UNAVAILABLE" || curr === "AUTHORIZED") {
          return "PHONE_INPUT";
        }
        return curr;
      });
    } catch {
      // Ignored
    }
  }, [httpConnected, snapshot]);

  useEffect(() => {
    fetchStatusAndProfile();
  }, [fetchStatusAndProfile]);

  // Handle saving API credentials
  const handleSaveCredentials = async () => {
    const parsedId = parseInt(apiIdInput.trim(), 10);
    const cleanHash = apiHashInput.trim();

    if (isNaN(parsedId) || parsedId <= 0) {
      setInlineError({
        code: "INVALID_API_ID",
        message: "TELEGRAM_API_ID phải là một số nguyên dương hợp lệ.",
        hint: "Đăng nhập https://my.telegram.org -> API development tools để lấy App api_id.",
      });
      return;
    }

    if (!cleanHash || cleanHash.length < 10) {
      setInlineError({
        code: "INVALID_API_HASH",
        message: "TELEGRAM_API_HASH không hợp lệ (chuỗi hex 32 ký tự).",
        hint: "Lấy App api_hash tại https://my.telegram.org.",
      });
      return;
    }

    setSavingCredentials(true);
    setInlineError(null);
    try {
      const res = await api.updateTelegramCredentials(parsedId, cleanHash);
      if (res.success) {
        addToast("Đã lưu cấu hình API Telegram thành công!", "success");
        setShowApiConfig(false);
        setApiIdInput("");
        setApiHashInput("");
        await fetchStatusAndProfile();
      }
    } catch (err: any) {
      const msg = err?.response?.user_message || err?.message || "Lỗi lưu cấu hình API Telegram.";
      setInlineError({ code: "SAVE_CONFIG_FAILED", message: msg });
    } finally {
      setSavingCredentials(false);
    }
  };

  // Helper: auto format phone suggestion
  const getPhoneSuggestion = (input: string): string | null => {
    const raw = input.trim().replace(/[\s-]/g, "");
    if (!raw) return null;
    if (raw.startsWith("+")) return null;
    if (raw.startsWith("0") && raw.length >= 9) {
      return `+84${raw.slice(1)}`;
    }
    if (raw.startsWith("84") && raw.length >= 10) {
      return `+${raw}`;
    }
    if (/^[1-9]\d{8,11}$/.test(raw)) {
      return `+84${raw}`;
    }
    return null;
  };

  const phoneSuggestion = getPhoneSuggestion(phone);

  // Step 1: Send OTP
  const handleSendCode = async () => {
    const cleanPhone = phone.trim().replace(/[\s-]/g, "");
    if (!cleanPhone) {
      setInlineError({
        code: "PHONE_EMPTY",
        message: "Vui lòng nhập số điện thoại Telegram.",
        hint: "Nhập số điện thoại kèm mã quốc gia (vd: +84393954568).",
      });
      return;
    }

    if (!cleanPhone.startsWith("+")) {
      setInlineError({
        code: "INVALID_PHONE_FORMAT",
        message: "Số điện thoại phải bắt đầu bằng mã quốc tế '+' (Ví dụ: +84393954568).",
        hint: phoneSuggestion ? `Gợi ý: bấm vào '${phoneSuggestion}' bên dưới ô nhập để tự động sửa.` : undefined,
      });
      return;
    }

    if (credentialsStatus && !credentialsStatus.has_credentials) {
      setShowApiConfig(true);
      setInlineError({
        code: "CONFIG_MISSING",
        message: "Chưa cấu hình API Telegram (api_id & api_hash).",
        hint: "Vui lòng nhập api_id và api_hash trong mục 'Cấu hình API Telegram' trước khi gửi mã.",
      });
      return;
    }

    setPreviousState(loginState);
    setLoginState("SENDING_CODE");
    setInlineError(null);

    try {
      const res = await api.telegramRequestCode(cleanPhone);
      if (res.already_authorized) {
        addToast("Phiên Telegram này đã được đăng nhập sẵn!", "info");
        setLoginState("AUTHORIZED");
        setInlineError(null);
        await fetchStatusAndProfile();
        await refreshSnapshot();
        return;
      }

      if (res.success) {
        setAuthAttemptId(res.auth_attempt_id || null);
        setPhoneMasked(res.phone_masked || cleanPhone);
        setCooldownSeconds(res.timeout_seconds || 60);
        setLoginState("CODE_REQUIRED");
        addToast("Mã xác thực Telegram đã được gửi đến ứng dụng của bạn.", "success");
      } else {
        throw new Error(res.error || "Gửi mã không thành công.");
      }
    } catch (err: any) {
      const code = err?.response?.code || err?.code || "SEND_CODE_FAILED";
      const message = err?.response?.user_message || err?.message || "Lỗi khi gửi mã đăng nhập Telegram.";
      let hint: string | undefined;

      if (code === "CONFIG_MISSING") {
        setShowApiConfig(true);
        hint = "Vui lòng điền App api_id và api_hash trong form cấu hình bên dưới.";
      } else if (code === "FLOOD_WAIT") {
        hint = "Telegram giới hạn gửi mã quá nhanh. Vui lòng thử lại sau vài phút.";
      } else if (code === "PHONE_NUMBER_INVALID") {
        hint = "Số điện thoại không hợp lệ hoặc chưa đăng ký tài khoản Telegram.";
      }

      setInlineError({ code, message, hint });
      setLoginState("ERROR");
    }
  };

  // Step 2: Submit OTP
  const handleSubmitCode = async () => {
    const cleanCode = otpCode.trim();
    if (!cleanCode) {
      setInlineError({
        code: "CODE_EMPTY",
        message: "Vui lòng nhập mã OTP nhận được trong ứng dụng Telegram.",
      });
      return;
    }

    setPreviousState(loginState);
    setLoginState("VERIFYING_CODE");
    setInlineError(null);

    try {
      const res = await api.telegramSubmitCode(cleanCode, authAttemptId || undefined, undefined);

      if (res.needs_2fa) {
        setAuthAttemptId(res.auth_attempt_id || authAttemptId);
        setLoginState("PASSWORD_REQUIRED");
        addToast("Tài khoản đã kích hoạt 2FA. Vui lòng nhập mật khẩu xác thực 2 bước.", "info");
        return;
      }

      if (res.success) {
        addToast("Đăng nhập Telegram thành công!", "success");
        setLoginState("AUTHORIZED");
        setOtpCode("");
        setPassword2FA("");
        setInlineError(null);
        await fetchStatusAndProfile();
        await refreshSnapshot();
      } else {
        throw new Error(res.error || "Xác thực mã thất bại.");
      }
    } catch (err: any) {
      const code = err?.response?.code || err?.code || "AUTH_CODE_FAILED";
      const message = err?.response?.user_message || err?.message || "Xác thực mã OTP thất bại.";
      let hint: string | undefined;

      if (code === "CODE_INVALID") {
        hint = "Mã xác thực không khớp. Vui lòng kiểm tra kỹ tin nhắn từ Telegram Service Notifications.";
      } else if (code === "CODE_EXPIRED") {
        hint = "Mã xác thực đã hết hạn. Vui lòng bấm 'Gửi lại mã mới'.";
      }

      setInlineError({ code, message, hint });
      setLoginState("ERROR");
    }
  };

  // Step 3: Submit 2FA Password
  const handleSubmit2FA = async () => {
    if (!password2FA) {
      setInlineError({
        code: "PASSWORD_EMPTY",
        message: "Vui lòng nhập mật khẩu bảo mật 2 lớp (2FA).",
      });
      return;
    }

    setPreviousState(loginState);
    setLoginState("VERIFYING_PASSWORD");
    setInlineError(null);

    try {
      const res = await api.telegramSubmitCode(otpCode.trim(), authAttemptId || undefined, password2FA);

      if (res.success) {
        addToast("Xác thực 2FA thành công! Đã đăng nhập Telegram.", "success");
        setLoginState("AUTHORIZED");
        setOtpCode("");
        setPassword2FA("");
        setInlineError(null);
        await fetchStatusAndProfile();
        await refreshSnapshot();
      } else {
        throw new Error(res.error || "Xác thực 2FA thất bại.");
      }
    } catch (err: any) {
      const code = err?.response?.code || err?.code || "PASSWORD_INVALID";
      const message = err?.response?.user_message || err?.message || "Mật khẩu 2FA không chính xác.";
      setInlineError({ code, message, hint: "Vui lòng kiểm tra lại mật khẩu Cloud Password của bạn trên Telegram." });
      setLoginState("ERROR");
    }
  };

  // Logout
  const handleTgLogout = async () => {
    try {
      await api.telegramLogout();
      addToast("Đã đăng xuất phiên Telegram thành công.", "info");
      setLoginState("PHONE_INPUT");
      setTgProfile(null);
      setAuthAttemptId(null);
      setPhoneMasked(null);
      setOtpCode("");
      setPassword2FA("");
      setInlineError(null);
      await fetchStatusAndProfile();
      await refreshSnapshot();
    } catch (err: any) {
      addToast(err?.response?.user_message || err?.message || "Lỗi khi đăng xuất.", "error");
    }
  };

  // Retry action from ERROR state
  const handleRetry = () => {
    setInlineError(null);
    if (previousState === "VERIFYING_PASSWORD") {
      setLoginState("PASSWORD_REQUIRED");
    } else if (previousState === "VERIFYING_CODE") {
      setLoginState("CODE_REQUIRED");
    } else {
      setLoginState("PHONE_INPUT");
    }
  };

  // Reset to change phone number
  const handleResetPhone = () => {
    setLoginState("PHONE_INPUT");
    setAuthAttemptId(null);
    setOtpCode("");
    setPassword2FA("");
    setInlineError(null);
  };

  // Binance actions
  const handleSaveBinanceCredentials = async () => {
    if (!testnetKey.trim() || !testnetSecret.trim()) {
      addToast("Vui lòng điền đầy đủ API Key và Secret Key của Testnet", "warning");
      return;
    }
    setSavingBinanceCreds(true);
    try {
      const res = await api.updateBinanceCredentials({
        testnet_api_key: testnetKey.trim(),
        testnet_api_secret: testnetSecret.trim(),
      });
      setBinanceCredStatus(res);
      addToast("Đã lưu khóa Binance Testnet API vào hệ thống!", "success");
      setTestnetKey("");
      setTestnetSecret("");
      setShowBinanceConfig(false);
      await handleTestBinance();
    } catch (err: any) {
      addToast(err?.message || "Lỗi khi lưu API Key Binance", "error");
    } finally {
      setSavingBinanceCreds(false);
    }
  };

  const handleSaveLiveBinanceCredentials = async () => {
    if (!liveKey.trim() || !liveSecret.trim()) {
      addToast("Vui lòng điền đầy đủ API Key và Secret Key của Binance Live", "warning");
      return;
    }
    setSavingLiveBinanceCreds(true);
    try {
      const res = await api.updateBinanceCredentials({
        live_api_key: liveKey.trim(),
        live_api_secret: liveSecret.trim(),
      });
      setBinanceCredStatus(res);
      addToast("Đã lưu khóa Binance Live API vào hệ thống!", "success");
      setLiveKey("");
      setLiveSecret("");
      setShowLiveBinanceConfig(false);
      await handleTestBinance();
    } catch (err: any) {
      addToast(err?.message || "Lỗi khi lưu Live API Key Binance", "error");
    } finally {
      setSavingLiveBinanceCreds(false);
    }
  };

  const handleTestTestnetBinance = async () => {
    setBinanceLoading(true);
    try {
      const res = await api.testBinanceConnection("TESTNET");
      if (res.success) {
        addToast(`Kết nối Testnet thành công! Số dư ví Demo: $${parseFloat(String(res.equity || 0)).toFixed(2)} USDT`, "success");
      } else {
        addToast(`Kiểm tra Testnet: ${res.error || res.message || "Thất bại"}`, "warning");
      }
    } catch (err: any) {
      addToast(err?.response?.user_message || err?.message || "Lỗi kiểm tra Testnet.", "error");
    } finally {
      setBinanceLoading(false);
    }
  };

  const handleTestLiveBinance = async () => {
    setBinanceLoading(true);
    try {
      const res = await api.testBinanceConnection("LIVE");
      if (res.success) {
        addToast(`Kết nối Binance Live thành công! Số dư ví Futures thật: $${parseFloat(String(res.equity || 0)).toFixed(2)} USDT`, "success");
      } else {
        addToast(`Kiểm tra Live: ${res.error || res.message || "Thất bại"}`, "warning");
      }
    } catch (err: any) {
      addToast(err?.response?.user_message || err?.message || "Lỗi kết nối Binance Live.", "error");
    } finally {
      setBinanceLoading(false);
    }
  };

  const handleTestBinance = async () => {
    setBinanceLoading(true);
    try {
      const res = await api.testBinanceConnection();
      if (res.success) {
        addToast("Kết nối Binance API thành công!", "success");
        try {
          await api.syncBinanceAccount();
        } catch {}
      } else {
        addToast(`Kiểm tra Binance: ${res.message || "Thất bại"}`, "warning");
      }
      await refreshSnapshot();
    } catch (err: any) {
      addToast(err?.response?.user_message || err?.message || "Lỗi kết nối Binance.", "error");
    } finally {
      setBinanceLoading(false);
    }
  };


  const handleSyncBinance = async () => {
    setBinanceLoading(true);
    try {
      await api.syncBinanceAccount();
      addToast("Đã đồng bộ số dư và thông tin vị thế từ Binance Futures.", "success");
      await refreshSnapshot();
    } catch (err: any) {
      addToast(err?.response?.user_message || err?.message || "Lỗi khi đồng bộ Binance.", "error");
    } finally {
      setBinanceLoading(false);
    }
  };

  const account = snapshot?.account;

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h2 style={{ fontSize: "20px", fontWeight: 700, color: "#fff" }}>Quản lý Kết nối</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
          Cấu hình phiên làm việc Telegram MTProto và liên kết API sàn Binance USD-M Futures.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
        {/* ========================================================= */}
        {/* TELEGRAM CARD                                             */}
        {/* ========================================================= */}
        <div className="card">
          <div className="card-title">
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>Tài khoản Telegram</span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowApiConfig(!showApiConfig)}
                title="Cấu hình API credentials Telegram"
                style={{ padding: "2px 8px", fontSize: "11px" }}
              >
                <Settings size={12} />
                <span>API Settings</span>
              </button>
            </div>

            {loginState === "AUTHORIZED" ? (
              <span className="badge badge-read-only">ĐÃ KẾT NỐI</span>
            ) : loginState === "BACKEND_UNAVAILABLE" ? (
              <span className="badge badge-live-off">BACKEND NGOẠI TUYẾN</span>
            ) : (
              <span className="badge badge-shadow">CHƯA ĐĂNG NHẬP</span>
            )}
          </div>

          {/* Collapsible API Credentials Configuration Card */}
          {showApiConfig && (
            <div
              style={{
                marginTop: "14px",
                padding: "14px",
                background: "rgba(30, 41, 59, 0.7)",
                borderRadius: "8px",
                border: "1px solid rgba(148, 163, 184, 0.2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                <span style={{ fontSize: "13px", fontWeight: 600, color: "#fff" }}>
                  Cấu hình Telegram API (api_id & api_hash)
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    color: credentialsStatus?.has_credentials ? "var(--color-success)" : "var(--color-warning)",
                  }}
                >
                  {credentialsStatus?.has_credentials ? "✓ Đã có trong .env" : "⚠ Chưa có trong .env"}
                </span>
              </div>

              <p style={{ fontSize: "11px", color: "var(--text-secondary)", marginBottom: "12px", lineHeight: "1.4" }}>
                Telegram yêu cầu tài khoản nhà phát triển để tạo phiên MTProto. Truy cập{" "}
                <a
                  href="https://my.telegram.org"
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--color-primary)", textDecoration: "underline" }}
                >
                  https://my.telegram.org <ExternalLink size={10} style={{ display: "inline" }} />
                </a>{" "}
                đăng nhập, vào <strong>API development tools</strong> để lấy App api_id và api_hash.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "10px", marginBottom: "10px" }}>
                <div>
                  <label className="form-label" style={{ fontSize: "11px" }}>App api_id (Số)</label>
                  <input
                    type="number"
                    className="form-input"
                    placeholder="vd: 20123456"
                    value={apiIdInput}
                    onChange={(e) => setApiIdInput(e.target.value)}
                    style={{ fontSize: "12px", padding: "6px 8px" }}
                  />
                </div>
                <div>
                  <label className="form-label" style={{ fontSize: "11px" }}>App api_hash (Chuỗi hex)</label>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="vd: 9a8b7c6d5e4f..."
                    value={apiHashInput}
                    onChange={(e) => setApiHashInput(e.target.value)}
                    style={{ fontSize: "12px", padding: "6px 8px" }}
                  />
                </div>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveCredentials}
                  disabled={savingCredentials || !apiIdInput || !apiHashInput}
                >
                  {savingCredentials ? "Đang lưu..." : "Lưu vào .env"}
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowApiConfig(false)}
                >
                  Đóng
                </button>
              </div>
            </div>
          )}

          {/* Persistent Inline Error Banner */}
          {inlineError && (
            <div
              style={{
                marginTop: "14px",
                padding: "12px",
                borderRadius: "6px",
                backgroundColor: "rgba(239, 68, 68, 0.12)",
                border: "1px solid rgba(239, 68, 68, 0.35)",
                color: "#fca5a5",
                fontSize: "12px",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                <AlertTriangle size={16} style={{ marginTop: "2px", flexShrink: 0, color: "#ef4444" }} />
                <div style={{ flex: 1 }}>
                  {inlineError.code && (
                    <span
                      style={{
                        fontWeight: 700,
                        fontSize: "11px",
                        background: "rgba(239, 68, 68, 0.25)",
                        padding: "1px 5px",
                        borderRadius: "3px",
                        marginRight: "6px",
                        color: "#fff",
                      }}
                    >
                      {inlineError.code}
                    </span>
                  )}
                  <span>{inlineError.message}</span>
                  {inlineError.hint && (
                    <div style={{ marginTop: "6px", color: "var(--text-secondary)", fontSize: "11px" }}>
                      💡 {inlineError.hint}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* STATE: BACKEND_UNAVAILABLE */}
          {loginState === "BACKEND_UNAVAILABLE" && (
            <div style={{ marginTop: "16px", padding: "16px", background: "rgba(239, 68, 68, 0.08)", borderRadius: "8px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#fca5a5", marginBottom: "6px" }}>
                <AlertTriangle size={16} />
                <strong style={{ fontSize: "13px" }}>Dịch vụ Backend chưa sẵn sàng</strong>
              </div>
              <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: 0 }}>
                Không thể kết nối đến backend HTTP API. Vui lòng kiểm tra tiến trình nền hoặc khởi động lại ứng dụng.
              </p>
            </div>
          )}

          {/* STATE: AUTHORIZED */}
          {loginState === "AUTHORIZED" && (
            <div style={{ marginTop: "16px" }}>
              <div style={{ marginBottom: "14px" }}>
                <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>Tên người dùng</div>
                <div style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>
                  {tgProfile?.first_name || "Telegram User"}
                </div>
              </div>

              <div style={{ marginBottom: "14px" }}>
                <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>Username (Đã ẩn)</div>
                <div className="mono" style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
                  {tgProfile?.username_masked || "—"}
                </div>
              </div>

              <div style={{ marginBottom: "20px" }}>
                <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>Số điện thoại (Đã ẩn)</div>
                <div className="mono" style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
                  {tgProfile?.phone_masked || phoneMasked || "—"}
                </div>
              </div>

              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleTgLogout}
                >
                  <LogOut size={14} />
                  <span>Đăng xuất phiên Telegram</span>
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => fetchStatusAndProfile()}
                  title="Kiểm tra lại trạng thái phiên"
                >
                  <RefreshCw size={13} />
                  <span>Làm mới</span>
                </button>
              </div>
            </div>
          )}

          {/* STATE: PHONE_INPUT */}
          {loginState === "PHONE_INPUT" && (
            <div style={{ marginTop: "16px" }}>
              <div className="form-group">
                <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>Số điện thoại Telegram</span>
                  <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>Định dạng quốc tế</span>
                </label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="+84393954568"
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value);
                    if (inlineError) setInlineError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && phone) {
                      handleSendCode();
                    }
                  }}
                />

                {/* Auto format suggestion badge */}
                {phoneSuggestion && (
                  <div style={{ marginTop: "6px", fontSize: "11px", color: "var(--text-secondary)" }}>
                    💡 Gợi ý định dạng:{" "}
                    <button
                      type="button"
                      onClick={() => {
                        setPhone(phoneSuggestion);
                        if (inlineError) setInlineError(null);
                      }}
                      style={{
                        background: "rgba(59, 130, 246, 0.2)",
                        border: "1px solid rgba(59, 130, 246, 0.4)",
                        color: "#60a5fa",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        cursor: "pointer",
                        fontWeight: 600,
                      }}
                    >
                      {phoneSuggestion} (Bấm để áp dụng)
                    </button>
                  </div>
                )}
              </div>

              <button
                className="btn btn-primary"
                onClick={handleSendCode}
                disabled={!phone.trim() || !httpConnected}
                title={!httpConnected ? "Backend chưa sẵn sàng" : undefined}
              >
                <Send size={14} />
                <span>Gửi mã đăng nhập OTP</span>
              </button>
            </div>
          )}

          {/* STATE: SENDING_CODE */}
          {loginState === "SENDING_CODE" && (
            <div style={{ marginTop: "24px", textAlign: "center", padding: "20px" }}>
              <RefreshCw size={24} className="spin" style={{ color: "var(--color-primary)", marginBottom: "10px" }} />
              <div style={{ fontSize: "14px", fontWeight: 600, color: "#fff" }}>
                Đang gửi yêu cầu mã OTP...
              </div>
              <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                Hệ thống đang kết nối máy chủ Telegram MTProto để gửi mã xác thực tới tài khoản của bạn.
              </p>
            </div>
          )}

          {/* STATE: CODE_REQUIRED */}
          {loginState === "CODE_REQUIRED" && (
            <div style={{ marginTop: "16px" }}>
              <div
                style={{
                  background: "rgba(59, 130, 246, 0.1)",
                  border: "1px solid rgba(59, 130, 246, 0.3)",
                  padding: "10px 12px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "#93c5fd",
                  marginBottom: "14px",
                }}
              >
                Mã xác thực 5-6 chữ số đã được gửi đến ứng dụng Telegram của số{" "}
                <strong>{phoneMasked || phone}</strong>.
              </div>

              <div className="form-group">
                <label className="form-label">Mã xác thực OTP từ Telegram</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="vd: 59381"
                  value={otpCode}
                  onChange={(e) => {
                    setOtpCode(e.target.value);
                    if (inlineError) setInlineError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && otpCode) {
                      handleSubmitCode();
                    }
                  }}
                  autoFocus
                />
              </div>

              <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                <button
                  className="btn btn-primary"
                  onClick={handleSubmitCode}
                  disabled={!otpCode.trim()}
                >
                  <Key size={14} />
                  <span>Xác nhận đăng nhập</span>
                </button>

                <button
                  className="btn btn-secondary"
                  onClick={handleSendCode}
                  disabled={cooldownSeconds > 0}
                  title={cooldownSeconds > 0 ? `Vui lòng đợi ${cooldownSeconds}s để gửi lại` : undefined}
                >
                  {cooldownSeconds > 0 ? `Gửi lại mã (${cooldownSeconds}s)` : "Gửi lại mã"}
                </button>

                <button
                  className="btn btn-secondary"
                  onClick={handleResetPhone}
                  style={{ color: "var(--text-muted)" }}
                >
                  Đổi số khác
                </button>
              </div>
            </div>
          )}

          {/* STATE: VERIFYING_CODE */}
          {loginState === "VERIFYING_CODE" && (
            <div style={{ marginTop: "24px", textAlign: "center", padding: "20px" }}>
              <RefreshCw size={24} className="spin" style={{ color: "var(--color-primary)", marginBottom: "10px" }} />
              <div style={{ fontSize: "14px", fontWeight: 600, color: "#fff" }}>
                Đang xác thực mã OTP...
              </div>
              <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                Đang gửi mã tới máy chủ Telegram để hoàn tất đăng nhập.
              </p>
            </div>
          )}

          {/* STATE: PASSWORD_REQUIRED */}
          {loginState === "PASSWORD_REQUIRED" && (
            <div style={{ marginTop: "16px" }}>
              <div
                style={{
                  background: "rgba(245, 158, 11, 0.1)",
                  border: "1px solid rgba(245, 158, 11, 0.3)",
                  padding: "10px 12px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  color: "#fcd34d",
                  marginBottom: "14px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600, marginBottom: "2px" }}>
                  <Lock size={14} /> Bảo mật 2 lớp (2FA) kích hoạt
                </div>
                Tài khoản Telegram của bạn đã bật mật khẩu 2 bước (Cloud Password). Vui lòng nhập mật khẩu để tiếp tục.
              </div>

              <div className="form-group">
                <label className="form-label">Mật khẩu xác thực 2 bước (2FA Password)</label>
                <input
                  type="password"
                  className="form-input"
                  placeholder="Nhập mật khẩu 2FA của bạn"
                  value={password2FA}
                  onChange={(e) => {
                    setPassword2FA(e.target.value);
                    if (inlineError) setInlineError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && password2FA) {
                      handleSubmit2FA();
                    }
                  }}
                  autoFocus
                />
              </div>

              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  className="btn btn-secondary"
                  onClick={() => setLoginState("CODE_REQUIRED")}
                >
                  <ArrowLeft size={14} />
                  <span>Quay lại</span>
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleSubmit2FA}
                  disabled={!password2FA}
                >
                  <ShieldCheck size={14} />
                  <span>Xác nhận mật khẩu 2FA</span>
                </button>
              </div>
            </div>
          )}

          {/* STATE: VERIFYING_PASSWORD */}
          {loginState === "VERIFYING_PASSWORD" && (
            <div style={{ marginTop: "24px", textAlign: "center", padding: "20px" }}>
              <RefreshCw size={24} className="spin" style={{ color: "var(--color-primary)", marginBottom: "10px" }} />
              <div style={{ fontSize: "14px", fontWeight: 600, color: "#fff" }}>
                Đang xác thực mật khẩu 2FA...
              </div>
              <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "4px" }}>
                Đang giải mã và xác thực phiên đăng nhập an toàn.
              </p>
            </div>
          )}

          {/* STATE: ERROR */}
          {loginState === "ERROR" && (
            <div style={{ marginTop: "16px" }}>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  className="btn btn-primary"
                  onClick={handleRetry}
                >
                  <RefreshCw size={14} />
                  <span>Thử lại</span>
                </button>

                <button
                  className="btn btn-secondary"
                  onClick={handleResetPhone}
                >
                  Đổi số điện thoại khác
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ========================================================= */}
        {/* BINANCE FUTURES CARD                                      */}
        {/* ========================================================= */}
        <div className="card">
          <div className="card-title">
            <span style={{ fontSize: "16px", fontWeight: 600, color: "#fff" }}>Sàn Binance Futures</span>
            {(account?.connected || account?.is_connected) ? (
              <span className="badge badge-read-only">ĐÃ KẾT NỐI</span>
            ) : (
              <span className="badge badge-shadow">CHƯA LIÊN KẾT</span>
            )}
          </div>

          <div style={{ marginTop: "16px" }}>
            <div style={{ marginBottom: "14px", fontSize: "13px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                Endpoint: <code className="mono">{account?.base_url || (snapshot?.mode === "LIVE" ? "https://fapi.binance.com" : "https://demo-fapi.binance.com")}</code>
              </div>
              <span className={`badge ${snapshot?.mode === "LIVE" ? "badge-live" : "badge-shadow"}`} style={{ fontSize: "11px" }}>
                Chế độ: {snapshot?.mode || "TESTNET"}
              </span>
            </div>

            {snapshot?.mode === "TESTNET" && binanceCredStatus?.has_live_credentials && (
              <div style={{
                background: "rgba(234, 179, 8, 0.1)",
                border: "1px solid rgba(234, 179, 8, 0.3)",
                borderRadius: "6px",
                padding: "8px 12px",
                marginBottom: "14px",
                fontSize: "12px",
                color: "#fde047",
              }}>
                💡 Bạn đã lưu Khóa Live thật. Để bot giao dịch tài khoản thật ($100), hãy chuyển sang <strong>LIVE</strong> trong trang <strong>Cài đặt</strong>.
              </div>
            )}

            {/* Cấu hình API Key */}
            <div style={{
              background: "var(--bg-input)",
              padding: "14px",
              borderRadius: "8px",
              marginBottom: "16px",
              border: "1px solid var(--border-color)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 600, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
                    <Key size={14} color="#f3ba2f" />
                    <span>Khóa API Testnet</span>
                  </div>
                  <div style={{ fontSize: "12px", marginTop: "2px" }}>
                    {binanceCredStatus === null ? (
                      <span style={{ color: "var(--text-muted)" }}>Đang tải cấu hình...</span>
                    ) : binanceCredStatus.has_testnet_credentials ? (
                      <span style={{ color: "#22c55e" }}>
                        Đã cấu hình: <code className="mono">{binanceCredStatus.testnet_api_key_masked}</code>
                      </span>
                    ) : (
                      <span style={{ color: "#eab308" }}>Chưa có API Key Testnet</span>
                    )}
                  </div>

                </div>
                <div style={{ display: "flex", gap: "6px" }}>
                  {binanceCredStatus?.has_testnet_credentials && (
                    <button
                      className="btn btn-secondary btn-sm"
                      style={{ padding: "5px 10px", fontSize: "11px", color: "#60a5fa", borderColor: "rgba(96, 165, 250, 0.4)" }}
                      onClick={handleTestTestnetBinance}
                      disabled={binanceLoading}
                      title="Kiểm tra kết nối và số dư ví Testnet Demo"
                    >
                      Thử Testnet
                    </button>
                  )}
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "5px 12px", fontSize: "12px" }}
                    onClick={() => setShowBinanceConfig(!showBinanceConfig)}
                  >
                    {showBinanceConfig ? "Ẩn" : binanceCredStatus?.has_testnet_credentials ? "Đổi khóa" : "Cấu hình"}
                  </button>
                </div>
              </div>


              {showBinanceConfig && (
                <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                      BINANCE_TESTNET_API_KEY
                    </label>
                    <input
                      type="text"
                      className="input"
                      style={{ width: "100%", fontSize: "12px" }}
                      placeholder="Dán API Key từ testnet.binancefuture.com..."
                      value={testnetKey}
                      onChange={(e) => setTestnetKey(e.target.value)}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                      BINANCE_TESTNET_API_SECRET
                    </label>
                    <input
                      type="password"
                      className="input"
                      style={{ width: "100%", fontSize: "12px" }}
                      placeholder="Dán API Secret Key..."
                      value={testnetSecret}
                      onChange={(e) => setTestnetSecret(e.target.value)}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "4px" }}>
                    <a
                      href="https://testnet.binancefuture.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: "12px", color: "#60a5fa", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none" }}
                    >
                      <ExternalLink size={12} />
                      <span>Lấy API Key Testnet miễn phí</span>
                    </a>
                    <button
                      className="btn btn-primary"
                      onClick={handleSaveBinanceCredentials}
                      disabled={savingBinanceCreds || !testnetKey.trim() || !testnetSecret.trim()}
                      style={{ padding: "6px 14px", fontSize: "12px" }}
                    >
                      {savingBinanceCreds ? "Đang lưu..." : "Lưu & Kiểm tra kết nối"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Cấu hình Live API Key (Tiền thật) */}
            <div style={{
              background: "var(--bg-input)",
              padding: "14px",
              borderRadius: "8px",
              marginBottom: "16px",
              border: "1px solid var(--border-color)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 600, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
                    <Key size={14} color="#ef4444" />
                    <span>Khóa API Live (Tài khoản thật Binance)</span>
                  </div>
                  <div style={{ fontSize: "12px", marginTop: "2px" }}>
                    {binanceCredStatus === null ? (
                      <span style={{ color: "var(--text-muted)" }}>Đang tải cấu hình...</span>
                    ) : binanceCredStatus.has_live_credentials ? (
                      <span style={{ color: "#22c55e" }}>
                        Đã cấu hình: <code className="mono">{binanceCredStatus.live_api_key_masked}</code>
                      </span>
                    ) : (
                      <span style={{ color: "#eab308" }}>Chưa cấu hình API Key Live</span>
                    )}
                  </div>

                </div>
                <div style={{ display: "flex", gap: "6px" }}>
                  {binanceCredStatus?.has_live_credentials && (
                    <button
                      className="btn btn-secondary btn-sm"
                      style={{ padding: "5px 10px", fontSize: "11px", color: "#22c55e", borderColor: "rgba(34, 197, 94, 0.4)" }}
                      onClick={handleTestLiveBinance}
                      disabled={binanceLoading}
                      title="Kiểm tra kết nối và số dư ví Live Futures thật"
                    >
                      Thử Live API
                    </button>
                  )}
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "5px 12px", fontSize: "12px" }}
                    onClick={() => setShowLiveBinanceConfig(!showLiveBinanceConfig)}
                  >
                    {showLiveBinanceConfig ? "Ẩn" : binanceCredStatus?.has_live_credentials ? "Đổi khóa" : "Cấu hình"}
                  </button>
                </div>
              </div>


              {showLiveBinanceConfig && (
                <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                      BINANCE_LIVE_API_KEY
                    </label>
                    <input
                      type="text"
                      className="input"
                      style={{ width: "100%", fontSize: "12px" }}
                      placeholder="Dán API Key tài khoản thật..."
                      value={liveKey}
                      onChange={(e) => setLiveKey(e.target.value)}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: "11px", color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
                      BINANCE_LIVE_API_SECRET
                    </label>
                    <input
                      type="password"
                      className="input"
                      style={{ width: "100%", fontSize: "12px" }}
                      placeholder="Dán Secret Key tài khoản thật..."
                      value={liveSecret}
                      onChange={(e) => setLiveSecret(e.target.value)}
                    />
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "4px" }}>
                    <a
                      href="https://www.binance.com/en/my/settings/api-management"
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: "12px", color: "#60a5fa", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none" }}
                    >
                      <ExternalLink size={12} />
                      <span>Quản lý API trên Binance (Bật quyền Futures)</span>
                    </a>
                    <button
                      className="btn btn-primary"
                      onClick={handleSaveLiveBinanceCredentials}
                      disabled={savingLiveBinanceCreds || !liveKey.trim() || !liveSecret.trim()}
                      style={{ padding: "6px 14px", fontSize: "12px" }}
                    >
                      {savingLiveBinanceCreds ? "Đang lưu..." : "Lưu Khóa Live API"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "18px" }}>
              <div style={{ background: "var(--bg-input)", padding: "10px", borderRadius: "6px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Số dư Ký quỹ</div>
                <div className="mono" style={{ fontSize: "15px", fontWeight: 700, color: "#fff" }}>
                  {(account?.connected || account?.is_connected) && (account?.total_margin_balance != null || account?.equity != null || account?.wallet_balance != null)
                    ? `$${parseFloat(String(account.total_margin_balance ?? account.equity ?? account.wallet_balance)).toFixed(2)}`
                    : "Chưa có dữ liệu"}
                </div>
              </div>

              <div style={{ background: "var(--bg-input)", padding: "10px", borderRadius: "6px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Khả dụng (Available)</div>
                <div className="mono" style={{ fontSize: "15px", fontWeight: 700, color: "#fff" }}>
                  {(account?.connected || account?.is_connected) && account?.available_balance != null
                    ? `$${parseFloat(String(account.available_balance)).toFixed(2)}`
                    : "Chưa có dữ liệu"}
                </div>
              </div>

              <div style={{ background: "var(--bg-input)", padding: "10px", borderRadius: "6px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Unrealized PnL</div>
                <div className="mono" style={{ fontSize: "15px", fontWeight: 700, color: "#fff" }}>
                  {(account?.connected || account?.is_connected) && (account?.total_unrealized_pnl != null || account?.unrealized_pnl != null)
                    ? `$${parseFloat(String(account.total_unrealized_pnl ?? account.unrealized_pnl)).toFixed(2)}`
                    : "Chưa có dữ liệu"}
                </div>
              </div>

              <div style={{ background: "var(--bg-input)", padding: "10px", borderRadius: "6px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Tỷ lệ Margin</div>
                <div className="mono" style={{ fontSize: "15px", fontWeight: 700, color: "#fff" }}>
                  {(account?.connected || account?.is_connected) && account?.margin_ratio_pct != null
                    ? `${parseFloat(String(account.margin_ratio_pct)).toFixed(2)}%`
                    : "Chưa có dữ liệu"}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                className="btn btn-secondary"
                onClick={handleTestBinance}
                disabled={binanceLoading || !httpConnected}
                title={!httpConnected ? "Backend chưa sẵn sàng" : undefined}
              >
                <CheckCircle2 size={14} />
                <span>{binanceLoading ? "Đang thử..." : "Kiểm tra kết nối"}</span>
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSyncBinance}
                disabled={binanceLoading || !httpConnected}
                title={!httpConnected ? "Backend chưa sẵn sàng" : undefined}
              >
                <RefreshCw size={14} className={binanceLoading ? "spin" : ""} />
                <span>Đồng bộ số dư</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
