// Wraps the engine's WebSocket event stream with auto-reconnect (the
// engine can restart independently of the webview, and a dropped socket
// must not require the user to reload the app).

import { engineWsUrl } from "./engineClient";
import type { WSMessage } from "../types/engine";

type Listener = (msg: WSMessage) => void;

class EngineSocket {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private reconnectDelay = 1000;
  private stopped = false;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async connect() {
    if (this.stopped || this.socket) return;
    const url = await engineWsUrl();
    const ws = new WebSocket(url);
    this.socket = ws;

    ws.onopen = () => {
      this.reconnectDelay = 1000;
    };
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        this.listeners.forEach((l) => l(msg));
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = () => {
      this.socket = null;
      if (!this.stopped) {
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
      }
    };
    ws.onerror = () => {
      ws.close();
    };
  }

  disconnect() {
    this.stopped = true;
    this.socket?.close();
    this.socket = null;
  }
}

export const engineSocket = new EngineSocket();
