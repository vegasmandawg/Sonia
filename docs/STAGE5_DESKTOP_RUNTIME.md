# Stage 5 — Desktop Action Runtime + Robust Recovery + Operator UX

## Overview

Stage 5 adds a full desktop action runtime to the Sonia API Gateway. Actions flow
through a plan → validate → execute → verify pipeline with risk-gated approval,
circuit breaker protection, dead letter recovery, and a complete audit trail.

## Architecture

```
User Intent
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  POST /v1/actions/plan                              │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐         │
│  │  PLAN    │→ │ VALIDATE  │→ │ EXECUTE  │→ VERIFY  │
│  │          │  │ 5 checks  │  │ breaker  │          │
│  │ risk +   │  │           │  │ + retry  │          │
│  │ confirm  │  │           │  │          │          │
│  └──────────┘  └───────────┘  └──────────┘         │
│       │              │              │                │
│       │         [FAIL]→ reject  [FAIL]→ dead letter  │
│       │                             │                │
│  [needs confirm] → pending_approval                  │
│                    POST .../approve → execute         │
│                    POST .../deny   → denied           │
└─────────────────────────────────────────────────────┘
```

## Milestones Delivered

### M1: Action Contract + Runtime Skeleton
- `schemas/action.py` — Pydantic models for the full action lifecycle
- `capability_registry.py` — 13 capabilities with risk classification
- `action_pipeline.py` — Plan → Validate → Execute → Verify pipeline
- `action_telemetry.py` — Structured JSONL telemetry per action
- 6 API endpoints: plan, get, approve, deny, list, capabilities

### M2: Recovery Core
- `circuit_breaker.py` — Per-dependency breaker (CLOSED → OPEN → HALF_OPEN)
- `dead_letter.py` — Bounded queue for unrecoverable failures with replay
- `health_supervisor.py` — Background loop monitoring 5 dependencies
- 7 recovery endpoints: health summary, breaker status/reset, dead letter CRUD

### M3: Desktop Adapters + Approval Flow + Audit Trail
- `executors/desktop_exec.py` — 9 Windows-native desktop executors
- `action_audit.py` — Per-action audit trail with lifecycle events
- All 13 capabilities implemented with appropriate risk gating
- Audit trail API for operator review

### M4: Operator UX + Hardening + Release Lock
- Soak test script (`soak_stage5_actions.ps1`)
- Full regression verification (135/137 green, 2 pre-existing pipecat WS)
- Stage 4 backward compatibility smoke (16/16 pass)
- Documentation and release checkpoint

## API Endpoints

### Action Pipeline
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/actions/plan` | Plan and optionally execute an action |
| GET | `/v1/actions/{id}` | Get action state |
| POST | `/v1/actions/{id}/approve` | Approve pending action |
| POST | `/v1/actions/{id}/deny` | Deny pending action |
| GET | `/v1/actions` | List actions (filter by state/session) |
| GET | `/v1/capabilities` | List all 13 capabilities + stats |

### Recovery & Observability
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health/summary` | Health supervisor per-dep states |
| GET | `/v1/breakers` | Circuit breaker states |
| POST | `/v1/breakers/{name}/reset` | Reset breaker to CLOSED |
| GET | `/v1/dead-letters` | List dead letters |
| GET | `/v1/dead-letters/{id}` | Get single dead letter |
| POST | `/v1/dead-letters/{id}/replay` | Replay failed action |
| GET | `/v1/audit-trails` | List audit trails |
| GET | `/v1/audit-trails/{id}` | Get trail for an action |

## 13 Implemented Capabilities

| Intent | Risk | Confirm? | Tags |
|--------|------|----------|------|
| file.read | safe | no | filesystem, readonly |
| file.write | medium | yes | filesystem, write |
| shell.run | medium | yes | shell, compute |
| browser.open | low | yes | browser, network |
| app.launch | medium | yes | desktop, app |
| app.close | high | yes | desktop, app |
| window.focus | safe | no | desktop, window |
| window.list | safe | no | desktop, window, readonly |
| keyboard.type | high | yes | desktop, input |
| keyboard.hotkey | high | yes | desktop, input |
| mouse.click | high | yes | desktop, input |
| clipboard.read | safe | no | desktop, clipboard, readonly |
| clipboard.write | low | no | desktop, clipboard |

## Safety Measures

- **Risk gating**: High-risk actions require operator approval before execution
- **Circuit breaker**: Opens after 5 consecutive openclaw failures, prevents cascade
- **Dead letter queue**: Failed actions captured for inspection and replay
- **Blocked operations**: format, shutdown, del commands blocked; alt+f4 hotkey blocked
- **Input limits**: Keyboard text max 1000 chars; clipboard max 100k chars
- **Bounds checking**: Mouse coordinates validated against 7680x4320 max
- **Audit trail**: Every action lifecycle recorded with timestamps

## Test Summary

| Suite | Tests | Status |
|-------|-------|--------|
| Stage 2 (Turn Pipeline) | 8 | All green |
| Stage 3 (Sessions + Safety) | 25 | All green |
| Stage 4 (Multimodal + Quality) | 26 | All green |
| Stage 5 M1 (Action Pipeline) | 17 | All green |
| Stage 5 M2 (Recovery) | 17 | All green |
| Stage 5 M3 (Desktop Adapters) | 17 | All green |
| Stage 4 Compat | 7 | All green |
| Pre-existing Pipecat WS | 2 | Known failure |
| **Total** | **137** | **135 pass** |

## Files Added/Modified

### New Files (Stage 5)
- `services/api-gateway/schemas/action.py` — Action pipeline Pydantic models
- `services/api-gateway/capability_registry.py` — 13-capability registry
- `services/api-gateway/action_pipeline.py` — Core pipeline + store
- `services/api-gateway/action_telemetry.py` — JSONL telemetry collector
- `services/api-gateway/circuit_breaker.py` — Circuit breaker with registry
- `services/api-gateway/dead_letter.py` — Dead letter queue
- `services/api-gateway/health_supervisor.py` — Background health monitor
- `services/api-gateway/action_audit.py` — Audit trail logger
- `services/openclaw/executors/desktop_exec.py` — 9 desktop executors
- `tests/integration/test_action_plan_execute.py` — 17 pipeline tests
- `tests/integration/test_stage4_compat.py` — 7 compat tests
- `tests/integration/test_recovery_and_dead_letter.py` — 17 recovery tests
- `tests/integration/test_desktop_adapters.py` — 17 desktop tests
- `scripts/soak_stage5_actions.ps1` — Soak test script

### Modified Files
- `services/api-gateway/main.py` — 14 new endpoints + supervisor lifecycle
- `services/openclaw/registry.py` — 9 new tool registrations
