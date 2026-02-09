/**
 * Sonia Avatar State -- Zustand store (v2.6-c1 production-hardened)
 *
 * ACK model: control toggles are OPTIMISTIC with rollback.
 * Every toggle sets a pending state, sends command to backend via WS,
 * and either confirms on ACK or rolls back on NACK/timeout.
 *
 * State shape:
 *   - Connection (5-state: disconnected/connecting/connected/reconnecting/error)
 *   - Conversation (idle/listening/thinking/speaking)
 *   - Emotion + viseme + amplitude (driven by backend events)
 *   - Controls with pending flags (mic/cam/privacy/hold)
 *   - Diagnostics snapshot
 *   - Interrupt + replay status
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

export type ConversationState = "idle" | "listening" | "thinking" | "speaking";

export type Emotion =
  | "neutral"
  | "warm"
  | "stern"
  | "thinking"
  | "alert"
  | "amused"
  | "concerned";

export interface Viseme {
  id: string;
  weight: number;
  timestamp: number;
}

export interface LatencySnapshot {
  asr_ms: number;
  model_ms: number;
  tool_ms: number;
  memory_ms: number;
  total_ms: number;
  last_updated: number;
}

export interface DiagnosticsData {
  session_id: string | null;
  uptime_seconds: number;
  turn_count: number;
  latency: LatencySnapshot;
  breaker_states: Record<string, string>;
  dlq_depth: number;
  privacy_status: string;
  vision_buffer_frames: number;
  last_error: string | null;
  visible: boolean;
}

export interface PendingControl {
  field: string;
  targetValue: boolean;
  sentAt: number;
  timeoutMs: number;
}

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

export interface SoniaState {
  // Connection (5-state)
  connectionStatus: ConnectionStatus;
  sessionId: string | null;
  reconnectAttempts: number;
  lastConnectedAt: number | null;

  // Conversation
  conversationState: ConversationState;
  lastUserMessage: string;
  lastAssistantMessage: string;
  turnCount: number;

  // Expression
  emotion: Emotion;
  amplitude: number;
  currentViseme: Viseme | null;

  // Controls (with pending ACK tracking)
  micEnabled: boolean;
  camEnabled: boolean;
  privacyEnabled: boolean;
  holdActive: boolean;
  pendingControls: PendingControl[];

  // Interrupt / replay
  interruptPending: boolean;
  replayPending: boolean;

  // Diagnostics
  diagnostics: DiagnosticsData;

  // --- Actions: connection ---
  setConnectionStatus: (s: ConnectionStatus) => void;
  setSessionId: (id: string | null) => void;
  incrementReconnect: () => void;
  resetReconnect: () => void;
  markConnected: () => void;

  // --- Actions: conversation ---
  setConversationState: (s: ConversationState) => void;
  setLastUserMessage: (m: string) => void;
  setLastAssistantMessage: (m: string) => void;
  incrementTurn: () => void;

  // --- Actions: expression ---
  setEmotion: (e: Emotion) => void;
  setAmplitude: (a: number) => void;
  setViseme: (v: Viseme | null) => void;

  // --- Actions: controls (optimistic + ACK) ---
  requestToggleMic: () => PendingControl;
  requestToggleCam: () => PendingControl;
  requestTogglePrivacy: () => PendingControl;
  requestToggleHold: () => PendingControl;
  ackControl: (field: string) => void;
  nackControl: (field: string) => void;
  expirePendingControls: () => void;

  // --- Actions: interrupt / replay ---
  requestInterrupt: () => void;
  ackInterrupt: () => void;
  requestReplay: () => void;
  ackReplay: () => void;

  // --- Actions: diagnostics ---
  updateDiagnostics: (d: Partial<DiagnosticsData>) => void;
  toggleDiagnostics: () => void;
}

// ---------------------------------------------------------------------------
// Default diagnostics
// ---------------------------------------------------------------------------

const DEFAULT_DIAGNOSTICS: DiagnosticsData = {
  session_id: null,
  uptime_seconds: 0,
  turn_count: 0,
  latency: {
    asr_ms: 0,
    model_ms: 0,
    tool_ms: 0,
    memory_ms: 0,
    total_ms: 0,
    last_updated: 0,
  },
  breaker_states: {},
  dlq_depth: 0,
  privacy_status: "disabled",
  vision_buffer_frames: 0,
  last_error: null,
  visible: false,
};

const CONTROL_ACK_TIMEOUT_MS = 5000;

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useSoniaStore = create<SoniaState>((set, get) => ({
  // Initial state
  connectionStatus: "disconnected",
  sessionId: null,
  reconnectAttempts: 0,
  lastConnectedAt: null,

  conversationState: "idle",
  lastUserMessage: "",
  lastAssistantMessage: "",
  turnCount: 0,

  emotion: "neutral",
  amplitude: 0.0,
  currentViseme: null,

  micEnabled: true,
  camEnabled: false,
  privacyEnabled: false, // privacy OFF by default (matches backend)
  holdActive: false,
  pendingControls: [],

  interruptPending: false,
  replayPending: false,

  diagnostics: { ...DEFAULT_DIAGNOSTICS },

  // --- Connection ---
  setConnectionStatus: (s) => set({ connectionStatus: s }),
  setSessionId: (id) => set({ sessionId: id }),
  incrementReconnect: () =>
    set((s) => ({ reconnectAttempts: s.reconnectAttempts + 1 })),
  resetReconnect: () => set({ reconnectAttempts: 0 }),
  markConnected: () =>
    set({
      connectionStatus: "connected",
      reconnectAttempts: 0,
      lastConnectedAt: Date.now(),
    }),

  // --- Conversation ---
  setConversationState: (s) => set({ conversationState: s }),
  setLastUserMessage: (m) => set({ lastUserMessage: m }),
  setLastAssistantMessage: (m) => set({ lastAssistantMessage: m }),
  incrementTurn: () => set((s) => ({ turnCount: s.turnCount + 1 })),

  // --- Expression ---
  setEmotion: (e) => set({ emotion: e }),
  setAmplitude: (a) => set({ amplitude: Math.max(0, Math.min(1, a)) }),
  setViseme: (v) => set({ currentViseme: v }),

  // --- Controls: optimistic toggle + pending ACK ---
  requestToggleMic: () => {
    const s = get();
    const target = !s.micEnabled;
    const pending: PendingControl = {
      field: "micEnabled",
      targetValue: target,
      sentAt: Date.now(),
      timeoutMs: CONTROL_ACK_TIMEOUT_MS,
    };
    set({
      micEnabled: target,
      pendingControls: [...s.pendingControls.filter((p) => p.field !== "micEnabled"), pending],
    });
    return pending;
  },

  requestToggleCam: () => {
    const s = get();
    const target = !s.camEnabled;
    const pending: PendingControl = {
      field: "camEnabled",
      targetValue: target,
      sentAt: Date.now(),
      timeoutMs: CONTROL_ACK_TIMEOUT_MS,
    };
    set({
      camEnabled: target,
      pendingControls: [...s.pendingControls.filter((p) => p.field !== "camEnabled"), pending],
    });
    return pending;
  },

  requestTogglePrivacy: () => {
    const s = get();
    const target = !s.privacyEnabled;
    const pending: PendingControl = {
      field: "privacyEnabled",
      targetValue: target,
      sentAt: Date.now(),
      timeoutMs: CONTROL_ACK_TIMEOUT_MS,
    };
    set({
      privacyEnabled: target,
      pendingControls: [...s.pendingControls.filter((p) => p.field !== "privacyEnabled"), pending],
    });
    return pending;
  },

  requestToggleHold: () => {
    const s = get();
    const target = !s.holdActive;
    const pending: PendingControl = {
      field: "holdActive",
      targetValue: target,
      sentAt: Date.now(),
      timeoutMs: CONTROL_ACK_TIMEOUT_MS,
    };
    set({
      holdActive: target,
      pendingControls: [...s.pendingControls.filter((p) => p.field !== "holdActive"), pending],
    });
    return pending;
  },

  ackControl: (field) => {
    set((s) => ({
      pendingControls: s.pendingControls.filter((p) => p.field !== field),
    }));
  },

  nackControl: (field) => {
    // Rollback: revert the optimistic toggle
    const s = get();
    const pending = s.pendingControls.find((p) => p.field === field);
    if (pending) {
      set({
        [field]: !pending.targetValue,
        pendingControls: s.pendingControls.filter((p) => p.field !== field),
      } as any);
    }
  },

  expirePendingControls: () => {
    const now = Date.now();
    const s = get();
    const expired = s.pendingControls.filter(
      (p) => now - p.sentAt > p.timeoutMs
    );
    if (expired.length === 0) return;

    // Rollback all expired
    const rollbacks: Record<string, boolean> = {};
    for (const p of expired) {
      rollbacks[p.field] = !p.targetValue;
    }
    set({
      ...rollbacks,
      pendingControls: s.pendingControls.filter(
        (p) => now - p.sentAt <= p.timeoutMs
      ),
    } as any);
  },

  // --- Interrupt / replay ---
  requestInterrupt: () => set({ interruptPending: true }),
  ackInterrupt: () =>
    set({ interruptPending: false, conversationState: "idle" }),
  requestReplay: () => set({ replayPending: true }),
  ackReplay: () => set({ replayPending: false }),

  // --- Diagnostics ---
  updateDiagnostics: (d) =>
    set((s) => ({
      diagnostics: { ...s.diagnostics, ...d },
    })),
  toggleDiagnostics: () =>
    set((s) => ({
      diagnostics: { ...s.diagnostics, visible: !s.diagnostics.visible },
    })),
}));
