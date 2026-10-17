import { getBackendInfo, clearBackendCache } from "./backendBridge";

export type EventCallback = (event: { event_type: string; payload: any; timestamp?: string }) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private listeners: Set<EventCallback> = new Set();
  private reconnectTimer: any = null;
  private pingInterval: any = null;
  private isIntentionalClose = false;
  private isAuthenticated = false;

  public async connect(): Promise<void> {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      const backend = await getBackendInfo();
      // Invariant: Do NOT put session token in query string or URL
      const wsUrl = `ws://${backend.host}:${backend.port}/ws`;

      this.ws = new WebSocket(wsUrl);
      this.isIntentionalClose = false;
      this.isAuthenticated = false;

      this.ws.onopen = () => {
        // Send First-Message Ticket Authentication immediately
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: "AUTH", token: backend.session_token }));
        }

        // Start ping heartbeat interval
        if (this.pingInterval) clearInterval(this.pingInterval);
        this.pingInterval = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN && this.isAuthenticated) {
            this.ws.send("ping");
          }
        }, 15000);
      };

      this.ws.onmessage = (event) => {
        if (event.data === "pong") return;
        try {
          const parsed = JSON.parse(event.data);
          if (parsed.event_type === "AUTH_SUCCESS") {
            this.isAuthenticated = true;
            this.listeners.forEach((l) => l({ event_type: "ws_status", payload: { connected: true } }));
          }

          this.listeners.forEach((listener) => {
            try {
              listener(parsed);
            } catch (err) {
              console.error("Error in websocket listener:", err);
            }
          });
        } catch {
          // Non-JSON message ignored
        }
      };

      this.ws.onclose = () => {
        this.isAuthenticated = false;
        this.listeners.forEach((l) => l({ event_type: "ws_status", payload: { connected: false } }));
        if (this.pingInterval) clearInterval(this.pingInterval);
        if (!this.isIntentionalClose) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        if (this.ws) {
          this.ws.close();
        }
      };
    } catch {
      clearBackendCache();
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, 2500);
  }

  public subscribe(callback: EventCallback): () => void {
    this.listeners.add(callback);
    return () => {
      this.listeners.delete(callback);
    };
  }

  public disconnect(): void {
    this.isIntentionalClose = true;
    this.isAuthenticated = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.pingInterval) clearInterval(this.pingInterval);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

export const wsClient = new WebSocketClient();
