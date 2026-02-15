# v3.5 Sprint: Conservative-Gap Closers

**Branch:** `v3.5-conservative-gaps`
**Base:** `main` at `v3.4.0-audit-closure`
**Goal:** Push both audit scorers above 78% per-pass floor. Estimated +10-15 pts conservative.

---

## Deliverables

### 1. Default-On Auth Posture
**Section:** I (Auth & Authorization) | **Est. impact:** +4-6 pts

- Enable auth middleware by default in `services/api-gateway/main.py`
- Add `SONIA_DEV_MODE=1` environment variable override
- Emit startup warning when dev mode is active: `WARNING: Auth disabled — SONIA_DEV_MODE=1`
- Require explicit opt-out, not opt-in
- Update `docs/SECURITY_MODEL.md` and `docs/DEPLOYMENT.md`

**Acceptance:**
- [ ] Fresh start without `SONIA_DEV_MODE` rejects unauthenticated requests (401)
- [ ] `SONIA_DEV_MODE=1` allows unauthenticated access with logged warning
- [ ] Existing integration tests updated to pass auth header or set dev mode

### 2. Thin Unit-Test Layer for Core Policy Modules
**Section:** L (Testing Strategy) | **Est. impact:** +3-5 pts

Target modules (direct import, no live services):
- `services/shared/rate_limiter.py` — token bucket, per-client isolation, burst/refill
- `services/shared/log_redaction.py` — all pattern categories, edge cases
- `services/api-gateway/tool_policy.py` — tier classification, safe_read/guarded/blocked
- `services/api-gateway/turn_quality.py` — normalization, max_output_chars, fallback

**Acceptance:**
- [ ] `tests/unit/` directory with 4 test files
- [ ] pytest runs unit tests in < 5 seconds (no network, no DB)
- [ ] Coverage report for targeted modules > 80%

### 3. Codified Automatic Fallback + Tests
**Section:** G (Error Handling & Resilience) | **Est. impact:** +3-4 pts

- Replace manual fallback cascade in `router_client.chat()` with automatic retry-with-fallback
- Define fallback chain: primary provider -> secondary provider -> local stub
- Add circuit breaker integration to fallback decisions
- Write integration tests proving fallback triggers automatically

**Acceptance:**
- [ ] `router_client.chat()` retries on transient failure without caller intervention
- [ ] Fallback chain is configurable (not hardcoded)
- [ ] Test: primary timeout -> automatic fallback -> success
- [ ] Test: all providers down -> graceful error with fallback_used=true annotation

---

## Definition of Done

All three deliverables complete AND:
- Full build verification re-run (all 10 gates PASS)
- Conservative audit re-score targets >= 78%
- No regressions in existing 20/20 integration tests
- Updated evidence binder with new artifacts
