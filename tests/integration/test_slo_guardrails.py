"""
v4.7 Epic C — C3 + C4: SLO Guardrails & Diagnostics Tests

C3 (recovery-exit-criteria):
  1. Sustained breach enters DEGRADED mode
  2. One-off spike does NOT trigger DEGRADED
  3. Recovery requires M consecutive healthy windows
  4. Breach during recovery resets to DEGRADED
  5. clear_to_recover flag is deterministic
  6. Recovery exit transitions back to NORMAL

C4 (slo-diagnostics-endpoint):
  7. slo_status() returns all required fields
  8. /v1/slo/status endpoint exists in main.py
"""

import sys
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from latency_budget import SLOGuardrails


class TestRecoveryExitCriteria:
    """C3: Recovery requires M consecutive healthy windows to exit_degrade."""

    def test_sustained_breach_enters_degraded(self):
        """N consecutive breach windows enter DEGRADED mode."""
        g = SLOGuardrails(breach_threshold=3, recover_threshold=2)
        violations = [{"stage": "model", "metric": "p95", "threshold": 5000, "actual": 6000}]

        # First 2 breaches: still NORMAL (below threshold)
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_NORMAL
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_NORMAL

        # Third breach: sustained -> DEGRADED
        mode = g.record_window(violations)
        assert mode == SLOGuardrails.MODE_DEGRADED
        assert g.current_mode == SLOGuardrails.MODE_DEGRADED

    def test_oneoff_spike_no_trigger(self):
        """A single breach followed by healthy does not trigger DEGRADED."""
        g = SLOGuardrails(breach_threshold=3, recover_threshold=2)
        violations = [{"stage": "total", "metric": "p95", "threshold": 8000, "actual": 9000}]

        g.record_window(violations)  # One breach
        g.record_window([])          # Healthy -> resets consecutive_breach
        g.record_window(violations)  # Another isolated breach

        assert g.current_mode == SLOGuardrails.MODE_NORMAL

    def test_recovery_requires_m_consecutive_healthy(self):
        """After DEGRADED, need M consecutive_healthy windows to return to NORMAL."""
        g = SLOGuardrails(breach_threshold=2, recover_threshold=3)
        violations = [{"stage": "model", "metric": "p95", "threshold": 5000, "actual": 7000}]

        # Enter DEGRADED
        g.record_window(violations)
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_DEGRADED

        # First healthy -> RECOVERING
        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_RECOVERING

        # Second healthy -> still RECOVERING (need 3)
        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_RECOVERING
        assert not g.clear_to_recover

        # Third healthy -> exit_degrade to NORMAL
        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_NORMAL
        assert g.clear_to_recover

    def test_breach_during_recovery_resets(self):
        """Breach during RECOVERING sends back to DEGRADED."""
        g = SLOGuardrails(breach_threshold=2, recover_threshold=3)
        violations = [{"stage": "model", "metric": "p95", "threshold": 5000, "actual": 6000}]

        # Enter DEGRADED
        g.record_window(violations)
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_DEGRADED

        # Start recovering
        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_RECOVERING

        # Breach during recovery -> back to DEGRADED
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_DEGRADED

    def test_clear_to_recover_deterministic(self):
        """clear_to_recover is False until M healthy windows are reached."""
        g = SLOGuardrails(breach_threshold=1, recover_threshold=2)
        violations = [{"stage": "total", "metric": "p99", "threshold": 10000, "actual": 15000}]

        g.record_window(violations)  # DEGRADED
        assert not g.clear_to_recover

        g.record_window([])  # RECOVERING, 1 healthy
        assert not g.clear_to_recover

        g.record_window([])  # 2 healthy -> clear
        assert g.clear_to_recover

    def test_full_degrade_recover_cycle(self):
        """Complete cycle: NORMAL -> DEGRADED -> RECOVERING -> NORMAL."""
        g = SLOGuardrails(breach_threshold=2, recover_threshold=2)
        violations = [{"stage": "model", "metric": "p95", "threshold": 5000, "actual": 8000}]

        assert g.current_mode == SLOGuardrails.MODE_NORMAL

        g.record_window(violations)
        g.record_window(violations)
        assert g.current_mode == SLOGuardrails.MODE_DEGRADED

        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_RECOVERING

        g.record_window([])
        assert g.current_mode == SLOGuardrails.MODE_NORMAL


class TestSLODiagnostics:
    """C4: slo_status() returns diagnostics fields."""

    def test_slo_status_returns_required_fields(self):
        """slo_status() includes current_mode, breach_history, time_in_degrade, degrade_reason, clear_to_recover."""
        g = SLOGuardrails(breach_threshold=2, recover_threshold=3)
        status = g.slo_status()

        required_fields = [
            "current_mode", "slo_mode", "breach_history",
            "time_in_degrade", "degrade_reason", "clear_to_recover",
            "consecutive_breach", "consecutive_healthy",
            "recovery_windows", "breach_threshold", "recover_threshold",
        ]
        for field in required_fields:
            assert field in status, f"Missing required field: {field}"

        assert status["current_mode"] == "normal"
        assert status["slo_mode"] == "normal"
        assert isinstance(status["breach_history"], list)
        assert isinstance(status["time_in_degrade"], (int, float))
        assert isinstance(status["clear_to_recover"], bool)

    def test_slo_endpoint_exists_in_main(self):
        """main.py defines /v1/slo/status route."""
        main_path = r"S:\services\api-gateway\main.py"
        with open(main_path) as f:
            src = f.read()
        assert "/v1/slo/status" in src or "slo/status" in src, "SLO status endpoint must exist"
        assert "slo_status" in src, "slo_status function must be referenced"
