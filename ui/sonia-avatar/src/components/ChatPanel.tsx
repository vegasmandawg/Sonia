/**
 * ChatPanel -- v3.0 Conversation Interface
 *
 * Renders the message history and a text input for sending messages
 * to Sonia through the turn pipeline via WebSocket.
 */

import React, { useState, useRef, useEffect } from "react";
import { useSoniaStore } from "../state/store";
import type { ChatMessage } from "../state/store";
import { connectionManager } from "../state/connection";

// ---------------------------------------------------------------------------
// Styles (inline to avoid CSS tooling dep)
// ---------------------------------------------------------------------------

const PANEL_STYLE: React.CSSProperties = {
  position: "absolute",
  bottom: 72, // above ControlBar
  left: 16,
  right: 16,
  maxHeight: "50vh",
  display: "flex",
  flexDirection: "column",
  background: "rgba(10, 10, 20, 0.85)",
  backdropFilter: "blur(12px)",
  borderRadius: 12,
  border: "1px solid rgba(255, 255, 255, 0.08)",
  overflow: "hidden",
  fontFamily: "'Inter', 'Segoe UI', sans-serif",
  fontSize: 14,
  color: "#e0e0e0",
};

const MESSAGES_STYLE: React.CSSProperties = {
  flex: 1,
  overflowY: "auto",
  padding: "12px 16px",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const INPUT_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 8,
  padding: "8px 12px",
  borderTop: "1px solid rgba(255, 255, 255, 0.06)",
};

const INPUT_STYLE: React.CSSProperties = {
  flex: 1,
  background: "rgba(255, 255, 255, 0.06)",
  border: "1px solid rgba(255, 255, 255, 0.1)",
  borderRadius: 8,
  padding: "8px 12px",
  color: "#e0e0e0",
  fontSize: 14,
  outline: "none",
  fontFamily: "inherit",
};

const SEND_BTN_STYLE: React.CSSProperties = {
  background: "rgba(100, 140, 255, 0.25)",
  border: "1px solid rgba(100, 140, 255, 0.4)",
  borderRadius: 8,
  padding: "8px 16px",
  color: "#a0b8ff",
  fontSize: 14,
  cursor: "pointer",
  fontFamily: "inherit",
};

const SEND_BTN_DISABLED: React.CSSProperties = {
  ...SEND_BTN_STYLE,
  opacity: 0.4,
  cursor: "default",
};

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  const isError = msg.role === "error";

  const bubbleStyle: React.CSSProperties = {
    alignSelf: isUser ? "flex-end" : "flex-start",
    maxWidth: "80%",
    padding: "8px 12px",
    borderRadius: isUser ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
    background: isError
      ? "rgba(255, 80, 80, 0.15)"
      : isUser
      ? "rgba(100, 140, 255, 0.15)"
      : "rgba(255, 255, 255, 0.06)",
    border: isError
      ? "1px solid rgba(255, 80, 80, 0.3)"
      : "1px solid rgba(255, 255, 255, 0.04)",
    color: isError ? "#ff8080" : "#e0e0e0",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    lineHeight: 1.5,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: isError ? "#ff6060" : isUser ? "#8090c0" : "#80c080",
    marginBottom: 2,
    fontWeight: 600,
  };

  return (
    <div style={bubbleStyle}>
      <div style={labelStyle}>
        {isError ? "Error" : isUser ? "You" : "Sonia"}
      </div>
      {msg.text}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChatPanel
// ---------------------------------------------------------------------------

export default function ChatPanel() {
  const messages = useSoniaStore((s) => s.messages);
  const connectionStatus = useSoniaStore((s) => s.connectionStatus);
  const conversationState = useSoniaStore((s) => s.conversationState);

  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const connected = connectionStatus === "connected";
  const thinking = conversationState === "thinking" || conversationState === "speaking";
  const canSend = connected && !thinking && input.trim().length > 0;

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || !canSend) return;
    connectionManager.sendText(text);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={PANEL_STYLE}>
      {/* Message list */}
      <div style={MESSAGES_STYLE}>
        {messages.length === 0 && (
          <div style={{ color: "#666", textAlign: "center", padding: 24 }}>
            {connected
              ? "Type a message to start talking to Sonia."
              : "Connecting to backend..."}
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {thinking && (
          <div
            style={{
              alignSelf: "flex-start",
              color: "#80c080",
              fontSize: 13,
              padding: "4px 12px",
              fontStyle: "italic",
            }}
          >
            Sonia is thinking...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input row */}
      <div style={INPUT_ROW_STYLE}>
        <input
          style={INPUT_STYLE}
          type="text"
          placeholder={connected ? "Message Sonia..." : "Waiting for connection..."}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!connected}
        />
        <button
          style={canSend ? SEND_BTN_STYLE : SEND_BTN_DISABLED}
          onClick={handleSend}
          disabled={!canSend}
        >
          Send
        </button>
      </div>
    </div>
  );
}
