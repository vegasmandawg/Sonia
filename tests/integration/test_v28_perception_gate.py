"""
v2.8 M3: Perception-to-Action Confirmed Assist

Tests that perception-driven actions are operationally impossible
to execute without confirmation.

Tests (22):
  ConfirmationRequirement (4):
    1. Default state is PENDING
    2. is_expired detects stale requirements
    3. to_dict produces JSON-serializable output
    4. Risk level assigned from PERCEPTION_ACTION_RISK

  PerceptionActionGate -- require/approve/deny (8):
    5. require_confirmation creates PENDING requirement
    6. approve transitions to APPROVED
    7. deny transitions to DENIED
    8. Approve expired requirement returns None
    9. Approve already-approved returns None (one-shot)
    10. Max pending limit enforced
    11. get_pending returns only PENDING requirements
    12. get_stats reflects approval/denial counts

  PerceptionActionGate -- validate_execution (6):
    13. validate_execution with approved requirement succeeds
    14. validate_execution with pending requirement raises bypass error
    15. validate_execution with denied requirement raises bypass error
    16. validate_execution with expired requirement raises bypass error
    17. validate_execution with unknown ID raises bypass error
    18. validate_execution marks as EXECUTED (one-shot)

  Integration / safety invariants (4):
    19. Full flow: perceive -> require -> approve -> execute
    20. Full flow: perceive -> require -> deny -> no execute
    21. Bypass attempt counter increments on violations
    22. Stress: 50 requirements, approve half, deny half, zero bypass
"""

import sys
import time
import json

import pytest

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")


# ===========================================================================
# ConfirmationRequirement tests
# ===========================================================================

class TestConfirmationRequirement:

    def test_default_state_pending(self):
        """Default state is PENDING."""
        from perception_action_gate import ConfirmationRequirement, RequirementState
        req = ConfirmationRequirement(requirement_id="test_1", action="file.read")
        assert req.state == RequirementState.PENDING
        assert req.is_pending

    def test_is_expired_detects_stale(self):
        """is_expired detects requirements past TTL."""
        from perception_action_gate import ConfirmationRequirement
        req = ConfirmationRequirement(
            requirement_id="test_2",
            action="shell.run",
            created_at=time.time() - 200,  # 200s ago
            ttl_seconds=120.0,
        )
        assert req.is_expired

    def test_to_dict_serializable(self):
        """to_dict produces JSON-serializable output."""
        from perception_action_gate import ConfirmationRequirement
        req = ConfirmationRequirement(
            requirement_id="test_3",
            action="file.write",
            args={"path": "/tmp/test"},
            scene_id="scene_abc",
            session_id="sess_1",
            correlation_id="req_1",
            created_at=time.time(),
            risk_level="high",
        )
        d = req.to_dict()
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["requirement_id"] == "test_3"
        assert parsed["action"] == "file.write"
        assert parsed["risk_level"] == "high"

    def test_risk_level_from_classification(self):
        """Risk level assigned from PERCEPTION_ACTION_RISK."""
        from perception_action_gate import PERCEPTION_ACTION_RISK, DEFAULT_PERCEPTION_RISK
        assert PERCEPTION_ACTION_RISK["shell.run"] == "critical"
        assert PERCEPTION_ACTION_RISK["file.read"] == "medium"
        assert PERCEPTION_ACTION_RISK["keyboard.type"] == "critical"
        assert DEFAULT_PERCEPTION_RISK == "high"


# ===========================================================================
# PerceptionActionGate -- require/approve/deny
# ===========================================================================

class TestPerceptionActionGateBasic:

    def test_require_creates_pending(self):
        """require_confirmation creates PENDING requirement."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate()
        req = gate.require_confirmation(
            action="file.read",
            args={"path": "/tmp/x"},
            scene_id="scene_1",
        )
        assert req.is_pending
        assert req.requirement_id.startswith("pcr_")
        assert req.action == "file.read"
        assert req.risk_level == "medium"

    def test_approve_transitions(self):
        """approve transitions to APPROVED."""
        from perception_action_gate import PerceptionActionGate, RequirementState
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="file.read", scene_id="s1")
        approved = gate.approve(req.requirement_id)
        assert approved is not None
        assert approved.state == RequirementState.APPROVED
        assert approved.resolved_at > 0

    def test_deny_transitions(self):
        """deny transitions to DENIED."""
        from perception_action_gate import PerceptionActionGate, RequirementState
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="shell.run", scene_id="s2")
        denied = gate.deny(req.requirement_id, reason="too risky")
        assert denied is not None
        assert denied.state == RequirementState.DENIED
        assert denied.denial_reason == "too risky"

    def test_approve_expired_returns_none(self):
        """Approve expired requirement returns None."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate(ttl_seconds=0.01)  # Very short TTL
        req = gate.require_confirmation(action="file.read", scene_id="s3")
        time.sleep(0.02)
        result = gate.approve(req.requirement_id)
        assert result is None

    def test_approve_already_approved_returns_none(self):
        """Approve already-approved returns None (one-shot)."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="file.read", scene_id="s4")
        gate.approve(req.requirement_id)
        second = gate.approve(req.requirement_id)
        assert second is None  # Already resolved and archived

    def test_max_pending_enforced(self):
        """Max pending limit raises ConfirmationBypassError."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate()
        gate.MAX_PENDING = 5
        for i in range(5):
            gate.require_confirmation(action="file.read", scene_id=f"scene_{i}")
        with pytest.raises(ConfirmationBypassError):
            gate.require_confirmation(action="file.read", scene_id="scene_overflow")

    def test_get_pending(self):
        """get_pending returns only PENDING requirements."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate()
        r1 = gate.require_confirmation(action="file.read", scene_id="s1", session_id="sess_a")
        r2 = gate.require_confirmation(action="shell.run", scene_id="s2", session_id="sess_a")
        r3 = gate.require_confirmation(action="file.write", scene_id="s3", session_id="sess_b")
        gate.approve(r1.requirement_id)

        pending_a = gate.get_pending(session_id="sess_a")
        assert len(pending_a) == 1  # Only r2 is still pending for sess_a

        pending_all = gate.get_pending()
        assert len(pending_all) == 2  # r2 and r3

    def test_stats_reflect_counts(self):
        """get_stats reflects approval/denial counts."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate()
        r1 = gate.require_confirmation(action="file.read", scene_id="s1")
        r2 = gate.require_confirmation(action="shell.run", scene_id="s2")
        r3 = gate.require_confirmation(action="file.write", scene_id="s3")
        gate.approve(r1.requirement_id)
        gate.deny(r2.requirement_id)

        stats = gate.get_stats()
        assert stats["total_approved"] == 1
        assert stats["total_denied"] == 1
        assert stats["pending_count"] == 1


# ===========================================================================
# PerceptionActionGate -- validate_execution
# ===========================================================================

class TestValidateExecution:

    def test_approved_succeeds(self):
        """validate_execution with approved requirement succeeds."""
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="file.read", scene_id="s1")
        gate.approve(req.requirement_id)
        validated = gate.validate_execution(req.requirement_id)
        assert validated.action == "file.read"

    def test_pending_raises_bypass(self):
        """validate_execution with PENDING requirement raises bypass error."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="shell.run", scene_id="s2")
        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.validate_execution(req.requirement_id)
        assert "pending" in exc_info.value.reason

    def test_denied_raises_bypass(self):
        """validate_execution with DENIED requirement raises bypass error."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="shell.run", scene_id="s3")
        gate.deny(req.requirement_id)
        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.validate_execution(req.requirement_id)
        assert "denied" in exc_info.value.reason

    def test_expired_raises_bypass(self):
        """validate_execution with expired requirement raises bypass error."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate(ttl_seconds=0.01)
        req = gate.require_confirmation(action="file.write", scene_id="s4")
        time.sleep(0.02)
        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.validate_execution(req.requirement_id)
        assert "expired" in exc_info.value.reason.lower()

    def test_unknown_id_raises_bypass(self):
        """validate_execution with unknown ID raises bypass error."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate()
        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.validate_execution("pcr_nonexistent")
        assert "not found" in exc_info.value.reason

    def test_execution_is_one_shot(self):
        """validate_execution marks as EXECUTED -- cannot reuse."""
        from perception_action_gate import (
            PerceptionActionGate, ConfirmationBypassError, RequirementState,
        )
        gate = PerceptionActionGate()
        req = gate.require_confirmation(action="file.read", scene_id="s5")
        gate.approve(req.requirement_id)
        validated = gate.validate_execution(req.requirement_id)
        assert validated.state == RequirementState.EXECUTED

        # Second attempt should fail -- already executed
        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)


# ===========================================================================
# Integration / safety invariants
# ===========================================================================

class TestPerceptionGateIntegration:

    def test_full_approve_flow(self):
        """Full flow: perceive -> require -> approve -> execute."""
        from perception_action_gate import PerceptionActionGate

        gate = PerceptionActionGate()

        # Step 1: Perception suggests action
        req = gate.require_confirmation(
            action="browser.open",
            args={"url": "https://example.com"},
            scene_id="scene_web",
            session_id="sess_1",
            correlation_id="req_flow1",
        )
        assert req.is_pending

        # Step 2: Operator approves
        approved = gate.approve(req.requirement_id)
        assert approved is not None
        assert approved.is_approved

        # Step 3: Execute with validation
        validated = gate.validate_execution(req.requirement_id)
        assert validated.action == "browser.open"
        assert validated.args["url"] == "https://example.com"

    def test_full_deny_flow(self):
        """Full flow: perceive -> require -> deny -> no execute."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError

        gate = PerceptionActionGate()

        req = gate.require_confirmation(
            action="keyboard.type",
            args={"text": "rm -rf /"},
            scene_id="scene_danger",
            correlation_id="req_flow2",
        )

        # Operator denies
        denied = gate.deny(req.requirement_id, reason="dangerous command")
        assert denied.is_denied

        # Attempting execution fails
        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)

    def test_bypass_counter_increments(self):
        """Bypass attempt counter increments on violations."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError

        gate = PerceptionActionGate()

        # Attempt 1: unknown ID
        try:
            gate.validate_execution("pcr_fake")
        except ConfirmationBypassError:
            pass

        # Attempt 2: pending
        req = gate.require_confirmation(action="shell.run", scene_id="s1")
        try:
            gate.validate_execution(req.requirement_id)
        except ConfirmationBypassError:
            pass

        stats = gate.get_stats()
        assert stats["bypass_attempts"] == 2

    def test_stress_50_requirements(self):
        """50 requirements: approve half, deny half, zero bypass."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError

        gate = PerceptionActionGate()
        reqs = []
        for i in range(50):
            req = gate.require_confirmation(
                action="file.read" if i % 2 == 0 else "shell.run",
                scene_id=f"scene_{i}",
                session_id="stress_sess",
            )
            reqs.append(req)

        # Approve even, deny odd
        for i, req in enumerate(reqs):
            if i % 2 == 0:
                gate.approve(req.requirement_id)
            else:
                gate.deny(req.requirement_id, reason="denied in test")

        # Validate approved ones
        for i, req in enumerate(reqs):
            if i % 2 == 0:
                validated = gate.validate_execution(req.requirement_id)
                assert validated.action == "file.read"
            else:
                with pytest.raises(ConfirmationBypassError):
                    gate.validate_execution(req.requirement_id)

        stats = gate.get_stats()
        assert stats["total_approved"] == 25
        assert stats["total_denied"] == 25
        assert stats["pending_count"] == 0
