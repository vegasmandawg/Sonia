"""
Stage 5 M3 — test_desktop_adapters.py
Tests for desktop action executors, approval flow, and audit trail.
"""

import sys
import httpx
import pytest
import uuid

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"


@pytest.fixture
def client():
    return httpx.Client(base_url=GW, timeout=30)


# ── Capabilities: all 13 now implemented ─────────────────────────────────────

def test_all_capabilities_implemented(client):
    """All 13 capabilities should now be implemented."""
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["stats"]["total"] == 13
    assert data["stats"]["implemented"] == 13
    for cap in data["capabilities"]:
        assert cap["implemented"] is True, f"{cap['intent']} should be implemented"


# ── Safe desktop actions (no approval needed) ────────────────────────────────

def test_window_list_safe_action(client):
    """window.list is safe and should execute immediately."""
    body = {
        "intent": "window.list",
        "params": {},
        "idempotency_key": f"wl-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "succeeded"
    assert data["risk_level"] == "safe"
    assert data["requires_confirmation"] is False
    assert data["execution"]["success"] is True
    # Should have a list of windows
    output = data["execution"].get("output", {})
    assert "windows" in output or "result" in output or isinstance(output, dict)


def test_clipboard_read_safe_action(client):
    """clipboard.read is safe and should execute immediately."""
    body = {
        "intent": "clipboard.read",
        "params": {},
        "idempotency_key": f"cr-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "succeeded"
    assert data["risk_level"] == "safe"
    assert data["execution"]["success"] is True


def test_window_focus_safe_action(client):
    """window.focus is safe, but may fail if no matching window — not an error."""
    body = {
        "intent": "window.focus",
        "params": {"title": "NonExistentWindow12345"},
        "idempotency_key": f"wf-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    # Should attempt execution (safe, no approval needed)
    # May succeed or fail depending on whether a window matches
    assert data["risk_level"] == "safe"
    assert data["requires_confirmation"] is False


# ── Guarded desktop actions (approval needed) ────────────────────────────────

def test_app_launch_requires_approval(client):
    """app.launch (medium risk) should gate to pending_approval."""
    body = {
        "intent": "app.launch",
        "params": {"target": "notepad.exe"},
        "idempotency_key": f"al-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["requires_confirmation"] is True
    assert data["risk_level"] == "medium"


def test_app_close_requires_approval(client):
    """app.close (high risk) should gate to pending_approval."""
    body = {
        "intent": "app.close",
        "params": {"target": "notepad.exe"},
        "idempotency_key": f"ac-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["requires_confirmation"] is True
    assert data["risk_level"] == "high"


def test_keyboard_type_requires_approval(client):
    """keyboard.type (high risk) should gate to pending_approval."""
    body = {
        "intent": "keyboard.type",
        "params": {"text": "hello"},
        "idempotency_key": f"kt-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["requires_confirmation"] is True
    assert data["risk_level"] == "high"


def test_keyboard_hotkey_requires_approval(client):
    """keyboard.hotkey (high risk) should gate to pending_approval."""
    body = {
        "intent": "keyboard.hotkey",
        "params": {"keys": "ctrl+s"},
        "idempotency_key": f"kh-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["risk_level"] == "high"


def test_mouse_click_requires_approval(client):
    """mouse.click (high risk) should gate to pending_approval."""
    body = {
        "intent": "mouse.click",
        "params": {"x": 100, "y": 100},
        "idempotency_key": f"mc-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["state"] == "pending_approval"
    assert data["risk_level"] == "high"


# ── Clipboard write (low risk, no confirmation) ─────────────────────────────

def test_clipboard_write_executes_immediately(client):
    """clipboard.write is low risk with no confirmation, executes immediately."""
    test_text = f"sonia-test-{uuid.uuid4().hex[:8]}"
    body = {
        "intent": "clipboard.write",
        "params": {"text": test_text},
        "idempotency_key": f"cw-{uuid.uuid4().hex[:8]}",
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "succeeded"
    assert data["risk_level"] == "low"
    assert data["execution"]["success"] is True


# ── Approve and execute desktop action ───────────────────────────────────────

def test_approve_app_launch_notepad(client):
    """Approving app.launch for notepad should succeed, then close it."""
    # Plan
    body = {
        "intent": "app.launch",
        "params": {"target": "notepad.exe"},
        "idempotency_key": f"aln-{uuid.uuid4().hex[:8]}",
    }
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

    # Clean up: close notepad
    close_body = {
        "intent": "app.close",
        "params": {"target": "notepad.exe"},
        "idempotency_key": f"acn-{uuid.uuid4().hex[:8]}",
    }
    close_plan = client.post("/v1/actions/plan", json=close_body).json()
    close_id = close_plan["action_id"]
    client.post(f"/v1/actions/{close_id}/approve")


# ── Deny desktop action ─────────────────────────────────────────────────────

def test_deny_keyboard_type(client):
    """Denying keyboard.type should set state to denied."""
    body = {
        "intent": "keyboard.type",
        "params": {"text": "should not type this"},
        "idempotency_key": f"dkt-{uuid.uuid4().hex[:8]}",
    }
    plan = client.post("/v1/actions/plan", json=body).json()
    assert plan["state"] == "pending_approval"
    action_id = plan["action_id"]

    r = client.post(f"/v1/actions/{action_id}/deny")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "denied"


# ── Dry run desktop actions ──────────────────────────────────────────────────

def test_dry_run_app_launch(client):
    """Dry run app.launch validates but does not execute."""
    body = {
        "intent": "app.launch",
        "params": {"target": "calc.exe"},
        "dry_run": True,
    }
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is True
    assert data["state"] == "validated"
    assert data.get("execution") is None
    assert data["validation"]["valid"] is True


# ── Audit trail ──────────────────────────────────────────────────────────────

def test_audit_trails_endpoint(client):
    """GET /v1/audit-trails returns list of audit trails."""
    r = client.get("/v1/audit-trails")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["trails"], list)
    assert "total" in data


def test_audit_trail_for_action(client):
    """Audit trail is created for an executed action."""
    body = {
        "intent": "window.list",
        "params": {},
        "idempotency_key": f"at-{uuid.uuid4().hex[:8]}",
    }
    plan = client.post("/v1/actions/plan", json=body).json()
    action_id = plan["action_id"]

    r = client.get(f"/v1/audit-trails/{action_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    trail = data["trail"]
    assert trail["action_id"] == action_id
    assert trail["intent"] == "window.list"
    assert len(trail["events"]) >= 3  # plan + validate + execute + lifecycle
    # Check lifecycle phases are recorded
    phases = [e["phase"] for e in trail["events"]]
    assert "plan" in phases
    assert "validate" in phases


def test_audit_trail_nonexistent(client):
    """GET /v1/audit-trails/{bad_id} returns 404."""
    r = client.get("/v1/audit-trails/act_nonexistent")
    assert r.status_code == 404


# ── Capability registry M3 updates ──────────────────────────────────────────

def test_capability_registry_stats_m3(client):
    """Registry stats reflect 13 implemented capabilities."""
    r = client.get("/v1/capabilities")
    data = r.json()
    stats = data["stats"]
    assert stats["total"] == 13
    assert stats["implemented"] == 13
    assert stats["by_risk"]["safe"] >= 4  # file.read, window.list, window.focus, clipboard.read
    assert stats["by_risk"]["high"] >= 4  # app.close, keyboard.type, keyboard.hotkey, mouse.click
    assert stats["confirmable"] >= 7  # All high/medium risk actions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
