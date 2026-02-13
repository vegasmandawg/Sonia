# INFRA-FLAKY-OLLAMA-TIMEOUT

**Status:** Open
**Priority:** P2
**Owner:** infra
**SLA:** Fix or suppress by v2.9.2
**Marker:** `@pytest.mark.infra_flaky`

## Tests

1. `tests/integration/test_multimodal_turn_pipeline.py::TestMultimodalTurnPipeline::test_sync_turn_has_quality_and_latency`
2. `tests/integration/test_phase2_e2e.py::TestAPIGatewayChat::test_chat_endpoint_exists`

## Failure Signature

```
test_sync_turn_has_quality_and_latency:
  Ollama model timeout (ok: False from slow model response)

test_chat_endpoint_exists:
  httpx.ReadTimeout against live Ollama
```

Both tests hit the `/v1/turn` or `/v1/chat` endpoint which routes to the
local Ollama instance. When Ollama is cold-starting, loading weights, or
under memory pressure, the response exceeds the default httpx timeout
(typically 30s), causing a `ReadTimeout`.

## Root Cause

Ollama model load time is non-deterministic. First inference after restart
can take 10-60s depending on model size and GPU/CPU load. The test timeout
does not account for cold-start latency.

## Mitigation

- Both tests marked `@pytest.mark.infra_flaky`.
- Non-blocking: `pytest -m infra_flaky` runs separately.

## Resolution Plan

1. Add a pre-test warm-up fixture that sends a throwaway inference to Ollama.
2. Increase httpx timeout to 90s for integration tests hitting live models.
3. Consider a `pytest-retry` plugin with 2 retries for `infra_flaky` tests.
4. Verify with 10x soak before removing markers.
