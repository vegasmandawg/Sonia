/**
 * ControlBar -- Bottom operator controls (v2.6-c1 production-hardened)
 *
 * ACK model: toggles go through requestToggle* -> backend WS -> ack/nack.
 * Pending controls show a pulsing indicator. On NACK/timeout, the toggle
 * automatically reverts.
 *
 * Controls:
 *   MIC  -- toggle microphone (optimistic + ACK)
 *   CAM  -- toggle camera (optimistic + ACK)
 *   EYE  -- toggle privacy/vision (optimistic + ACK)
 *   HLD  -- hold conversation (optimistic + ACK)
 *   INT  -- interrupt / barge-in (fire-and-forget, ACK clears state)
 *   RPL  -- replay last response (fire-and-forget, ACK clears state)
 *   DX   -- toggle diagnostics panel
 */

import React from "react";
import { useSoniaStore } from "../state/store";
import { connectionManager } from "../state/connection";

const BAR_STYLE: React.CSSProperties = {
  position: "absolute",
  bottom: 0,
  left: 0,
  right: 0,
  height: 56,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 12,
  background: "rgba(10, 10, 10, 0.9)",
  borderTop: "1px solid #2a1010",
  padding: "0 16px",
  zIndex: 10,
};

const BTN_STYLE: React.CSSProperties = {
  width: 40,
  height: 40,
  borderRadius: 8,
  border: "1px solid #3a1515",
  background: "#1a0808",
  color: "#cc3333",
  fontSize: 16,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  transition: "background 0.15s, border-color 0.15s, opacity 0.15s",
  position: "relative",
};

const BTN_ACTIVE: React.CSSProperties = {
  ...BTN_STYLE,
  background: "#cc3333",
  color: "#0a0a0a",
  borderColor: "#cc3333",
};

const BTN_PENDING: React.CSSProperties = {
  ...BTN_STYLE,
  opacity: 0.6,
  cursor: "wait",
};

interface ControlButtonProps {
  label: string;
  active?: boolean;
  pending?: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
}

function ControlButton({ label, active, pending, disabled, onClick, title }: ControlButtonProps) {
  const style = pending
    ? BTN_PENDING
    : active
    ? BTN_ACTIVE
    : BTN_STYLE;

  return (
    <button
      style={{ ...style, ...(disabled ? { opacity: 0.3, cursor: "not-allowed" } : {}) }}
      onClick={() => !disabled && !pending && onClick()}
      title={pending ? `${title} (pending...)` : title}
      onMouseEnter={(e) => {
        if (!disabled && !pending) {
          (e.target as HTMLButtonElement).style.borderColor = "#cc3333";
        }
      }}
      onMouseLeave={(e) => {
        if (!active && !pending) {
          (e.target as HTMLButtonElement).style.borderColor = "#3a1515";
        }
      }}
    >
      {label}
      {pending && (
        <span
          style={{
            position: "absolute",
            top: 2,
            right: 2,
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "#cc6633",
            animation: "pulse 1s infinite",
          }}
        />
      )}
    </button>
  );
}

const DIVIDER: React.CSSProperties = {
  width: 1,
  height: 24,
  background: "#2a1010",
};

export default function ControlBar() {
  const micEnabled = useSoniaStore((s) => s.micEnabled);
  const camEnabled = useSoniaStore((s) => s.camEnabled);
  const privacyEnabled = useSoniaStore((s) => s.privacyEnabled);
  const holdActive = useSoniaStore((s) => s.holdActive);
  const pendingControls = useSoniaStore((s) => s.pendingControls);
  const interruptPending = useSoniaStore((s) => s.interruptPending);
  const replayPending = useSoniaStore((s) => s.replayPending);
  const connectionStatus = useSoniaStore((s) => s.connectionStatus);
  const diagnosticsVisible = useSoniaStore((s) => s.diagnostics.visible);
  const conversationState = useSoniaStore((s) => s.conversationState);

  const requestToggleMic = useSoniaStore((s) => s.requestToggleMic);
  const requestToggleCam = useSoniaStore((s) => s.requestToggleCam);
  const requestTogglePrivacy = useSoniaStore((s) => s.requestTogglePrivacy);
  const requestToggleHold = useSoniaStore((s) => s.requestToggleHold);
  const requestInterrupt = useSoniaStore((s) => s.requestInterrupt);
  const requestReplay = useSoniaStore((s) => s.requestReplay);
  const toggleDiagnostics = useSoniaStore((s) => s.toggleDiagnostics);

  const isConnected = connectionStatus === "connected";
  const isPending = (field: string) => pendingControls.some((p) => p.field === field);

  const makeToggle = (
    requestFn: () => { targetValue: boolean },
    sendFn: (value: boolean) => void
  ) => () => {
    const p = requestFn();
    sendFn(p.targetValue);
  };

  const handleToggleMic = makeToggle(requestToggleMic, (v) => connectionManager.sendControlToggle("micEnabled", v));
  const handleToggleCam = makeToggle(requestToggleCam, (v) => connectionManager.sendControlToggle("camEnabled", v));
  const handleTogglePrivacy = makeToggle(requestTogglePrivacy, (v) => connectionManager.sendControlToggle("privacyEnabled", v));
  const handleToggleHold = makeToggle(requestToggleHold, (v) => connectionManager.sendHold(v));

  const handleInterrupt = () => {
    requestInterrupt();
    connectionManager.sendInterrupt();
  };

  const handleReplay = () => {
    requestReplay();
    connectionManager.sendReplay();
  };

  // Interrupt only available when speaking or thinking
  const canInterrupt = isConnected && (conversationState === "speaking" || conversationState === "thinking");
  // Replay only when idle and we have a last message
  const canReplay = isConnected && conversationState === "idle";

  return (
    <div style={BAR_STYLE}>
      {/* Toggle controls (ACK model) */}
      <ControlButton
        label={micEnabled ? "MIC" : "MUT"}
        active={micEnabled}
        pending={isPending("micEnabled")}
        disabled={!isConnected}
        onClick={handleToggleMic}
        title={micEnabled ? "Mute microphone" : "Unmute microphone"}
      />
      <ControlButton
        label={camEnabled ? "CAM" : "---"}
        active={camEnabled}
        pending={isPending("camEnabled")}
        disabled={!isConnected}
        onClick={handleToggleCam}
        title={camEnabled ? "Disable camera" : "Enable camera"}
      />
      <ControlButton
        label={privacyEnabled ? "EYE" : "BLD"}
        active={privacyEnabled}
        pending={isPending("privacyEnabled")}
        disabled={!isConnected}
        onClick={handleTogglePrivacy}
        title={privacyEnabled ? "Privacy: vision enabled" : "Privacy: vision blocked"}
      />

      <div style={DIVIDER} />

      <ControlButton
        label={holdActive ? "RSM" : "HLD"}
        active={holdActive}
        pending={isPending("holdActive")}
        disabled={!isConnected}
        onClick={handleToggleHold}
        title={holdActive ? "Resume conversation" : "Hold conversation"}
      />
      <ControlButton
        label="INT"
        pending={interruptPending}
        disabled={!canInterrupt}
        onClick={handleInterrupt}
        title="Interrupt / barge in"
      />
      <ControlButton
        label="RPL"
        pending={replayPending}
        disabled={!canReplay}
        onClick={handleReplay}
        title="Replay last response"
      />

      <div style={DIVIDER} />

      <ControlButton
        label="DX"
        active={diagnosticsVisible}
        onClick={toggleDiagnostics}
        title="Toggle diagnostics panel"
      />
    </div>
  );
}
