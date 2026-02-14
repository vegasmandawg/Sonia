/**
 * App -- Root component (v2.6-c1 production-hardened)
 *
 * Wires:
 *   - 3D avatar scene (Canvas)
 *   - StatusIndicator (5-state connection, emotion, conversation, hold)
 *   - ControlBar (ACK model, interrupt, replay, diagnostics toggle)
 *   - DiagnosticsPanel (slide-out)
 *   - Connection manager auto-connect on mount
 */

import React, { useEffect } from "react";
import { Canvas } from "@react-three/fiber";
import AvatarScene from "./three/AvatarScene";
import ControlBar from "./components/ControlBar";
import ChatPanel from "./components/ChatPanel";
import StatusIndicator from "./components/StatusIndicator";
import DiagnosticsPanel from "./components/DiagnosticsPanel";
import ErrorBoundary from "./components/ErrorBoundary";
import { useSoniaStore } from "./state/store";
import { connectionManager } from "./state/connection";

declare global {
  interface Window {
    soniaAPI?: {
      getBackendWS: () => Promise<string>;
      minimize: () => Promise<void>;
      maximize: () => Promise<void>;
      close: () => Promise<void>;
    };
  }
}

const FALLBACK_WS = "ws://127.0.0.1:7000/v1/ui/stream";

export default function App() {
  const connectionStatus = useSoniaStore((s) => s.connectionStatus);
  const emotion = useSoniaStore((s) => s.emotion);
  const conversationState = useSoniaStore((s) => s.conversationState);
  const reconnectAttempts = useSoniaStore((s) => s.reconnectAttempts);
  const holdActive = useSoniaStore((s) => s.holdActive);
  const diagnostics = useSoniaStore((s) => s.diagnostics);

  // Auto-connect on mount
  useEffect(() => {
    const init = async () => {
      let wsUrl = FALLBACK_WS;
      if (window.soniaAPI) {
        try {
          wsUrl = await window.soniaAPI.getBackendWS();
        } catch {
          // fallback
        }
      }
      connectionManager.connect(wsUrl);
    };
    init();
    return () => {
      connectionManager.disconnect();
    };
  }, []);

  return (
    <ErrorBoundary>
      <div style={{ width: "100%", height: "100%", position: "relative" }}>
        {/* 3D Avatar */}
        <Canvas
          style={{ width: "100%", height: "100%" }}
          camera={{ position: [0, 0, 3], fov: 35 }}
          gl={{ antialias: true, alpha: true }}
        >
          <AvatarScene />
        </Canvas>

        {/* Status overlay */}
        <StatusIndicator
          connectionStatus={connectionStatus}
          emotion={emotion}
          conversationState={conversationState}
          reconnectAttempts={reconnectAttempts}
          holdActive={holdActive}
        />

        {/* Chat conversation panel */}
        <ChatPanel />

        {/* Diagnostics panel (slide-out) */}
        <DiagnosticsPanel data={diagnostics} />

        {/* Bottom control bar */}
        <ControlBar />
      </div>
    </ErrorBoundary>
  );
}
