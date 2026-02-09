# Stage 8: Companion Experience Layer (v2.6)

> v2.5.0 proved reliability, recovery, and release discipline.
> v2.6 spends that reliability budget on what makes Sonia feel alive.

## Overview

v2.6 delivers the **Companion Experience Layer** across three parallel tracks:

| Track | Focus | Exit Gate |
|-------|-------|-----------|
| **A** | Persona + Fine-tune Pipeline | Tool misuse -50%, persona consistency up, no safety regression |
| **B** | Vision Presence | Zero inference when privacy off, latency target met, stable GPU |
| **C** | Embodiment UI | Lip sync drift acceptable, UI never blocks core loop, crash recovery |

## Track A: Persona + Fine-tune Pipeline

### Dataset Contract

All datasets live under `S:\datasets\` with the following structure:

```
S:\datasets\
  text\raw\           # Unprocessed conversation data
  text\curated\       # Human-reviewed, quality-filtered
  text\processed\     # Pipeline output (normalized, deduped, classified)
  vision\raw\         # Image/video training data
  speech\raw\         # Audio training data
  manifests\          # Dataset manifests (integrity, lineage)
  exports\jsonl\      # Final JSONL exports (train/val/test splits)
```

### Manifest Schema

Every dataset gets a manifest (`S:\datasets\manifests\schema.py`):
- `name`, `version`, `source`, `license`
- `schema_version`, `filters`, `tags`
- Per-file SHA-256 hash list
- Verification: `manifest.verify(base_dir)` returns integrity errors

### Processing Pipeline

Deterministic 5-stage pipeline (`S:\pipeline\text\process.py`):

1. **Normalize** — NFC unicode, strip C0 control chars, collapse whitespace
2. **Deduplicate** — SHA-256 content hash, first-occurrence wins
3. **Classify** — Keyword/heuristic: style, tool_use, roleplay, refusal, instruction, knowledge, correction, other
4. **Split** — Stratified by category: 85/10/5 train/val/test (seed=42)
5. **Export** — JSONL with internal metadata stripped

### Identity Invariant Enforcement

`S:\pipeline\text\identity_invariants.py` ensures training data doesn't hardcode identity facts:

- **Philosophy**: "Sonia-ness" = fine-tuned *style* and *behavior*, NOT baked identity
- **Anchors detected**: name patterns, wake words, creator claims, platform references
- **Modes**: `audit` (flag and keep) or `enforce` (flag and remove)
- **Report**: violation rate, per-conversation details, saved as JSON

### Evaluation Harness

`S:\pipeline\eval\harness.py` — fixed evaluation suite with 5 dimensions:

| Dimension | What it checks | Checker |
|-----------|---------------|---------|
| **Consistency** | Persona markers present, forbidden markers absent | `check_consistency` |
| **Verbosity** | Response length within bounds | `check_verbosity` |
| **Refusal** | Correctly refuses/complies | `check_refusal` |
| **Tool misuse** | No hallucinated/malformed tool calls | `check_tool_misuse` |
| **Regression** | Known-good prompts still handled correctly | `check_regression` |

Seed prompts: `S:\pipeline\eval\seed_prompts.jsonl` (13 initial prompts)

### Fine-tune Plan

1. LoRA/QLoRA SFT on curated text (persona + tool discipline)
2. Small "tool-use correction" set: bad tool calls -> corrected tool calls
3. Evaluate with fixed harness after each training run
4. Model package with checksums and rollback path

## Track B: Vision Presence

### Vision Capture Service (`S:\services\vision-capture\`)

Port: **7060** | Health: `/healthz`

**Ring Buffer**: RAM-based deque, 300 frames max (~30s at 10fps)

**Modes**:
- `off` — no capture, buffer cleared
- `ambient` — 1 fps, 320x240 (low resource)
- `active` — 10 fps, 640x480 (on-demand)

**Privacy Controls**:
- Hardware toggle state respected
- Software toggle: `POST /v1/vision/privacy` with `enabled`/`disabled`
- When disabled: buffer is **immediately cleared**, mode forced to `off`
- **Hard gate**: zero frames accepted when privacy disabled (403)

**Endpoints**:
- `GET /v1/vision/status` — current state
- `POST /v1/vision/privacy` — toggle privacy
- `POST /v1/vision/mode` — switch off/ambient/active
- `POST /v1/vision/frames` — push frame (from webcam client)
- `GET /v1/vision/frames/latest?n=1` — retrieve recent frames
- `DELETE /v1/vision/buffer` — explicit clear

**Limits**: 1MB max frame, rate-limited per mode FPS

### Perception Pipeline (`S:\services\perception\`)

Port: **7070** | Health: `/healthz`

**Event-driven**: only runs VLM on triggers:
- `wake_word` — user said the wake word with visual intent
- `motion` — significant motion detected in frame delta
- `user_command` — explicit "what do you see?" type request
- `scheduled` — periodic ambient check (if configured)

**Output**: Structured `SceneAnalysis`:
```json
{
  "scene_id": "uuid",
  "summary": "User is at their desk, laptop open, coffee cup visible",
  "entities": [{"label": "laptop", "confidence": 0.92}, ...],
  "overall_confidence": 0.85,
  "recommended_action": "No action needed",
  "action_requires_confirmation": true,
  "inference_ms": 450.2,
  "model_used": "ollama/qwen2-vl:7b"
}
```

**Key constraint**: `action_requires_confirmation` is **always true** — no auto-execution from perception.

## Track C: Embodiment UI

### Stack

- **Electron** + **React** + **Three.js** (via @react-three/fiber)
- **Zustand** for state management
- Local WebSocket from backend for real-time state

### Architecture (`S:\ui\sonia-avatar\`)

```
electron/
  main.js         # Electron main process
  preload.js      # Safe IPC bridge
src/
  main.tsx        # React entry
  App.tsx         # Root component (Canvas + Controls)
  state/
    store.ts      # Zustand store (connection, conversation, emotion, viseme, controls)
  three/
    AvatarScene.tsx  # 3D scene with expression-driven avatar
  components/
    ControlBar.tsx      # Bottom operator controls
    StatusIndicator.tsx # Connection + emotion overlay
```

### State Model

| State | Values |
|-------|--------|
| `connectionStatus` | disconnected, connecting, connected, reconnecting, error |
| `conversationState` | idle, listening, thinking, speaking |
| `emotion` | neutral, warm, stern, thinking, alert, amused, concerned |
| `amplitude` | 0.0-1.0 (audio envelope for mouth motion) |
| `currentViseme` | id + weight + timestamp |
| `micEnabled` / `camEnabled` / `privacyEnabled` / `holdActive` | boolean toggles with ACK |
| `pendingControls` | PendingControl[] (field, targetValue, sentAt, timeoutMs) |
| `interruptPending` / `replayPending` | boolean (fire-and-forget + ACK) |
| `diagnostics` | DiagnosticsData (session, latency, breakers, DLQ, vision) |

### ACK Model (v2.6-c1)

All control toggles use **optimistic update with rollback**:
1. UI toggles state immediately (optimistic)
2. Sends command to backend via WS
3. Backend processes and sends `ack.control` or `nack.control`
4. On ACK: pending cleared, state confirmed
5. On NACK: state rolled back to pre-toggle value
6. On timeout (5s): state rolled back automatically

### Connection Manager

`src/state/connection.ts` -- singleton WS client:
- 5-state FSM: disconnected -> connecting -> connected (-> reconnecting -> ...)
- Exponential backoff: 1s, 2s, 4s, 8s, 16s cap, max 20 attempts
- Auto-connect on mount, disconnect on unmount
- ACK expiry timer runs every 1s

### Expression System

- **Color**: emotion maps to red-spectrum color (warm=orange-red, stern=deep-red, etc.)
- **Motion**: idle breathing (sine), thinking tilt, speaking scale pulse
- **Eyes**: placeholder white spheres (will be replaced with proper model)
- **Viseme**: phoneme/viseme mapping from TTS output (future)

### Controls

Bottom bar with: MIC, CAM, Privacy, Hold, Interrupt, Replay Last, Diagnostics

- **MIC/CAM/Privacy/Hold**: ACK model (optimistic + rollback), disabled when disconnected
- **Interrupt**: only enabled when `conversationState` is speaking/thinking
- **Replay**: only enabled when idle
- **Diagnostics**: toggles slide-out panel (no ACK needed, client-only)

### Theme

Minimalist dark red/black: `#0a0a0a` background, `#cc3333` accent, frameless window.

### Diagnostics Panel

`src/components/DiagnosticsPanel.tsx` -- slide-out (right side):
- Session ID, uptime, turn count
- Latency breakdown: ASR, Model, Tool, Memory, Total (ms)
- Circuit breaker states (CLOSED/OPEN/HALF_OPEN with color coding)
- DLQ depth
- Vision privacy status + buffer frame count
- Last error (if any)

## Cross-Track Integration

### Unified Event Envelope

`services/shared/events.py` -- shared event contract:
- `EventType` enum: 20 cross-service event types
- `EventEnvelope`: id, timestamp, type, source, correlation_id, payload
- `generate_correlation_id()`: `req_XXXX` format (12 hex chars)
- `ensure_correlation_id()`: propagate existing or generate new
- `envelope.derive()`: create child event preserving correlation_id
- `validate_envelope()`: structural validation

### Correlation ID Rules
1. If inbound event has a correlation_id, propagate it
2. If no correlation_id, generate one (`req_XXXX` format)
3. All downstream events and logs must carry the same correlation_id

## Promotion Gate (v2.6)

`S:\scripts\promotion-gate-v26.ps1` -- 16 gates across 6 categories:

| # | Gate | Category |
|---|------|----------|
| 1 | Regression test suite | regression |
| 2 | v2.6 cross-track tests (17) | regression |
| 3 | All 6 core services healthy | health |
| 4 | Vision + perception services healthy | health |
| 5 | Circuit breakers all CLOSED | recovery |
| 6 | Dead letter queue empty | recovery |
| 7 | Chaos suite passes | recovery |
| 8 | Dependencies frozen | artifacts |
| 9 | Release manifest exists | artifacts |
| 10 | Rollback script exists | artifacts |
| 11 | Incident bundle script exists | artifacts |
| 12 | Diagnostics snapshot works | observability |
| 13 | Correlation IDs present | observability |
| 14 | Vision privacy hard gate | companion |
| 15 | UI doesn't block core loop | companion |
| 16 | Model package checksum + rollback | companion |

Machine-readable JSON report (schema v2.0) with per-gate timing and environment metadata.

### Rollback

`scripts/rollback-to-v25.ps1` -- safe rollback to v2.5.0-rc1:
- `-DryRun` support (validate without executing)
- Rollback markers saved to `S:\reports\rollback\`
- Stops all services (including v2.6-new: 7060, 7070)
- Checks out target tag, restarts, verifies health

## New Services

| Service | Port | Description |
|---------|------|-------------|
| vision-capture | 7060 | Camera capture, ring buffer, privacy controls |
| perception | 7070 | Event-driven VLM inference, scene analysis |

## File Inventory

### Track A
- `S:\datasets\manifests\schema.py` — manifest schema + verification
- `S:\pipeline\text\process.py` — 5-stage text processing pipeline
- `S:\pipeline\text\identity_invariants.py` — identity anchor enforcement
- `S:\pipeline\eval\harness.py` — 5-dimension evaluation harness
- `S:\pipeline\eval\seed_prompts.jsonl` — 13 seed eval prompts

### Track B
- `S:\services\vision-capture\main.py` — FastAPI vision capture service
- `S:\services\perception\main.py` — FastAPI perception pipeline

### Track C
- `S:\ui\sonia-avatar\` -- Full Electron + React + Three.js application
- `S:\ui\sonia-avatar\electron\main.js` -- Electron main process
- `S:\ui\sonia-avatar\src\state\store.ts` -- Zustand state (5-state FSM, ACK model)
- `S:\ui\sonia-avatar\src\state\connection.ts` -- ConnectionManager (WS + reconnect)
- `S:\ui\sonia-avatar\src\three\AvatarScene.tsx` -- 3D avatar scene
- `S:\ui\sonia-avatar\src\components\ControlBar.tsx` -- Operator controls (ACK wired)
- `S:\ui\sonia-avatar\src\components\StatusIndicator.tsx` -- Status overlay (5-state)
- `S:\ui\sonia-avatar\src\components\DiagnosticsPanel.tsx` -- Diagnostics slide-out

### Cross-Track
- `S:\services\shared\events.py` -- Unified event envelope + correlation IDs

### Tests
- `S:\tests\integration\test_v26_cross_track.py` -- 17 integration tests

### Ops
- `S:\scripts\promotion-gate-v26.ps1` -- 16-gate promotion checklist (machine-readable)
- `S:\scripts\rollback-to-v25.ps1` -- Safe rollback to v2.5.0

## Commit History

| Commit | Description |
|--------|-------------|
| `dddebe22` | Foundation: 25 files, 2554 lines across 3 tracks |
| `2c845496` | v2.6-a1: CLI + deterministic artifacts + schema v1.1.0 |
| `f88e6174` | v2.6-a2: invariant severity + enforce-mode + fixtures |
| `61bb6799` | v2.6-b1: capture privacy endpoints + zero-frame guarantees |
| `52268bf2` | v2.6-b2: perception event contract + SceneAnalysis validation |
| `6a380446` | v2.6-c1: UI control ACK model + diagnostics panel |
| `f9745418` | v2.6-i1: unified event envelope + 17 integration tests |
| `f496fcb2` | v2.6-g1: 16-gate promotion + machine-readable reports |
