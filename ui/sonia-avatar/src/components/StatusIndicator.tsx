/**
 * StatusIndicator -- Top-left overlay (v2.6-c1 production-hardened)
 *
 * Shows:
 *   - 5-state connection dot (disconnected/connecting/connected/reconnecting/error)
 *   - Reconnect attempt counter (when reconnecting)
 *   - Conversation state label
 *   - Emotion tag
 *   - Hold indicator
 */

import React from "react";
import type { ConnectionStatus, ConversationState, Emotion } from "../state/store";

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  disconnected: "#555",
  connecting: "#cc6633",
  connected: "#33cc33",
  reconnecting: "#cccc33",
  error: "#cc3333",
};

const CONV_LABELS: Record<ConversationState, string> = {
  idle: "idle",
  listening: "listening...",
  thinking: "thinking...",
  speaking: "speaking...",
};

interface Props {
  connectionStatus: ConnectionStatus;
  emotion: Emotion;
  conversationState: ConversationState;
  reconnectAttempts: number;
  holdActive: boolean;
}

export default function StatusIndicator({
  connectionStatus,
  emotion,
  conversationState,
  reconnectAttempts,
  holdActive,
}: Props) {
  const dotColor = STATUS_COLORS[connectionStatus];

  return (
    <div
      style={{
        position: "absolute",
        top: 40,
        left: 16,
        display: "flex",
        flexDirection: "column",
        gap: 4,
        zIndex: 10,
        pointerEvents: "none",
      }}
    >
      {/* Connection status */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: dotColor,
            boxShadow: `0 0 6px ${dotColor}`,
          }}
        />
        <span
          style={{
            fontSize: 11,
            color: "#888",
            letterSpacing: 1,
            textTransform: "uppercase",
          }}
        >
          {connectionStatus}
          {connectionStatus === "reconnecting" && reconnectAttempts > 0
            ? ` (${reconnectAttempts})`
            : ""}
        </span>
      </div>

      {/* Conversation state */}
      <span style={{ fontSize: 10, color: "#777", letterSpacing: 0.5 }}>
        {CONV_LABELS[conversationState]}
      </span>

      {/* Emotion */}
      <span style={{ fontSize: 10, color: "#666", letterSpacing: 0.5 }}>
        {emotion}
      </span>

      {/* Hold indicator */}
      {holdActive && (
        <span
          style={{
            fontSize: 10,
            color: "#cc6633",
            letterSpacing: 1,
            textTransform: "uppercase",
            fontWeight: "bold",
          }}
        >
          HOLD
        </span>
      )}
    </div>
  );
}
