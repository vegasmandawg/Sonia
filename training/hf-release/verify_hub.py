#!/usr/bin/env python3
"""Verify HuggingFace Hub repo artifact consistency (remote, no download)."""
import json
import os
import re
import sys
from huggingface_hub import HfApi, hf_hub_download

TOKEN = os.environ.get("HF_TOKEN", "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")
REPO = "medawgyt/Sonia-Qwen3-VL-32B"
EXPECTED_FAMILY = "00014"

SHARD_RE = re.compile(r"^model-(\d{5})-of-(\d{5})\.safetensors$")

api = HfApi(token=TOKEN)

print("=" * 60)
print("RELEASE GATE: Remote Hub Verification")
print("=" * 60)

# 1. List all files
print("\n[STEP 1] Listing repo files...")
files = api.list_repo_files(REPO, repo_type="model")
print(f"  Total files: {len(files)}")

# 2. Check required files
required = ["README.md", "config.json", "generation_config.json", "model.safetensors.index.json"]
for r in required:
    if r in files:
        print(f"  [OK] {r}")
    else:
        print(f"  [FAIL] Missing: {r}")
        sys.exit(1)

# 3. Check shard families
shards = [f for f in files if SHARD_RE.match(f)]
families = {}
for s in shards:
    m = SHARD_RE.match(s)
    of = m.group(2)
    families.setdefault(of, []).append(s)

print(f"\n[STEP 2] Shard families found: {sorted(families.keys())}")
if EXPECTED_FAMILY not in families:
    print(f"  [FAIL] Expected family of-{EXPECTED_FAMILY} not found")
    sys.exit(1)

if len(families) > 1:
    print(f"  [FAIL] Multiple shard families: {sorted(families.keys())}")
    sys.exit(1)
print(f"  [OK] Single shard family: of-{EXPECTED_FAMILY}")

# Check contiguity
expected = [f"model-{i:05d}-of-{EXPECTED_FAMILY}.safetensors" for i in range(1, int(EXPECTED_FAMILY) + 1)]
actual = sorted(families[EXPECTED_FAMILY])
if actual == expected:
    print(f"  [OK] All {len(actual)} shards contiguous and complete")
else:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        print(f"  [FAIL] Missing shards: {missing}")
    if extra:
        print(f"  [FAIL] Extra shards: {extra}")
    sys.exit(1)

# 4. Download and verify index
print("\n[STEP 3] Verifying index...")
idx_path = hf_hub_download(REPO, "model.safetensors.index.json", token=TOKEN)
with open(idx_path, "r") as f:
    idx = json.load(f)

weight_map = idx.get("weight_map", {})
if not weight_map:
    print("  [FAIL] Empty weight_map")
    sys.exit(1)

mapped_files = set(weight_map.values())
family_refs = sorted({SHARD_RE.match(m).group(2) for m in mapped_files if SHARD_RE.match(m)})
if family_refs != [EXPECTED_FAMILY]:
    print(f"  [FAIL] Index references families: {family_refs}")
    sys.exit(1)
print(f"  [OK] Index weight_map references only of-{EXPECTED_FAMILY}")
print(f"  [OK] {len(weight_map)} weight entries across {len(mapped_files)} unique shards")

# 5. Download and verify configs
print("\n[STEP 4] Verifying configs...")
cfg_path = hf_hub_download(REPO, "config.json", token=TOKEN)
gen_path = hf_hub_download(REPO, "generation_config.json", token=TOKEN)

with open(cfg_path) as f:
    cfg = json.load(f)
with open(gen_path) as f:
    gen = json.load(f)

if "architectures" in cfg:
    print(f"  [OK] architectures: {cfg['architectures']}")
else:
    print("  [WARN] No architectures field")

cfg_tv = cfg.get("transformers_version")
gen_tv = gen.get("transformers_version")
if cfg_tv and gen_tv and cfg_tv != gen_tv:
    print(f"  [WARN] transformers_version mismatch: config={cfg_tv} gen={gen_tv}")
else:
    print(f"  [OK] transformers_version aligned: {cfg_tv}")

# 6. Check release infrastructure files
print("\n[STEP 5] Checking release infrastructure...")
release_files = [
    "RELEASE_CHECKLIST.md", "RELEASE_NOTES.md", "requirements-release.txt",
    "tools/release/verify_artifacts.py", "tools/release/smoke_load.py",
    "tools/release/build_manifest.py", "tools/release/run_release_gate.py",
]
for rf in release_files:
    if rf in files:
        print(f"  [OK] {rf}")
    else:
        print(f"  [FAIL] Missing: {rf}")
        sys.exit(1)

# Summary
print("\n" + "=" * 60)
print("RELEASE GATE: ALL CHECKS PASS")
print(f"  Repo: {REPO}")
print(f"  Files: {len(files)}")
print(f"  Shards: {len(actual)} (of-{EXPECTED_FAMILY})")
print(f"  Weights: {len(weight_map)} entries")
print(f"  Architecture: {cfg.get('architectures', ['unknown'])}")
print("=" * 60)
