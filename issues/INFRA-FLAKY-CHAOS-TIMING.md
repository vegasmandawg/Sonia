# INFRA-FLAKY-CHAOS-TIMING

**Status:** Open
**Priority:** P2
**Owner:** infra
**SLA:** Fix or suppress by v2.9.2
**Marker:** `@pytest.mark.infra_flaky`

## Test

`tests/integration/test_stage7_chaos_recovery.py::TestChaosRecovery::test_health_supervisor_reports_healthy`

## Failure Signature

```
Expected healthy, got recovering (chaos test timing sensitivity)
```

The test calls `/v1/health/summary` and asserts `overall_state == "healthy"`.
After preceding chaos tests (adapter timeouts, breaker trips, DLQ replays),
the health supervisor may still be in `recovering` state when this test runs.

## Root Cause

The health supervisor state machine transitions through
`degraded -> recovering -> healthy` after chaos perturbations. The recovery
window depends on probe intervals (default 5s) and the number of services
that need re-verification. Test ordering places this assertion too soon
after chaos teardown.

## Mitigation

- Marked `@pytest.mark.infra_flaky`.
- Non-blocking: `pytest -m infra_flaky` runs separately.

## Resolution Plan

1. Add a polling wait (up to 30s) in the test for `healthy` state instead of
   a single-shot assertion.
2. Alternatively, insert a `time.sleep(10)` fixture between chaos tests and
   health assertion tests.
3. Consider test ordering constraints (`pytest-ordering`) to guarantee
   sufficient recovery window.
4. Verify with 10x soak before removing marker.
