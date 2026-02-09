"""
Stage 5 — test_action_plan_execute.py
Tests the action plan → validate → execute pipeline and approval flow.
"""

import sys
import httpx
import pytest

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"


@pytest.fixture
def client():
    return httpx.Client(base_url=GW, timeout=30)


# ── Capabilities ─────────────────────────────────────────────────────────────

def test_capabilities_endpoint(client):
    """GET /v1/capabilities returns 13+ capabilities with stats."""
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["stats"]["total"] >= 13
    assert data["stats"]["implemented"] >= 4


# ── Safe action immediate execution ──────────────────────────────────────────

def test_safe_action_executes_immediately(client):
    """file.read (safe) should plan+validate+execute in one call."""
    body = {
        "intent": "file.read",
        "params": {"path": r"S:\config\sonia-config.json"},
    }
    r = client.post("/v1/actions/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "succeeded"
    assert data["risk_level"] == "safe"
    assert data["requires_confirmation"] is False
    assert data["execution"]["success"] is True
    assert data["telemetry"]["total_ms"] > 0


# ── Guarded action gates to pending_approval ─────────────────────────────────

def test_guarded_action_pending_approval(client):
    """shell.run (medium) should stop at pending_approval."""
    body = {
        "intent": "shell.run",
        "params": {"command": "Get-ChildItem"},
    }
    r = client.post("/v1/actions/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["requires_confirmation"] is True
    assert data["risk_level"] == "medium"
    assert data.get("execution") is None


# ── Approve and execute ──────────────────────────────────────────────────────

def test_approve_executes_action(client):
    """Approving a pending action triggers execution."""
    # Plan guarded action
    body = {"intent": "shell.run", "params": {"command": "Get-ChildItem"}}
    plan = client.post("/v1/actions/plan", json=body).json()
    assert plan["state"] == "pending_approval"
    action_id = plan["action_id"]

    # Approve
    r = client.post(f"/v1/actions/{action_id}/approve")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "succeeded"
    assert data["execution"]["success"] is True


# ── Deny action ──────────────────────────────────────────────────────────────

def test_deny_action(client):
    """Denying a pending action sets state to denied."""
    body = {"intent": "file.write", "params": {"path": "S:\\tmp\\deny.txt", "content": "x"}}
    plan = client.post("/v1/actions/plan", json=body).json()
    assert plan["state"] == "pending_approval"
    action_id = plan["action_id"]

    r = client.post(f"/v1/actions/{action_id}/deny")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "denied"


# ── Dry run ──────────────────────────────────────────────────────────────────

def test_dry_run_validates_only(client):
    """dry_run=true should validate but not execute."""
    body = {
        "intent": "file.read",
        "params": {"path": r"S:\config\sonia-config.json"},
        "dry_run": True,
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "validated"
    assert data.get("execution") is None
    assert data["validation"]["valid"] is True


# ── Validation failures ──────────────────────────────────────────────────────

def test_unknown_intent_rejected(client):
    """Unknown intent should fail validation."""
    body = {"intent": "nonexistent.action", "params": {}}
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "VALIDATION_FAILED"
    assert "Unknown intent" in data["error"]["message"]


def test_missing_params_rejected(client):
    """Missing required params should fail validation."""
    body = {"intent": "file.read", "params": {}}
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "VALIDATION_FAILED"
    assert "Missing required" in data["error"]["message"]


def test_unimplemented_intent_rejected(client):
    """An intent that exists but is not implemented should fail validation."""
    body = {"intent": "app.launch", "params": {"target": "notepad.exe"}}
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is False
    assert "Not implemented" in data["error"]["message"]


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_idempotency_key(client):
    """Same idempotency_key returns same action_id."""
    body = {
        "intent": "file.read",
        "params": {"path": r"S:\config\sonia-config.json"},
        "idempotency_key": "pytest-idem-001",
    }
    r1 = client.post("/v1/actions/plan", json=body).json()
    r2 = client.post("/v1/actions/plan", json=body).json()
    assert r1["action_id"] == r2["action_id"]


# ── Action list/get ──────────────────────────────────────────────────────────

def test_list_actions(client):
    """GET /v1/actions returns list with total count."""
    r = client.get("/v1/actions")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["actions"], list)
    assert data["total"] >= 0


def test_get_action_by_id(client):
    """GET /v1/actions/{id} returns action record."""
    # Create an action first
    body = {"intent": "file.read", "params": {"path": r"S:\config\sonia-config.json"}}
    plan = client.post("/v1/actions/plan", json=body).json()
    action_id = plan["action_id"]

    r = client.get(f"/v1/actions/{action_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["action"]["action_id"] == action_id
    assert data["action"]["intent"] == "file.read"


def test_get_nonexistent_action(client):
    """GET /v1/actions/{bad_id} returns 404."""
    r = client.get("/v1/actions/act_nonexistent")
    assert r.status_code == 404
    data = r.json()
    assert data["ok"] is False


# ── Schema validation ────────────────────────────────────────────────────────

def test_telemetry_fields_present(client):
    """Successful action response includes telemetry with timing data."""
    import uuid
    body = {
        "intent": "file.read",
        "params": {"path": r"S:\config\sonia-config.json"},
        "idempotency_key": f"telemetry-test-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body).json()
    assert "telemetry" in r
    t = r["telemetry"]
    assert "plan_ms" in t
    assert "validate_ms" in t
    assert "total_ms" in t
    assert t["execute_ms"] >= 0


def test_validation_result_has_checks(client):
    """Validation result includes individual check details."""
    body = {"intent": "file.read", "params": {"path": r"S:\config\sonia-config.json"}, "dry_run": True}
    r = client.post("/v1/actions/plan", json=body).json()
    v = r["validation"]
    assert v["valid"] is True
    assert len(v["checks"]) >= 4
    for check in v["checks"]:
        assert "check" in check
        assert "pass" in check


# ── Unit tests for capability registry ────────────────────────────────────────

def test_capability_registry_param_validation():
    """CapabilityRegistry.validate_params catches missing params."""
    from capability_registry import get_capability_registry
    reg = get_capability_registry()
    errors = reg.validate_params("file.read", {})
    assert len(errors) == 1
    assert "path" in errors[0]

    errors = reg.validate_params("file.read", {"path": "/some/file"})
    assert len(errors) == 0


def test_capability_registry_stats():
    """Registry stats are populated correctly."""
    from capability_registry import get_capability_registry
    reg = get_capability_registry()
    stats = reg.stats()
    assert stats["total"] >= 13
    assert stats["implemented"] >= 4
    assert stats["confirmable"] >= 1
    assert stats["idempotent"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
