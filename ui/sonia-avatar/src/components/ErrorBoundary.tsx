/**
 * ErrorBoundary -- Catches React render errors and shows a fallback UI.
 */

import React, { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("[ErrorBoundary] Uncaught render error:", error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: "#0a0a0a",
            color: "#cc3333",
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
            gap: 16,
            padding: 32,
          }}
        >
          <div style={{ fontSize: 20, fontWeight: 600 }}>Something went wrong</div>
          <div style={{ fontSize: 13, color: "#888", maxWidth: 400, textAlign: "center" }}>
            {this.state.error?.message || "An unexpected error occurred in the UI."}
          </div>
          <button
            onClick={this.handleRetry}
            style={{
              marginTop: 8,
              padding: "8px 20px",
              background: "rgba(204, 51, 51, 0.15)",
              border: "1px solid #cc3333",
              borderRadius: 8,
              color: "#cc3333",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
