type MessageCallback = (data: unknown) => void;

interface WSMessage {
  type: string;
  data: unknown;
}

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private subscribers = new Map<string, Set<MessageCallback>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url: string;
  private intentionallyClosed = false;

  constructor(url = "ws://localhost:8000/ws/dashboard") {
    this.url = url;
  }

  // ---------------------------------------------------------------------------
  // Connection lifecycle
  // ---------------------------------------------------------------------------

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const token = localStorage.getItem("token");
    const urlWithAuth = token ? `${this.url}?token=${token}` : this.url;

    this.intentionallyClosed = false;
    this.ws = new WebSocket(urlWithAuth);

    this.ws.onopen = () => {
      console.log("[WS] Connected");
      this.reconnectAttempts = 0;
      this.notifySubscribers("connection", { connected: true });
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        this.notifySubscribers(message.type, message.data);
      } catch {
        console.warn("[WS] Failed to parse message:", event.data);
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      console.log("[WS] Disconnected:", event.code, event.reason);
      this.notifySubscribers("connection", { connected: false });

      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      console.error("[WS] Connection error");
    };
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Reconnection with exponential backoff
  // ---------------------------------------------------------------------------

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("[WS] Max reconnect attempts reached");
      return;
    }

    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30_000);
    console.log(
      `[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  // ---------------------------------------------------------------------------
  // Pub / Sub
  // ---------------------------------------------------------------------------

  subscribe(type: string, callback: MessageCallback): () => void {
    if (!this.subscribers.has(type)) {
      this.subscribers.set(type, new Set());
    }
    this.subscribers.get(type)!.add(callback);

    // Return unsubscribe function
    return () => this.unsubscribe(type, callback);
  }

  unsubscribe(type: string, callback: MessageCallback): void {
    const subs = this.subscribers.get(type);
    if (subs) {
      subs.delete(callback);
      if (subs.size === 0) {
        this.subscribers.delete(type);
      }
    }
  }

  private notifySubscribers(type: string, data: unknown): void {
    const subs = this.subscribers.get(type);
    if (subs) {
      subs.forEach((cb) => {
        try {
          cb(data);
        } catch (err) {
          console.error(`[WS] Subscriber error for "${type}":`, err);
        }
      });
    }

    // Also notify wildcard subscribers
    const wildcardSubs = this.subscribers.get("*");
    if (wildcardSubs) {
      wildcardSubs.forEach((cb) => {
        try {
          cb({ type, data });
        } catch (err) {
          console.error("[WS] Wildcard subscriber error:", err);
        }
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Send
  // ---------------------------------------------------------------------------

  send(type: string, data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    } else {
      console.warn("[WS] Cannot send – not connected");
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();

export default wsManager;
