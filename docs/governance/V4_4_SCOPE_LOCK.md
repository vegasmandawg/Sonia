# SONIA v4.4 Scope Lock

**Schema:** 11.0
**Baseline:** 3973b72 (v4.4-dev, inherits v4.3.0 GA at bb511d4)
**Floor:** 18/18 v4.3 gates GREEN
**Contract pin:** v4.3.0 (unchanged until v4.4 scope is locked)

---

## Epics

### Epic A — Secure Exposure Hardening

**Objective:** Eliminate all P0 network exposure gaps so the stack can be safely
reachable from a non-loopback interface.

**Deliverables:**
1. Bind-address audit + fix: tool-service and orchestrator bind `127.0.0.1` by
   default, configurable via env var. Resolve port 7040 collision
   (tool-service -> 7080).
2. Auth middleware on all `0.0.0.0`-bound services (api-gateway already has it;
   extend to any service that may face an external interface).
3. TLS passthrough config: `SONIA_TLS_CERT` / `SONIA_TLS_KEY` env vars wired
   into uvicorn startup. Optional (plaintext still works on loopback), but the
   code path must exist and be testable.
4. CORS origin override: `SONIA_CORS_ORIGINS` env var in api-gateway main.py.
5. Service-token bootstrap: document and test the `x-service-token` flow for
   intra-service calls.

**Gate ownership:** 5 delta gates (bind-audit, auth-coverage, tls-config,
cors-env, service-token).

### Epic B — Voice Pipeline Activation

**Objective:** Wire the existing real ASR/TTS/VAD implementations
(`pipeline/asr.py`, `pipeline/tts.py`, `pipeline/vad.py`) into the Pipecat
service so a text or audio round-trip is testable end-to-end.

**Deliverables:**
1. Concrete `voice_backends.py` providers: `OllamaASR`, `OllamaTTS`,
   `EnergyVAD` that delegate to the existing pipeline modules.
2. Fix `ASRConfig.api_key` / `TTSConfig.api_key` AttributeError for OpenAI
   paths.
3. Factory wiring: `create_asr()` / `create_tts()` / `create_vad()` return
   real providers when backend env vars are set, stubs otherwise.
4. Binary audio WebSocket framing: extend the WS handler to accept raw PCM
   bytes (alongside `input.text` JSON) and emit TTS audio frames.
5. At least one integration test that exercises the full text round-trip path
   through the voice service with a mocked ASR/TTS backend.

**Gate ownership:** 5 delta gates (backends-wired, asr-config-fix,
factory-providers, ws-audio-framing, voice-roundtrip-test).

### Epic C — Supervision + Restart Policy

**Objective:** Give EVA-OS the ability to actually restart crashed services and
provide a process supervision contract.

**Deliverables:**
1. `ServiceSupervisor.restart_service(name)`: subprocess-based restart using
   the canonical uvicorn command for each service.
2. Restart policy: max 3 restarts per 5-minute window per service, exponential
   backoff (2s, 4s, 8s). After exhaustion, mark `UNREACHABLE` and emit alert.
3. Fix `/tasks` endpoint: real in-memory task storage with create/list/get.
4. Fix `/approve` endpoint: wire approval into SafeOrchestrator (or remove if
   SafeOrchestrator is not active).
5. Health-driven restart trigger: when a service enters `UNREACHABLE` state and
   restart policy allows, auto-restart.

**Gate ownership:** 5 delta gates (restart-method, restart-policy,
tasks-endpoint, approve-endpoint, health-restart-trigger).

---

## Explicit Non-Goals (v4.4)

- **Containerization / Docker / K8s.** Deployment artifacts are deferred to
  v4.5. v4.4 keeps the PowerShell launcher but makes it restart-safe.
- **Multi-host deployment.** All services remain single-host. TLS is for
  local-network safety, not internet exposure.
- **Full voice production (real-time audio streaming).** v4.4 wires the
  existing implementations and proves the round-trip. Low-latency streaming
  and production SLOs are v4.5.
- **action_pipeline.verify() real adapters.** Deferred to v4.5 verification
  track.
- **Memory ops risk tier classification.** Deferred to v4.5 governance track.

---

## Invariants

1. **Floor regression zero-tolerance.** All 18 inherited v4.3 gates must pass
   at every merge point. Any floor regression blocks promotion.
2. **Fail-closed security.** Unknown bind addresses default to `127.0.0.1`.
   TLS misconfiguration fails startup, not silently degrades.
3. **Restart safety.** A restarted service must re-enter the lifespan flow
   (DurableStateStore restore, vector init, consent FSM reset). No state leak.
4. **Contract pin.** SONIA_CONTRACT stays at `v4.3.0` until GA. Version bumps
   only in `SONIA_VERSION`.

---

## Rollback Policy

- **Per-epic rollback:** each epic merges `--no-ff` from its own branch. Revert
  the merge commit to roll back a single epic.
- **Full rollback:** `git revert` the v4.4-dev merge into main; `release/v4.3.x`
  remains as the hotfix-only stable branch.
- **State compatibility:** DurableStateStore schema must remain backward
  compatible. No destructive migrations in v4.4.

---

## Epic-to-Gate Ownership Map

| Gate Class | Source | Count |
|------------|--------|-------|
| A (floor)  | Inherited v4.3 | 18 |
| B (delta)  | Epic A: Secure Exposure | 5 |
| B (delta)  | Epic B: Voice Pipeline | 5 |
| B (delta)  | Epic C: Supervision | 5 |
| **Total**  | | **33** |

---

## Branch Strategy

```
main (v4.3.0 GA merged)
  └── v4.4-dev (active development)
       ├── v4.4-epic-a (secure exposure)
       ├── v4.4-epic-b (voice pipeline)
       └── v4.4-epic-c (supervision)
```

Each epic branch merges into `v4.4-dev` with `--no-ff` and evidence (gate
report + tests). Mid-cycle control point after first epic merge.

---

## Promotion Exit Criteria

1. **Floor:** 18/18 inherited v4.3 gates PASS (zero regressions).
2. **Delta:** 15/15 new v4.4 gates PASS.
3. **Soak:** Zero SLO violations across 200+ operations.
4. **Clean-room:** All files compile, all roundtrip tests pass.
5. **SHA-256:** Reproducible release bundle with checksum manifest.
6. **Evidence:** Gate report, soak report, baseline-vs-final comparison.

---

## Mid-Cycle Control Point

After the first epic merge into `v4.4-dev`:
- Run full 18 floor gates + available delta subset.
- Compare against `v4.4.0-baseline/gate-report.json`.
- If any floor gate regresses, block further epic merges until fixed.
- Archive mid-cycle report to `releases/v4.4.0-midcycle/`.
