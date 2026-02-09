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
| `connectionStatus` | disconnected, connecting, connected, error |
| `conversationState` | idle, listening, thinking, speaking |
| `emotion` | neutral, warm, stern, thinking, alert, amused, concerned |
| `amplitude` | 0.0-1.0 (audio envelope for mouth motion) |
| `currentViseme` | id + weight + timestamp |
| `micEnabled` / `camEnabled` / `privacyEnabled` | boolean toggles |

### Expression System

- **Color**: emotion maps to red-spectrum color (warm=orange-red, stern=deep-red, etc.)
- **Motion**: idle breathing (sine), thinking tilt, speaking scale pulse
- **Eyes**: placeholder white spheres (will be replaced with proper model)
- **Viseme**: phoneme/viseme mapping from TTS output (future)

### Controls

Bottom bar with: MIC, CAM, Privacy, Hold, Interrupt, Replay Last, Diagnostics

### Theme

Minimalist dark red/black: `#0a0a0a` background, `#cc3333` accent, frameless window.

## Promotion Gate (v2.6)

`S:\scripts\promotion-gate-v26.ps1` — 15 gates total:

| # | Gate | Source |
|---|------|--------|
| 1-12 | v2.5.0 gates | Inherited |
| 13 | Vision privacy hard gate | Track B — zero frames when disabled |
| 14 | UI doesn't block core loop | Track C — gateway <2s under UI load |
| 15 | Model package checksum + rollback | Track A — fallback model defined |

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
- `S:\ui\sonia-avatar\` — Full Electron + React + Three.js application
- `S:\ui\sonia-avatar\electron\main.js` — Electron main process
- `S:\ui\sonia-avatar\src\state\store.ts` — Zustand state management
- `S:\ui\sonia-avatar\src\three\AvatarScene.tsx` — 3D avatar scene
- `S:\ui\sonia-avatar\src\components\ControlBar.tsx` — Operator controls
- `S:\ui\sonia-avatar\src\components\StatusIndicator.tsx` — Status overlay

### Ops
- `S:\scripts\promotion-gate-v26.ps1` — 15-gate promotion checklist
