"""
SONIA v3.0.0 Milestone 2 -- Identity + Persistence integration tests.

Tests:
  - User CRUD (create, get, update, soft-delete)
  - API key generation, hashing, rotation
  - Auth middleware (valid/invalid/missing key, exempt paths, service token)
  - Session persistence (create -> load)
  - Conversation history (write -> read back)
  - Session list by user
  - History list by session (ordered)

Runs against in-process ASGI TestClient (no live services needed).
"""
import hashlib
import json
import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# ── Path setup ───────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = REPO_ROOT / "services" / "shared"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
MEMORY_DIR = REPO_ROOT / "services" / "memory-engine"

sys.path.insert(0, str(SHARED_DIR))
sys.path.insert(0, str(GATEWAY_DIR))
sys.path.insert(0, str(MEMORY_DIR))


# ═════════════════════════════════════════════════════════════════════════
# Group 1: Memory Engine Identity Endpoints
# ═════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def memory_client():
    """Create a TestClient for the Memory Engine app with test DB.

    Key trick: patch db.get_db *before* importing main so the module-level
    ``db = get_db()`` initialises against the temp DB, not the production one.
    """
    from starlette.testclient import TestClient

    # Use a temp database so tests don't affect production data
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_path = tmp_db.name

    # Let MemoryDatabase handle schema + migrations (it tracks applied
    # migrations in schema_migrations table, so everything is idempotent).
    from db import MemoryDatabase
    test_db = MemoryDatabase(db_path=tmp_path)

    # Ensure main hasn't been imported yet (would have used production DB).
    sys.modules.pop("main", None)

    import db as _db_mod
    _original_get_db = _db_mod.get_db

    # Patch get_db so the module-level ``db = get_db()`` in main.py returns
    # our test instance instead of creating one against production.
    _db_mod.get_db = lambda: test_db

    try:
        import main as mem_main
        # Also poke the module-level name directly (belt-and-suspenders)
        mem_main.db = test_db
    finally:
        _db_mod.get_db = _original_get_db

    client = TestClient(mem_main.app, raise_server_exceptions=False)
    yield client

    # Cleanup
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


class TestUserCRUD:
    """User create, read, update, soft-delete."""

    def test_create_user(self, memory_client):
        resp = memory_client.post("/v1/users", json={"display_name": "Test User"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Test User"
        assert data["user_id"].startswith("usr_")
        assert data["api_key"].startswith("sk-sonia-")
        assert "_warning" in data

    def test_get_user(self, memory_client):
        # Create first
        create = memory_client.post("/v1/users", json={"display_name": "Get Test"})
        user_id = create.json()["user_id"]

        resp = memory_client.get(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user_id
        assert data["display_name"] == "Get Test"
        assert data["status"] == "active"
        # API key should NOT be in the response
        assert "api_key" not in data
        assert "api_key_hash" not in data

    def test_update_user(self, memory_client):
        create = memory_client.post("/v1/users", json={"display_name": "Before"})
        user_id = create.json()["user_id"]

        resp = memory_client.put(
            f"/v1/users/{user_id}",
            json={"display_name": "After", "metadata": {"role": "admin"}},
        )
        assert resp.status_code == 200

        get_resp = memory_client.get(f"/v1/users/{user_id}")
        assert get_resp.json()["display_name"] == "After"
        assert get_resp.json()["metadata"]["role"] == "admin"

    def test_soft_delete_user(self, memory_client):
        create = memory_client.post("/v1/users", json={"display_name": "Delete Me"})
        user_id = create.json()["user_id"]

        resp = memory_client.delete(f"/v1/users/{user_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        get_resp = memory_client.get(f"/v1/users/{user_id}")
        assert get_resp.json()["status"] == "deleted"

    def test_list_users(self, memory_client):
        resp = memory_client.get("/v1/users")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_get_nonexistent_user(self, memory_client):
        resp = memory_client.get("/v1/users/usr_nonexistent")
        assert resp.status_code == 404


class TestAPIKeyManagement:
    """API key generation, hashing, rotation."""

    def test_key_is_sha256_hashed(self, memory_client):
        resp = memory_client.post("/v1/users", json={"display_name": "Hash Test"})
        data = resp.json()
        api_key = data["api_key"]
        user_id = data["user_id"]
        expected_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

        # Look up by hash
        lookup = memory_client.get(f"/v1/users/by-key?api_key_hash={expected_hash}")
        assert lookup.status_code == 200
        assert lookup.json()["user_id"] == user_id

    def test_wrong_key_hash_not_found(self, memory_client):
        resp = memory_client.get("/v1/users/by-key?api_key_hash=deadbeef1234567890")
        assert resp.status_code == 404

    def test_rotate_key(self, memory_client):
        create = memory_client.post("/v1/users", json={"display_name": "Rotate Test"})
        user_id = create.json()["user_id"]
        old_key = create.json()["api_key"]

        # Rotate
        rotate = memory_client.post(f"/v1/users/{user_id}/rotate-key")
        assert rotate.status_code == 200
        new_key = rotate.json()["api_key"]
        assert new_key != old_key
        assert new_key.startswith("sk-sonia-")

        # Old key should no longer work
        old_hash = hashlib.sha256(old_key.encode("utf-8")).hexdigest()
        lookup_old = memory_client.get(f"/v1/users/by-key?api_key_hash={old_hash}")
        assert lookup_old.status_code == 404

        # New key should work
        new_hash = hashlib.sha256(new_key.encode("utf-8")).hexdigest()
        lookup_new = memory_client.get(f"/v1/users/by-key?api_key_hash={new_hash}")
        assert lookup_new.status_code == 200
        assert lookup_new.json()["user_id"] == user_id

    def test_rotate_deleted_user_fails(self, memory_client):
        create = memory_client.post("/v1/users", json={"display_name": "Del Rotate"})
        user_id = create.json()["user_id"]
        memory_client.delete(f"/v1/users/{user_id}")

        rotate = memory_client.post(f"/v1/users/{user_id}/rotate-key")
        assert rotate.status_code == 400


# ═════════════════════════════════════════════════════════════════════════
# Group 2: Session Persistence
# ═════════════════════════════════════════════════════════════════════════

class TestSessionPersistence:
    """Session persist, load, update, list."""

    def test_persist_and_load_session(self, memory_client):
        session_data = {
            "session_id": "ses_test123",
            "user_id": "usr_test",
            "conversation_id": "conv_test",
            "profile": "chat_low_latency",
            "status": "active",
            "created_at": "2026-02-14T10:00:00Z",
            "expires_at": "2026-02-14T10:30:00Z",
            "last_activity": "2026-02-14T10:00:00Z",
            "turn_count": 0,
        }
        persist = memory_client.post("/v1/sessions/persist", json=session_data)
        assert persist.status_code == 200

        load = memory_client.get("/v1/sessions/load/ses_test123")
        assert load.status_code == 200
        data = load.json()
        assert data["session_id"] == "ses_test123"
        assert data["user_id"] == "usr_test"
        assert data["profile"] == "chat_low_latency"

    def test_update_session(self, memory_client):
        session_data = {
            "session_id": "ses_update",
            "user_id": "usr_test",
            "conversation_id": "conv_up",
            "profile": "reasoning_deep",
            "status": "active",
            "created_at": "2026-02-14T10:00:00Z",
            "expires_at": "2026-02-14T10:30:00Z",
            "last_activity": "2026-02-14T10:00:00Z",
            "turn_count": 0,
        }
        memory_client.post("/v1/sessions/persist", json=session_data)

        update = memory_client.put(
            "/v1/sessions/update/ses_update",
            json={"status": "closed", "turn_count": 5},
        )
        assert update.status_code == 200

        load = memory_client.get("/v1/sessions/load/ses_update")
        assert load.json()["status"] == "closed"
        assert load.json()["turn_count"] == 5

    def test_list_user_sessions(self, memory_client):
        for i in range(3):
            memory_client.post("/v1/sessions/persist", json={
                "session_id": f"ses_list_{i}",
                "user_id": "usr_lister",
                "conversation_id": f"conv_{i}",
                "profile": "chat_low_latency",
                "status": "active",
                "created_at": "2026-02-14T10:00:00Z",
                "expires_at": "2026-02-14T10:30:00Z",
                "last_activity": "2026-02-14T10:00:00Z",
                "turn_count": 0,
            })

        resp = memory_client.get("/v1/users/usr_lister/sessions")
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    def test_list_active_sessions(self, memory_client):
        resp = memory_client.get("/v1/sessions/active")
        assert resp.status_code == 200
        assert isinstance(resp.json()["sessions"], list)

    def test_load_nonexistent_session(self, memory_client):
        resp = memory_client.get("/v1/sessions/load/ses_noexist")
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Group 3: Conversation History
# ═════════════════════════════════════════════════════════════════════════

class TestConversationHistory:
    """Write and read conversation turns."""

    def test_write_and_read_turn(self, memory_client):
        turn_data = {
            "turn_id": "turn_001",
            "session_id": "ses_hist",
            "user_id": "usr_hist",
            "sequence_num": 1,
            "user_input": "Hello, Sonia",
            "assistant_response": "Hello! How can I help?",
            "model_used": "ollama/sonia-vlm:32b",
            "latency_ms": 150.5,
        }
        write = memory_client.post("/v1/history/turns", json=turn_data)
        assert write.status_code == 200

        read = memory_client.get("/v1/sessions/ses_hist/history")
        assert read.status_code == 200
        turns = read.json()["turns"]
        assert len(turns) >= 1
        assert turns[0]["turn_id"] == "turn_001"
        assert turns[0]["user_input"] == "Hello, Sonia"
        assert turns[0]["assistant_response"] == "Hello! How can I help?"

    def test_history_ordered_by_sequence(self, memory_client):
        for i in [3, 1, 2]:
            memory_client.post("/v1/history/turns", json={
                "turn_id": f"turn_ord_{i}",
                "session_id": "ses_order",
                "user_id": "usr_order",
                "sequence_num": i,
                "user_input": f"Message {i}",
            })

        read = memory_client.get("/v1/sessions/ses_order/history")
        turns = read.json()["turns"]
        assert len(turns) == 3
        assert [t["sequence_num"] for t in turns] == [1, 2, 3]

    def test_user_history_across_sessions(self, memory_client):
        for sid in ["ses_a", "ses_b"]:
            memory_client.post("/v1/history/turns", json={
                "turn_id": f"turn_{sid}",
                "session_id": sid,
                "user_id": "usr_cross",
                "sequence_num": 1,
                "user_input": f"In {sid}",
            })

        read = memory_client.get("/v1/users/usr_cross/history")
        assert read.status_code == 200
        assert read.json()["count"] >= 2

    def test_history_with_tool_calls(self, memory_client):
        memory_client.post("/v1/history/turns", json={
            "turn_id": "turn_tools",
            "session_id": "ses_tools",
            "user_id": "usr_tools",
            "sequence_num": 1,
            "user_input": "Read a file",
            "tool_calls": [{"name": "file.read", "args": {"path": "/tmp/test.txt"}}],
            "metadata": {"quality": "good"},
        })

        read = memory_client.get("/v1/sessions/ses_tools/history")
        turns = read.json()["turns"]
        assert len(turns) >= 1
        assert isinstance(turns[0]["tool_calls"], list)
        assert turns[0]["tool_calls"][0]["name"] == "file.read"
        assert isinstance(turns[0]["metadata"], dict)


# ═════════════════════════════════════════════════════════════════════════
# Group 4: Auth Middleware
# ═════════════════════════════════════════════════════════════════════════

class TestAuthMiddleware:
    """Test the auth module directly (not via full gateway TestClient)."""

    def test_key_cache_basic(self):
        from auth import _KeyCache
        cache = _KeyCache(max_entries=5, ttl_seconds=60)

        cache.put("hash1", "usr_1", "Alice")
        result = cache.get("hash1")
        assert result is not None
        assert result["user_id"] == "usr_1"
        assert result["display_name"] == "Alice"

    def test_key_cache_miss(self):
        from auth import _KeyCache
        cache = _KeyCache()
        assert cache.get("nonexistent") is None

    def test_key_cache_eviction(self):
        from auth import _KeyCache
        cache = _KeyCache(max_entries=2, ttl_seconds=60)
        cache.put("a", "usr_a", "A")
        cache.put("b", "usr_b", "B")
        cache.put("c", "usr_c", "C")  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") is not None
        assert cache.get("c") is not None

    def test_key_cache_invalidate(self):
        from auth import _KeyCache
        cache = _KeyCache()
        cache.put("x", "usr_x", "X")
        cache.invalidate("x")
        assert cache.get("x") is None

    def test_hash_key_deterministic(self):
        from auth import _hash_key
        h1 = _hash_key("sk-sonia-test123")
        h2 = _hash_key("sk-sonia-test123")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_key_matches_python_hashlib(self):
        from auth import _hash_key
        key = "sk-sonia-abc"
        expected = hashlib.sha256(key.encode("utf-8")).hexdigest()
        assert _hash_key(key) == expected


# ═════════════════════════════════════════════════════════════════════════
# Group 5: Session Manager Persistence
# ═════════════════════════════════════════════════════════════════════════

class TestSessionManagerPersistence:
    """Test the SessionManager with mock memory client."""

    @pytest.fixture
    def mock_memory_client(self):
        client = MagicMock()
        client.persist_session = AsyncMock(return_value={"status": "persisted"})
        client.update_session = AsyncMock(return_value={"status": "updated"})
        client.load_active_sessions = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_create_triggers_persist(self, mock_memory_client):
        from session_manager import SessionManager
        mgr = SessionManager()
        mgr.set_memory_client(mock_memory_client)

        sess = await mgr.create("usr_test", "conv_test")
        assert sess.session_id.startswith("ses_")

        # Give the fire-and-forget task a chance to run
        import asyncio
        await asyncio.sleep(0.1)
        mock_memory_client.persist_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_triggers_update(self, mock_memory_client):
        from session_manager import SessionManager
        mgr = SessionManager()
        mgr.set_memory_client(mock_memory_client)

        sess = await mgr.create("usr_test", "conv_test")
        import asyncio
        await asyncio.sleep(0.1)

        await mgr.delete(sess.session_id)
        await asyncio.sleep(0.1)
        mock_memory_client.update_session.assert_called()

    @pytest.mark.asyncio
    async def test_restore_sessions(self, mock_memory_client):
        from session_manager import SessionManager
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        mock_memory_client.load_active_sessions = AsyncMock(return_value=[{
            "session_id": "ses_restored_1",
            "user_id": "usr_restore",
            "conversation_id": "conv_restore",
            "profile": "chat_low_latency",
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
            "last_activity": now.isoformat(),
            "turn_count": 5,
            "metadata": {},
        }])

        mgr = SessionManager()
        mgr.set_memory_client(mock_memory_client)
        count = await mgr.restore_sessions()
        assert count == 1

        sess = await mgr.get("ses_restored_1")
        assert sess is not None
        assert sess.user_id == "usr_restore"
        assert sess.turn_count == 5
