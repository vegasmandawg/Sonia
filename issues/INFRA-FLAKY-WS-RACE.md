# INFRA-FLAKY-WS-RACE

**Status:** Open
**Priority:** P2
**Owner:** infra
**SLA:** Fix or suppress by v2.9.2
**Marker:** `@pytest.mark.infra_flaky`

## Test

`tests/integration/test_multimodal_turn_pipeline.py::TestMultimodalTurnPipeline::test_text_plus_vision_produces_response`

## Failure Signature

```
WebSocket closed OK race condition (ws protocol timing)
```

The test opens a WebSocket session, sends a text+vision payload, and waits
for `response.final`. On slow CI or under load, the WebSocket connection
closes with code 1000 (OK) before the response frame arrives, causing the
`recv()` to raise `ConnectionClosedOK` instead of delivering the event.

## Root Cause

WebSocket `close_timeout` in the gateway or the ws library default can fire
before the model-router round-trip completes for vision payloads (which are
heavier than text-only).

## Mitigation

- Marked `@pytest.mark.infra_flaky` so it does not block the CI gate.
- Non-blocking: `pytest -m infra_flaky` runs separately.

## Resolution Plan

1. Increase `close_timeout` on the gateway WS handler for vision turns.
2. Add server-side keep-alive pings during long model calls.
3. Verify fix with 10x retry soak before removing marker.
