/**
 * DiagnosticsPanel -- v2.6-c1
 *
 * Slide-out panel showing real-time system diagnostics:
 *   - Session info
 *   - Latency breakdown (asr, model, tool, memory, total)
 *   - Circuit breaker states
 *   - DLQ depth
 *   - Privacy / vision status
 *   - Last error
 *
 * Toggled via DX button in ControlBar.
 */

import React from "react";
import type { DiagnosticsData } from "../state/store";

const PANEL_STYLE: React.CSSProperties = {
  position: "absolute",
  top: 32,
  right: 0,
  bottom: 56,
  width: 280,
  background: "rgba(10, 10, 10, 0.95)",
  borderLeft: "1px solid #2a1010",
  padding: "12px 14px",
  overflowY: "auto",
  zIndex: 20,
  fontFamily: "monospace",
  fontSize: 11,
  color: "#999",
  lineHeight: 1.6,
};

const HEADING_STYLE: React.CSSProperties = {
  color: "#cc3333",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  marginTop: 12,
  marginBottom: 4,
  borderBottom: "1px solid #1a0808",
  paddingBottom: 2,
};

const ROW_STYLE: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  padding: "1px 0",
};

const VALUE_STYLE: React.CSSProperties = {
  color: "#ccc",
  textAlign: "right",
};

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={ROW_STYLE}>
      <span>{label}</span>
      <span style={VALUE_STYLE}>{value}</span>
    </div>
  );
}

function BreakerRow({ name, state }: { name: string; state: string }) {
  const color =
    state === "CLOSED"
      ? "#33cc33"
      : state === "OPEN"
      ? "#cc3333"
      : state === "HALF_OPEN"
      ? "#cc6633"
      : "#666";
  return (
    <div style={ROW_STYLE}>
      <span>{name}</span>
      <span style={{ color, fontWeight: "bold" }}>{state}</span>
    </div>
  );
}

interface Props {
  data: DiagnosticsData;
}

export default function DiagnosticsPanel({ data }: Props) {
  if (!data.visible) return null;

  const lat = data.latency;
  const breakerEntries = Object.entries(data.breaker_states);

  return (
    <div style={PANEL_STYLE}>
      <div style={{ ...HEADING_STYLE, marginTop: 0 }}>Session</div>
      <Row label="ID" value={data.session_id || "--"} />
      <Row label="Uptime" value={`${data.uptime_seconds.toFixed(0)}s`} />
      <Row label="Turns" value={data.turn_count} />

      <div style={HEADING_STYLE}>Latency (ms)</div>
      <Row label="ASR" value={lat.asr_ms.toFixed(0)} />
      <Row label="Model" value={lat.model_ms.toFixed(0)} />
      <Row label="Tool" value={lat.tool_ms.toFixed(0)} />
      <Row label="Memory" value={lat.memory_ms.toFixed(0)} />
      <Row
        label="Total"
        value={lat.total_ms.toFixed(0)}
      />

      <div style={HEADING_STYLE}>Circuit Breakers</div>
      {breakerEntries.length === 0 ? (
        <div style={{ color: "#555" }}>No breakers registered</div>
      ) : (
        breakerEntries.map(([name, state]) => (
          <BreakerRow key={name} name={name} state={state} />
        ))
      )}

      <div style={HEADING_STYLE}>Recovery</div>
      <Row label="DLQ Depth" value={data.dlq_depth} />

      <div style={HEADING_STYLE}>Vision</div>
      <Row label="Privacy" value={data.privacy_status} />
      <Row label="Buffer" value={`${data.vision_buffer_frames} frames`} />

      {data.last_error && (
        <>
          <div style={HEADING_STYLE}>Last Error</div>
          <div style={{ color: "#cc3333", wordBreak: "break-word" }}>
            {data.last_error}
          </div>
        </>
      )}
    </div>
  );
}
