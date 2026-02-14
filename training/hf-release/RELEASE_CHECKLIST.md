# Sonia-Qwen3-VL-32B Release Checklist

## A. Artifact integrity
- [ ] Exactly one active shard family (of-00014) in production branch
- [ ] All shards contiguous: 00001..00014
- [ ] model.safetensors.index.json references only existing of-00014 files
- [ ] No orphan shard set left in repo root

## B. Config consistency
- [ ] config.json valid JSON
- [ ] generation_config.json valid JSON
- [ ] transformers_version aligned or intentionally documented
- [ ] architecture fields present

## C. Model card quality
- [ ] Real license selected (not placeholder)
- [ ] Base model declared
- [ ] Dataset provenance documented
- [ ] Eval protocol and metrics added
- [ ] Intended/out-of-scope usage defined
- [ ] Limitations and failure modes documented

## D. Reproducibility
- [ ] RELEASE_MANIFEST.json generated
- [ ] SHA256 hashes captured for all shards + critical metadata
- [ ] requirements-release.txt pinned
- [ ] smoke load succeeds on target runtime

## E. Tagging and release
- [ ] Release notes finalized
- [ ] Tag created: vX.Y.Z-rc1 (or vX.Y.Z)
- [ ] Tag pushed to remote
- [ ] GA tag created only after gate pass
