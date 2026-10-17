import type { BackendInfo } from "../types/api";

let cachedInfo: BackendInfo | null = null;
let pendingPromise: Promise<BackendInfo> | null = null;

export async function getBackendInfo(forceRefresh = false): Promise<BackendInfo> {
  if (cachedInfo && !forceRefresh) {
    return cachedInfo;
  }

  if (pendingPromise) {
    return pendingPromise;
  }

  pendingPromise = (async () => {
    // 1. Try Tauri invoke with retries
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      let attempts = 0;
      const maxAttempts = 20; // 20 * 500ms = 10s wait for Python bind
      let lastError: any = null;

      while (attempts < maxAttempts) {
        attempts++;
        try {
          const info = await invoke<BackendInfo>("get_backend_info");
          if (info && info.port && info.session_token && info.status === "READY") {
            cachedInfo = info;
            return info;
          }
        } catch (err: any) {
          lastError = err;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
      }

      if (lastError) {
        console.warn("Tauri get_backend_info timeout or error:", lastError);
      }
    } catch {
      // Outside Tauri desktop shell
    }

    // 2. Fallback only for standalone web browser development
    const isBrowser =
      typeof window !== "undefined" &&
      !(window as any).__TAURI_INTERNALS__ &&
      !(window as any).__TAURI__;

    if (isBrowser) {
      try {
        const port = window.location.port ? parseInt(window.location.port) : 8000;
        const host = window.location.hostname || "127.0.0.1";
        const resp = await fetch(`http://${host}:${port}/api/handshake`);
        if (resp.ok) {
          const data = await resp.json();
          cachedInfo = {
            host: data.host || host,
            port: data.port || port,
            session_token: data.session_token || "dev_insecure_token",
            status: "READY",
          };
          return cachedInfo;
        }
      } catch (err) {
        console.warn("Could not fetch /api/handshake, using defaults:", err);
      }

      const envPort = import.meta.env.VITE_BACKEND_PORT
        ? parseInt(import.meta.env.VITE_BACKEND_PORT)
        : window.location.port
        ? parseInt(window.location.port)
        : 8000;
      const envToken = import.meta.env.VITE_SESSION_TOKEN || "dev_insecure_token";

      cachedInfo = {
        host: "127.0.0.1",
        port: envPort,
        session_token: envToken,
        status: "READY",
      };

      return cachedInfo;
    }

    throw new Error(
      "Backend Python chưa sẵn sàng sau quá trình khởi động. Vui lòng kiểm tra khay hệ thống hoặc khởi động lại ứng dụng."
    );
  })().finally(() => {
    pendingPromise = null;
  });

  return pendingPromise;
}

export function clearBackendCache(): void {
  cachedInfo = null;
}

