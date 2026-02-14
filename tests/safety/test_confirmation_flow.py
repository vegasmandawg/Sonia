"""Pytest suite for confirmation token lifecycle and guard flow."""

import sys
import time
from pathlib import Path

OPENCLAW_DIR = Path(__file__).resolve().parents[2] / "services" / "openclaw"
OPENCLAW_APP_DIR = OPENCLAW_DIR / "app"
if str(OPENCLAW_DIR) not in sys.path:
    sys.path.insert(0, str(OPENCLAW_DIR))
if str(OPENCLAW_APP_DIR) not in sys.path:
    sys.path.insert(0, str(OPENCLAW_APP_DIR))

try:
    import app as _app_pkg  # type: ignore
    if hasattr(_app_pkg, "__path__") and str(OPENCLAW_APP_DIR) not in _app_pkg.__path__:
        _app_pkg.__path__.append(str(OPENCLAW_APP_DIR))
except Exception:
    pass

from app.action_guard import ActionGuard
from app.confirmations import ConfirmationManager, TokenState
from app.policy_engine import PolicyEngine, default_safety_rules


def _guard() -> ActionGuard:
    engine = PolicyEngine(rules=default_safety_rules())
    confirmations = ConfirmationManager(ttl_seconds=60.0)
    return ActionGuard(engine, confirmations)


def test_f1_mint_token_basics():
    manager = ConfirmationManager(ttl_seconds=10.0)
    token = manager.mint_token("file.write", {"path": "S:\\tmp\\x"}, "f1")
    assert token.token_id.startswith("ctk_")
    assert token.state == TokenState.PENDING
    assert token.action == "file.write"
    assert token.remaining_seconds > 0


def test_f2_redeem_happy_path():
    manager = ConfirmationManager(ttl_seconds=10.0)
    token = manager.mint_token("file.write", {"path": "S:\\tmp\\x"}, "f2a")
    result = manager.redeem_token(token.token_id, "f2b")
    assert result.accepted
    assert result.state == TokenState.APPROVED


def test_f3_replay_denied():
    manager = ConfirmationManager(ttl_seconds=10.0)
    token = manager.mint_token("file.write", {"path": "S:\\tmp\\x"}, "f3a")
    manager.redeem_token(token.token_id, "f3b")
    replay = manager.redeem_token(token.token_id, "f3c")
    assert not replay.accepted
    assert replay.state == TokenState.REPLAYED
    assert "already used" in replay.reason.lower()


def test_f4_redeem_nonexistent_token():
    manager = ConfirmationManager(ttl_seconds=10.0)
    result = manager.redeem_token("ctk_bogus", "f4")
    assert not result.accepted
    assert "not found" in result.reason.lower()


def test_f5_ttl_expiry():
    manager = ConfirmationManager(ttl_seconds=0.05)
    token = manager.mint_token("shell.run", {"command": "ls"}, "f5a")
    time.sleep(0.1)
    result = manager.redeem_token(token.token_id, "f5b")
    assert not result.accepted
    assert result.state == TokenState.EXPIRED


def test_f6_explicit_deny():
    manager = ConfirmationManager(ttl_seconds=60.0)
    token = manager.mint_token("browser.open", {"url": "https://x.com"}, "f6a")
    denied = manager.deny_token(token.token_id, "f6b", "No thanks")
    assert not denied.accepted
    assert denied.state == TokenState.DENIED
    post = manager.redeem_token(token.token_id, "f6c")
    assert not post.accepted


def test_f7_max_pending_eviction():
    manager = ConfirmationManager(ttl_seconds=60.0, max_pending=2)
    t1 = manager.mint_token("a1", {}, "f7a")
    manager.mint_token("a2", {}, "f7b")
    t3 = manager.mint_token("a3", {}, "f7c")
    assert manager.get_token(t1.token_id).state == TokenState.EXPIRED
    assert manager.get_token(t3.token_id).state == TokenState.PENDING


def test_f8_pending_query_and_count():
    manager = ConfirmationManager(ttl_seconds=60.0)
    t1 = manager.mint_token("a", {}, "f8a")
    manager.mint_token("b", {}, "f8b")
    manager.redeem_token(t1.token_id, "f8c")
    assert manager.pending_count == 1


def test_f9_event_log_contains_mint_and_redeem():
    manager = ConfirmationManager(ttl_seconds=60.0)
    token = manager.mint_token("a", {}, "f9a")
    manager.redeem_token(token.token_id, "f9b")
    events = manager.event_log
    event_types = [event["event"] for event in events]
    assert len(events) >= 2
    assert "minted" in event_types
    assert "redeemed" in event_types


def test_f10_token_serialisation():
    manager = ConfirmationManager(ttl_seconds=60.0)
    token = manager.mint_token("test", {"key": "val"}, "f10")
    data = token.to_dict()
    assert data["state"] == "pending"
    assert data["remaining_seconds"] > 0


def test_f11_guard_allow_path():
    guard = _guard()
    result = guard.guard("file.read", {"path": "S:\\x"}, trace_id="f11")
    assert result.proceed
    assert not result.needs_confirmation


def test_f12_guard_deny_path():
    guard = _guard()
    result = guard.guard("shell.run", {"command": "Remove-Item foo"}, trace_id="f12")
    assert result.denied
    assert not result.proceed


def test_f13_f14_f15_guard_confirm_and_replay():
    guard = _guard()
    initial = guard.guard("file.write", {"path": "S:\\tmp\\test"}, trace_id="f13")
    assert initial.needs_confirmation
    assert initial.confirmation_token is not None

    token_id = initial.confirmation_token.token_id
    approved = guard.guard(
        "file.write",
        {"path": "S:\\tmp\\test"},
        context={"approval_token": token_id},
        trace_id="f14",
    )
    assert approved.proceed
    assert approved.redeem_result.accepted

    replay = guard.guard(
        "file.write",
        {"path": "S:\\tmp\\test"},
        context={"approval_token": token_id},
        trace_id="f15",
    )
    assert not replay.proceed
    assert replay.denied


def test_f16_guard_deny_pending():
    guard = _guard()
    pending = guard.guard("file.write", {"path": "S:\\tmp\\deny_me"}, trace_id="f16a")
    deny_result = guard.deny_pending(pending.confirmation_token.token_id, "f16b", "Nope")
    assert not deny_result.accepted
    assert deny_result.state == TokenState.DENIED


def test_f17_guard_result_serialisation():
    guard = _guard()
    result = guard.guard("file.read", {"path": "S:\\x"}, trace_id="f17")
    data = result.to_dict()
    assert data["proceed"] is True
    assert "policy_decision" in data
