# Release Notes — Sonia-Qwen3-VL-32B v1.0.0

## Summary
Production hardening release for merged 14-shard Sonia-Qwen3-VL-32B package.

## Included
- Deterministic artifact verification scripts
- SHA256 release manifest generation
- Smoke load test for processor + model
- Hardened model card with reproducibility contract
- Pinned release dependency spec

## Packaging invariants
- Active shard family: of-00014
- Index consistency: PASS
- Manifest generated: PASS
- Smoke load: PASS

## Known limitations
- Anchor tags from training data may appear in outputs (sonia-persona-dense-NNNNN)
- OCR edge cases with small text / low-contrast regions
- Multi-image context coherence limits

## Upgrade notes
- Replace prior release references with tag `v1.0.0`
- Pin runtime deps to release spec
