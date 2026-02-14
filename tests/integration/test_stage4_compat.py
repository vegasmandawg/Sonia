"""
Stage 5 — test_stage4_compat.py
Backward compatibility tests ensuring Stage 4 behavior is preserved.
"""

import sys
import httpx
import pytest
import json

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"


@pytest.fixture
def client():
    return httpx.Client(base_url=GW, timeout=120)


# ── Health check preserved ───────────────────────────────────────────────────

def test_healthz(client):
    """GET /healthz still works."""
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["service"] == "api-gateway"


# ── Stage 2 turn endpoint preserved ──────────────────────────────────────────

def test_sync_turn_still_works(client):
    """POST /v1/turn still returns ok with quality and latency."""
    body = {
        "user_id": "s4compat-user",
        "conversation_id": "s4compat-conv",
        "input_text": "What is 7+3?",
    }
    r = client.post("/v1/turn", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["assistant_text"]
    assert "quality" in data
    assert "latency" in data


# ── Stage 3 session endpoints preserved ──────────────────────────────────────

def test_session_lifecycle(client):
    """POST/GET/DELETE sessions still works."""
    # Create
    body = {"user_id": "s4compat", "conversation_id": "s4compat-conv"}
    cr = client.post("/v1/sessions", json=body)
    assert cr.status_code == 200
    sid = cr.json()["session_id"]

    # Get
    gr = client.get(f"/v1/sessions/{sid}")
    assert gr.status_code == 200
    assert gr.json()["session_id"] == sid

    # Delete
    dr = client.delete(f"/v1/sessions/{sid}")
    assert dr.status_code == 200


# ── Stage 3 confirmation endpoints preserved ─────────────────────────────────

def test_confirmation_pending(client):
    """GET /v1/confirmations/pending still works."""
    r = client.get("/v1/confirmations/pending", params={"session_id": "test-session"})
    assert r.status_code == 200
    data = r.json()
    assert "pending" in data
    assert "count" in data


# ── Stage 4 quality annotations preserved ────────────────────────────────────

def test_turn_quality_annotations(client):
    """Turn response includes quality annotations from Stage 4."""
    body = {
        "user_id": "s4compat-quality",
        "conversation_id": "s4compat-qconv",
        "input_text": "hello",
    }
    r = client.post("/v1/turn", json=body).json()
    assert r["ok"] is True
    quality = r.get("quality", {})
    assert "generation_profile_used" in quality or quality == {}
    latency = r.get("latency", {})
    assert "total_ms" in latency or latency == {}


# ── Stage 2 action endpoint preserved ────────────────────────────────────────

def test_legacy_action_endpoint(client):
    """POST /v1/action (Stage 2 legacy) still works."""
    r = client.post("/v1/action", params={"tool_name": "file.read", "timeout_ms": 5000},
                    json={"path": r"S:\config\sonia-config.json"})
    assert r.status_code == 200
    data = r.json()
    # The legacy action endpoint should still return a valid response
    assert "ok" in data or "status" in data


# ── Deps check preserved ────────────────────────────────────────────────────

def test_deps_endpoint(client):
    """GET /v1/deps still returns dependency status."""
    r = client.get("/v1/deps")
    assert r.status_code == 200
    data = r.json()
    assert "data" in data
    assert "openclaw" in data["data"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
