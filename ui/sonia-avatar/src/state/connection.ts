/**
 * Connection Manager -- v2.6-c1
 *
 * Manages WebSocket lifecycle with:
 *   - 5-state FSM (disconnected/connecting/connected/reconnecting/error)
 *   - Exponential backoff reconnect (1s -> 2s -> 4s -> 8s -> 16s cap)
 *   - Backend event dispatch into Zustand store
 *   - Outbound command envelope for controls, interrupt, replay
 *   - Pending ACK expiry timer
 *
 * Protocol contract (WS JSON messages):
 *   Inbound (backend -> UI):
 *     { type: "state.conversation", state: ConversationState }
 *     { type: "state.emotion", emotion: Emotion }
 *     { type: "state.amplitude", value: number }
 *     { type: "state.viseme", viseme: Viseme }
 *     { type: "ack.control", field: string }
 *     { type: "nack.control", field: string, reason?: string }
 *     { type: "ack.interrupt" }
 *     { type: "ack.replay" }
 *     { type: "turn.assistant", text: string }
 *     { type: "turn.user", text: string }
 *     { type: "diagnostics", data: Partial<DiagnosticsData> }
 *     { type: "session.created", session_id: string }
 *     { type: "error", message: string }
 *
 *   Outbound (UI -> backend):
 *     { type: "control.toggle", field: string, value: boolean }
 *     { type: "control.interrupt" }
 *     { type: "control.replay" }
 *     { type: "control.hold", active: boolean }
 */

import { useSoniaStore } from "./store";
import type { ConnectionStatus, Emotion, ConversationState, Viseme, DiagnosticsData } from "./store";

// ---------------------------------------------------------------------------
// Inbound message types (backend -> UI)
// ---------------------------------------------------------------------------

type InboundMessage =
  | { type: "session.created"; session_id?: string }
  | { type: "state.conversation"; state: string }
  | { type: "state.emotion"; emotion: string }
  | { type: "state.amplitude"; value?: number }
  | { type: "state.viseme"; viseme?: Viseme }
  | { type: "ack.control"; field: string }
  | { type: "nack.control"; field: string; reason?: string }
  | { type: "ack.interrupt" }
  | { type: "ack.replay" }
  | { type: "turn.assistant"; text?: string }
  | { type: "turn.user"; text?: string }
  | { type: "diagnostics"; data?: Partial<DiagnosticsData> }
  | { type: "error"; message?: string };

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const RECONNECT_BASE_MS = 1000;
const RECONNECT_CAP_MS = 16000;
const MAX_RECONNECT_ATTEMPTS = 20;
const ACK_EXPIRY_INTERVAL_MS = 1000;

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

class ConnectionManager {
  private ws: WebSocket | null = null;
  private wsUrl: string = "";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private ackExpiryTimer: ReturnType<typeof setInterval> | null = null;
  private intentionalClose = false;

  get status(): ConnectionStatus {
    return useSoniaStore.getState().connectionStatus;
  }

  /** Start connection to the backend WS. */
  connect(url: string): void {
    this.wsUrl = url;
    this.intentionalClose = false;
    this.doConnect();
    this.startAckExpiryTimer();
  }

  /** Gracefully close. */
  disconnect(): void {
    this.intentionalClose = true;
    this.clearReconnectTimer();
    this.stopAckExpiryTimer();
    if (this.ws) {
      this.ws.close(1000, "user_disconnect");
      this.ws = null;
    }
    useSoniaStore.getState().setConnectionStatus("disconnected");
  }

  /** Send a control toggle command. */
  sendControlToggle(field: string, value: boolean): void {
    this.send({ type: "control.toggle", field, value });
  }

  /** Send interrupt command. */
  sendInterrupt(): void {
    this.send({ type: "control.interrupt" });
  }

  /** Send replay command. */
  sendReplay(): void {
    this.send({ type: "control.replay" });
  }

  /** Send hold command. */
  sendHold(active: boolean): void {
    this.send({ type: "control.hold", active });
  }

  /** v3.0: Send user text message through the turn pipeline. */
  sendText(text: string): void {
    this.send({ type: "input.text", text });
  }

  // ---- internal ----

  private doConnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    const store = useSoniaStore.getState();
    const isReconnect = store.reconnectAttempts > 0;
    store.setConnectionStatus(isReconnect ? "reconnecting" : "connecting");

    try {
      this.ws = new WebSocket(this.wsUrl);
    } catch {
      store.setConnectionStatus("error");
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      const s = useSoniaStore.getState();
      s.markConnected();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg && typeof msg.type === "string") {
          this.handleMessage(msg as InboundMessage);
        }
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = (event) => {
      if (this.intentionalClose) {
        useSoniaStore.getState().setConnectionStatus("disconnected");
        return;
      }
      useSoniaStore.getState().setConnectionStatus("reconnecting");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose fires after onerror, reconnect handled there
    };
  }

  private handleMessage(msg: InboundMessage): void {
    const store = useSoniaStore.getState();

    switch (msg.type) {
      case "session.created":
        store.setSessionId(msg.session_id || null);
        break;

      case "state.conversation":
        store.setConversationState(msg.state as ConversationState);
        break;

      case "state.emotion":
        store.setEmotion(msg.emotion as Emotion);
        break;

      case "state.amplitude":
        store.setAmplitude(msg.value ?? 0);
        break;

      case "state.viseme":
        store.setViseme(msg.viseme || null);
        break;

      case "ack.control":
        store.ackControl(msg.field);
        break;

      case "nack.control":
        store.nackControl(msg.field);
        break;

      case "ack.interrupt":
        store.ackInterrupt();
        break;

      case "ack.replay":
        store.ackReplay();
        break;

      case "turn.assistant":
        store.setLastAssistantMessage(msg.text || "");
        store.addMessage("assistant", msg.text || "");
        store.incrementTurn();
        break;

      case "turn.user":
        store.setLastUserMessage(msg.text || "");
        store.addMessage("user", msg.text || "");
        break;

      case "diagnostics":
        store.updateDiagnostics(msg.data || {});
        break;

      case "error":
        store.updateDiagnostics({ last_error: msg.message || "unknown" });
        break;
    }
  }

  private send(msg: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    const store = useSoniaStore.getState();
    store.incrementReconnect();

    if (store.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      store.setConnectionStatus("error");
      store.updateDiagnostics({
        last_error: `Reconnect failed after ${MAX_RECONNECT_ATTEMPTS} attempts`,
      });
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, store.reconnectAttempts - 1),
      RECONNECT_CAP_MS
    );

    this.reconnectTimer = setTimeout(() => {
      this.doConnect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startAckExpiryTimer(): void {
    this.stopAckExpiryTimer();
    this.ackExpiryTimer = setInterval(() => {
      useSoniaStore.getState().expirePendingControls();
    }, ACK_EXPIRY_INTERVAL_MS);
  }

  private stopAckExpiryTimer(): void {
    if (this.ackExpiryTimer) {
      clearInterval(this.ackExpiryTimer);
      this.ackExpiryTimer = null;
    }
  }
}

/** Singleton connection manager. */
export const connectionManager = new ConnectionManager();
