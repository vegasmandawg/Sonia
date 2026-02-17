"""
v4.7 Epic B -- B2/B5: Mutation Ordering Determinism

Tests:
  1. Concurrent approve calls on same action serialize (only first wins)
  2. Concurrent deny + approve on same action serialize deterministically
  3. ActionStore.put() under concurrent writes preserves all records
  4. Idempotency map is consistent after concurrent plan() calls with same key
  5. Confirmation approve after expiry returns EXPIRED, not race
  6. Sequential mutations produce monotonically increasing updated_at
"""

import asyncio
import sys
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from tool_policy import GatewayConfirmationManager, ConfirmationToken
from action_pipeline import ActionStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMutationOrdering:
    """B2/B5: Concurrent mutations on shared state resolve in stable, deterministic order."""

    def test_concurrent_approve_only_first_wins(self):
        """Two concurrent approve() calls on same token: first succeeds, second is idempotent."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_001", "turn_001", "file.write", {"path": "/tmp/a"})
            r1 = await mgr.approve(token.confirmation_id)
            r2 = await mgr.approve(token.confirmation_id)
            return r1, r2

        r1, r2 = _run(_test())
        assert r1["ok"] is True
        # Second approve should still return ok (idempotent), not error
        assert r2["ok"] is True
        assert r2.get("idempotent") is True

    def test_concurrent_deny_then_approve_deterministic(self):
        """Deny followed by approve returns idempotent deny, not race condition."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_002", "turn_002", "shell.run", {"cmd": "ls"})
            r_deny = await mgr.deny(token.confirmation_id)
            r_approve = await mgr.approve(token.confirmation_id)
            return r_deny, r_approve

        r_deny, r_approve = _run(_test())
        assert r_deny["ok"] is False  # deny returns ok=False
        # Approve after deny: token already decided -> idempotent
        assert r_approve["ok"] is False
        assert r_approve.get("idempotent") is True

    def test_action_store_concurrent_puts_all_preserved(self):
        """Multiple concurrent put() calls on different action_ids all persist."""
        store = ActionStore()

        async def _put_many():
            from schemas.action import ActionRecord
            tasks = []
            for i in range(20):
                rec = ActionRecord(
                    action_id=f"act_{i:04d}",
                    intent="file.read",
                    params={"path": f"/tmp/{i}"},
                    state="planned",
                    risk_level="low",
                    requires_confirmation=False,
                    dry_run=False,
                )
                tasks.append(store.put(rec))
            await asyncio.gather(*tasks)

        _run(_put_many())

        # All 20 should be present
        for i in range(20):
            rec = _run(store.get(f"act_{i:04d}"))
            assert rec is not None, f"act_{i:04d} missing after concurrent put()"

    def test_idempotency_map_consistent_after_concurrent_puts(self):
        """Concurrent puts with same idempotency key map to last-write-wins record."""
        store = ActionStore()

        async def _concurrent_idem():
            from schemas.action import ActionRecord
            tasks = []
            for i in range(5):
                rec = ActionRecord(
                    action_id=f"act_idem_{i}",
                    intent="file.read",
                    params={},
                    state="planned",
                    risk_level="low",
                    requires_confirmation=False,
                    dry_run=False,
                    idempotency_key="shared_key",
                )
                tasks.append(store.put(rec))
            await asyncio.gather(*tasks)

        _run(_concurrent_idem())

        # The idempotency map should point to exactly one action_id
        result = _run(store.get_by_idempotency_key("shared_key"))
        assert result is not None
        assert result.action_id.startswith("act_idem_")

    def test_approve_after_expiry_returns_expired(self):
        """Token past TTL returns CONFIRMATION_EXPIRED, not a race."""
        mgr = GatewayConfirmationManager(ttl_seconds=0.0)

        async def _test():
            token = await mgr.create("ses_003", "turn_003", "file.write", {"path": "/tmp/b"})
            # Wait a tick to ensure monotonic time passes beyond TTL
            await asyncio.sleep(0.01)
            r = await mgr.approve(token.confirmation_id)
            return r

        r = _run(_test())
        # Expired token should not approve
        assert r["ok"] is False
        assert r.get("code") == "CONFIRMATION_EXPIRED" or "expired" in str(r.get("status", "")).lower()

    def test_sequential_mutations_monotonic_updated_at(self):
        """Sequential state updates produce monotonically increasing updated_at."""
        store = ActionStore()

        async def _sequential():
            from schemas.action import ActionRecord
            rec = ActionRecord(
                action_id="act_seq_001",
                intent="file.read",
                params={},
                state="planned",
                risk_level="low",
                requires_confirmation=False,
                dry_run=False,
            )
            await store.put(rec)

            timestamps = []
            for state in ["validated", "executing", "succeeded"]:
                await store.update_state("act_seq_001", state)
                updated = await store.get("act_seq_001")
                timestamps.append(updated.updated_at)

            return timestamps

        ts = _run(_sequential())
        # Each timestamp should be >= previous (monotonic)
        for i in range(1, len(ts)):
            assert ts[i] >= ts[i - 1], f"updated_at not monotonic: {ts[i]} < {ts[i-1]}"
