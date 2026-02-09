/**
 * StatusIndicator — Top-left overlay showing connection + emotion state
 */

import React from "react";
import type { ConnectionStatus, Emotion } from "../state/store";

const STATUS_COLORS: Record<ConnectionStatus, string> = {
  disconnected: "#555",
  connecting: "#cc6633",
  connected: "#33cc33",
  error: "#cc3333",
};

interface Props {
  connectionStatus: ConnectionStatus;
  emotion: Emotion;
}

export default function StatusIndicator({ connectionStatus, emotion }: Props) {
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
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: STATUS_COLORS[connectionStatus],
            boxShadow: `0 0 6px ${STATUS_COLORS[connectionStatus]}`,
          }}
        />
        <span style={{ fontSize: 11, color: "#888", letterSpacing: 1, textTransform: "uppercase" }}>
          {connectionStatus}
        </span>
      </div>
      <span style={{ fontSize: 10, color: "#666", letterSpacing: 0.5 }}>
        {emotion}
      </span>
    </div>
  );
}
