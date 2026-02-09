/**
 * ControlBar — Bottom operator controls
 *
 * Minimalist dark red/black theme.
 * Controls: mic, cam, privacy indicator, hold, interrupt, replay last, diagnostics.
 */

import React from "react";
import { useSoniaStore } from "../state/store";

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
  transition: "background 0.15s, border-color 0.15s",
};

const BTN_ACTIVE: React.CSSProperties = {
  ...BTN_STYLE,
  background: "#cc3333",
  color: "#0a0a0a",
  borderColor: "#cc3333",
};

interface ControlButtonProps {
  label: string;
  active?: boolean;
  onClick: () => void;
  title: string;
}

function ControlButton({ label, active, onClick, title }: ControlButtonProps) {
  return (
    <button
      style={active ? BTN_ACTIVE : BTN_STYLE}
      onClick={onClick}
      title={title}
      onMouseEnter={(e) => {
        (e.target as HTMLButtonElement).style.borderColor = "#cc3333";
      }}
      onMouseLeave={(e) => {
        if (!active) (e.target as HTMLButtonElement).style.borderColor = "#3a1515";
      }}
    >
      {label}
    </button>
  );
}

export default function ControlBar() {
  const micEnabled = useSoniaStore((s) => s.micEnabled);
  const camEnabled = useSoniaStore((s) => s.camEnabled);
  const privacyEnabled = useSoniaStore((s) => s.privacyEnabled);
  const toggleMic = useSoniaStore((s) => s.toggleMic);
  const toggleCam = useSoniaStore((s) => s.toggleCam);
  const togglePrivacy = useSoniaStore((s) => s.togglePrivacy);

  return (
    <div style={BAR_STYLE}>
      <ControlButton
        label={micEnabled ? "MIC" : "MUT"}
        active={micEnabled}
        onClick={toggleMic}
        title={micEnabled ? "Mute microphone" : "Unmute microphone"}
      />
      <ControlButton
        label={camEnabled ? "CAM" : "---"}
        active={camEnabled}
        onClick={toggleCam}
        title={camEnabled ? "Disable camera" : "Enable camera"}
      />
      <ControlButton
        label={privacyEnabled ? "EYE" : "BLD"}
        active={privacyEnabled}
        onClick={togglePrivacy}
        title={privacyEnabled ? "Privacy: vision enabled" : "Privacy: vision blocked"}
      />

      <div style={{ width: 1, height: 24, background: "#2a1010" }} />

      <ControlButton
        label="HLD"
        onClick={() => console.log("hold")}
        title="Hold conversation"
      />
      <ControlButton
        label="INT"
        onClick={() => console.log("interrupt")}
        title="Interrupt / barge in"
      />
      <ControlButton
        label="RPL"
        onClick={() => console.log("replay last")}
        title="Replay last response"
      />
      <ControlButton
        label="DX"
        onClick={() => console.log("diagnostics snapshot")}
        title="Capture diagnostics snapshot"
      />
    </div>
  );
}
