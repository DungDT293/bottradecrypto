import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import type { AppSnapshot, AlertRecord, LicenseInfo } from "../types/api";
import { api } from "../services/api";
import { wsClient } from "../services/websocket";

export type NavTab =
  | "overview"
  | "connections"
  | "groups"
  | "leaderboard"
  | "signals"
  | "trading"
  | "history"
  | "stats"
  | "reviews"
  | "logs"
  | "settings";

export interface ToastMessage {
  id: string;
  type: "success" | "error" | "info" | "warning";
  text: string;
}

interface AppContextValue {
  tab: NavTab;
  setTab: (tab: NavTab) => void;
  snapshot: AppSnapshot | null;
  license: LicenseInfo | null;
  loading: boolean;
  httpConnected: boolean;
  wsConnected: boolean;
  connected: boolean;
  isStale: boolean;
  lastSyncTime: string | null;
  error: string | null;
  refreshSnapshot: () => Promise<void>;
  refreshLicense: () => Promise<void>;
  isLicenseModalOpen: boolean;
  setIsLicenseModalOpen: (open: boolean) => void;
  openLicenseModal: () => void;
  closeLicenseModal: () => void;
  toasts: ToastMessage[];
  addToast: (text: string, type?: "success" | "error" | "info" | "warning") => void;
  removeToast: (id: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [tab, setTab] = useState<NavTab>("overview");
  const [snapshot, setSnapshot] = useState<AppSnapshot | null>(null);
  const [license, setLicense] = useState<LicenseInfo | null>(null);
  const [isLicenseModalOpen, setIsLicenseModalOpen] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [httpConnected, setHttpConnected] = useState<boolean>(false);
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [lastSyncTime, setLastSyncTime] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const openLicenseModal = useCallback(() => setIsLicenseModalOpen(true), []);
  const closeLicenseModal = useCallback(() => setIsLicenseModalOpen(false), []);

  const refreshLicense = useCallback(async () => {
    try {
      const lic = await api.getLicenseStatus();
      setLicense(lic);
    } catch {
      // License check failed or backend unavailable
    }
  }, []);

  const addToast = useCallback((text: string, type: "success" | "error" | "info" | "warning" = "info") => {
    setToasts((prev) => {
      // Deduplicate identical active toasts to prevent spamming
      if (prev.some((t) => t.text === text)) {
        return prev;
      }
      const id = Math.random().toString(36).substring(2, 9);
      setTimeout(() => {
        setToasts((curr) => curr.filter((t) => t.id !== id));
      }, 5000);
      return [...prev, { id, type, text }];
    });
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const refreshSnapshot = useCallback(async () => {
    try {
      const [snapRes, licRes] = await Promise.allSettled([
        api.getSnapshot(),
        api.getLicenseStatus(),
      ]);

      if (snapRes.status === "fulfilled") {
        setSnapshot(snapRes.value);
        setHttpConnected(true);
        setError(null);
        setLastSyncTime(new Date().toLocaleTimeString("vi-VN"));
      } else {
        throw snapRes.reason;
      }

      if (licRes.status === "fulfilled") {
        setLicense(licRes.value);
      }
    } catch (err: any) {
      // Light health check fallback to distinguish between network failure and server issue
      try {
        await api.getHealth();
        setHttpConnected(true);
      } catch {
        setHttpConnected(false);
      }
      setError(err?.user_message || err?.message || "Không thể kết nối với dịch vụ backend.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    refreshSnapshot();

    // Connect WebSocket
    wsClient.connect();

    // Subscribe to WebSocket events
    const unsubscribe = wsClient.subscribe((event) => {
      if (event.event_type === "ws_status") {
        setWsConnected(event.payload.connected);
      } else if (
        event.event_type === "backend_status_changed" ||
        event.event_type === "binance_status_changed" ||
        event.event_type === "signal_updated" ||
        event.event_type === "stats_updated"
      ) {
        refreshSnapshot();
      } else if (event.event_type === "license_updated") {
        refreshLicense();
      } else if (event.event_type === "alert_added") {
        const alert = event.payload as AlertRecord;
        addToast(`${alert.title}: ${alert.message}`, alert.level === "CRITICAL" ? "error" : "warning");
        refreshSnapshot();
      }
    });

    // Periodic polling as fallback (every 8 seconds)
    const interval = setInterval(() => {
      refreshSnapshot();
    }, 8000);

    return () => {
      unsubscribe();
      clearInterval(interval);
      wsClient.disconnect();
    };
  }, [refreshSnapshot, refreshLicense, addToast]);

  return (
    <AppContext.Provider
      value={{
        tab,
        setTab,
        snapshot,
        license,
        loading,
        httpConnected,
        wsConnected,
        connected: httpConnected,
        isStale: !httpConnected && Boolean(snapshot),
        lastSyncTime,
        error,
        refreshSnapshot,
        refreshLicense,
        isLicenseModalOpen,
        setIsLicenseModalOpen,
        openLicenseModal,
        closeLicenseModal,
        toasts,
        addToast,
        removeToast,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used within an AppProvider");
  }
  return context;
};
