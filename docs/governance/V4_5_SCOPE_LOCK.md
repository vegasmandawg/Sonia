# SONIA v4.5 Scope Lock

**Schema:** 12.0
**Baseline:** 30b0dd1 (v4.5-dev, inherits v4.4.0 GA at 52f1461)
**Floor:** 33/33 v4.4 gates GREEN
**Contract pin:** v4.4.0 (unchanged until v4.5 GA)

---

## Epics

### Epic A — Orchestrator Convergence

**Objective:** Eliminate the dual-agent split by wiring the Orchestrator into the
canonical service graph — boot sequence, EVA-OS supervision, and health probes —
while routing its tool/memory calls through the canonical stack instead of
parallel implementations.

**Deliverables:**
1. Add orchestrator (8000) to EVA-OS `DEPENDENCY_GRAPH` and
   `SERVICE_COMMANDS`. Supervisor health-probes orchestrator on `/healthz`.
2. Add orchestrator to `start-sonia-stack.ps1` / `stop-sonia-stack.ps1` as
   a Tier-3 service (launched after EVA-OS, optional flag `--with-orchestrator`).
3. Rewire `agent.py` tool calls to proxy through openclaw (7040) instead of
   its own `ToolExecutor`. All tool executions flow through the safety gate.
4. Rewire `agent.py` memory calls to proxy through memory-engine (7020)
   instead of its own `MemoryManager`. All memory ops go through the
   canonical store.
5. Add vision-capture (7060) and perception (7070) to EVA-OS supervisor
   defaults + `DEPENDENCY_GRAPH` as optional services.

**Gate ownership:** 5 delta gates (orchestrator-supervised, orchestrator-boot,
tool-proxy-canonical, memory-proxy-canonical, vision-supervised).

### Epic B — Action Verification + Tool Call Routing

**Objective:** Close the two biggest turn-pipeline stubs: action post-execution
verification and model-driven tool call extraction.

**Deliverables:**
1. `action_pipeline.verify()`: implement real post-execution checks per
   capability — file.write checks file exists + size, shell.run checks exit
   code, app.launch checks process alive, clipboard checks content matches.
2. Turn pipeline tool call extraction: parse model router responses for
   structured tool calls (Ollama function-calling format), route through
   openclaw safety gate, return results in turn response.
3. Memory ops risk tier classification: replace `AUTO_LOW` placeholder with
   real policy — `FACT` writes are `safe_read`, `BELIEF`/`PREFERENCE` are
   `guarded_low`, `REDACTION` is `guarded_high`.
4. Fix stale port references in EVA-OS supervisor: verify openclaw (7040)
   and tool-service (7080) entries in `SERVICE_COMMANDS` are correct.
5. At least 3 integration tests: verify(file.write), verify(shell.run),
   tool-call-extraction round-trip.

**Gate ownership:** 5 delta gates (verify-real, tool-call-extraction,
memory-risk-tier, supervisor-ports-clean, verification-tests).

### Epic C — Voice Production Readiness

**Objective:** Upgrade the voice pipeline from batch-only to streaming-capable
with real default backends and end-to-end binary audio testing.

**Deliverables:**
1. Default backend selection: when no `SONIA_ASR_BACKEND` env var is set,
   auto-detect Ollama availability and default to `OllamaASR`/`OllamaTTS`
   instead of returning stubs. Fall back to stubs only if no provider is
   reachable.
2. Streaming ASR interface: `transcribe_stream()` on `OllamaASR` and
   `QwenASR` yields partial transcripts as audio chunks arrive. Wire into
   the binary PCM WebSocket handler for incremental results.
3. VAD-driven turn detection: `EnergyVAD` triggers end-of-utterance, which
   flushes the ASR buffer and initiates the turn pipeline. Barge-in
   interrupts TTS playback.
4. TTS streaming output: send TTS audio as binary PCM frames over WS as
   they are generated, not as a single blob after full synthesis.
5. E2E binary audio test: send raw PCM bytes over WS, verify transcription
   occurs, verify TTS audio bytes are returned. At minimum with Ollama
   backend (skip if Ollama not available).

**Gate ownership:** 5 delta gates (default-backend-auto, streaming-asr,
vad-turn-detect, tts-streaming, e2e-audio-test).

---

## Explicit Non-Goals (v4.5)

- **Containerization / Docker / K8s.** Still deferred. v4.5 focuses on
  functional convergence. Packaging is v4.6.
- **Multi-host deployment / failover.** Single-host only. Multi-node is v5.x.
- **Electron shell / native UI.** UI remains browser-only. Desktop packaging
  is v4.7+.
- **Auth onboarding flow.** User provisioning is deferred to the deployment
  packaging epic.
- **Memory token budget precision.** The 3.5 chars/token estimate stays for
  now; a tiktoken-based counter is a v4.6 refinement.

---

## Invariants

1. **Floor regression zero-tolerance.** All 33 inherited v4.4 gates must pass
   at every merge point. Any floor regression blocks promotion.
2. **Canonical-only tool execution.** After Epic A, no service may execute
   tools except through openclaw's safety gate. Direct tool execution is a
   promotion blocker.
3. **Canonical-only memory writes.** After Epic A, no service may write to
   memory except through memory-engine. Parallel stores are a promotion
   blocker.
4. **Fail-closed voice.** If no ASR/TTS provider is reachable, the voice WS
   returns a JSON error frame, not silent failure. Binary audio path must
   never hang indefinitely.
5. **Contract pin.** SONIA_CONTRACT stays at `v4.4.0` until GA.

---

## Gate Architecture

- **Floor:** 33 gates inherited from v4.4 (schema 11.0)
- **Delta:** 15 new gates (5 per epic)
- **Total:** 48 gates
- **Script:** `scripts/release/gate-v45.py`
- **Report:** `releases/v4.5.0/gate-report.json`
