#!/usr/bin/env python3
"""Streaming LoRA merge: merges adapter into base model shard-by-shard.

Unlike merge_and_unload() which loads the ENTIRE model into RAM (~130GB),
this script processes one safetensor shard at a time:
  1. Load adapter config + weights (1.1GB)
  2. For each base model shard (~4GB):
     a. Load shard tensors
     b. Apply LoRA delta (W' = W + alpha/r * B @ A) to matching layers
     c. Save merged shard to /tmp
     d. Upload to HF Hub
     e. Free shard from memory
  3. Upload config, tokenizer, README

Peak memory: ~6GB (1 shard + adapter weights + overhead).
"""
import gc
import json
import os
import sys
import time

import torch

# ── Config ──────────────────────────────────────────────────────────────
BASE_MODEL = os.getenv("BASE_MODEL", "VocaborSilentii/Qwen3-VL-32B-Instruct")
ADAPTER_DIR = os.getenv("ADAPTER_DIR", "/workspace/output/sonia-lora")
HUB_REPO = os.getenv("HUB_REPO", "VocaborSilentii/Sonia-Qwen3-VL-32B")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
TEMP_DIR = "/tmp/merge_upload"

for v in ("TMPDIR", "TEMP", "TMP"):
    os.environ[v] = "/tmp"

def log(msg):
    print(msg, flush=True)

def fmt_time(s):
    m, s = divmod(int(s), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"

# ── Startup checks ─────────────────────────────────────────────────────
log("=" * 60)
log("STREAMING LORA MERGE + SHARD-BY-SHARD PUSH")
log("=" * 60)

if not HF_TOKEN:
    log("ERROR: HF_TOKEN not set")
    sys.exit(1)

if not os.path.isdir(ADAPTER_DIR):
    log(f"ERROR: Adapter dir not found: {ADAPTER_DIR}")
    sys.exit(1)

log(f"  Base model:  {BASE_MODEL}")
log(f"  Adapter:     {ADAPTER_DIR}")
log(f"  Hub repo:    {HUB_REPO}")
log(f"  Temp dir:    {TEMP_DIR}")

import shutil
for path in ["/tmp"]:
    usage = shutil.disk_usage(path)
    log(f"  {path}: {usage.free / 1e9:.1f}G free / {usage.total / 1e9:.1f}G total")

cgroup_usage = open("/sys/fs/cgroup/memory/memory.usage_in_bytes").read().strip()
cgroup_limit = open("/sys/fs/cgroup/memory/memory.limit_in_bytes").read().strip()
log(f"  cgroup mem: {int(cgroup_usage)/1e9:.1f}G used / {int(cgroup_limit)/1e9:.1f}G limit")
log("")

t_start = time.time()
os.makedirs(TEMP_DIR, exist_ok=True)

# ── [1/5] Load adapter config and weights ──────────────────────────────
log("[1/5] Loading adapter config and LoRA weights...")
t0 = time.time()

adapter_config_path = os.path.join(ADAPTER_DIR, "adapter_config.json")
with open(adapter_config_path) as f:
    adapter_config = json.load(f)

lora_alpha = adapter_config["lora_alpha"]
lora_r = adapter_config["r"]
scaling = lora_alpha / lora_r
target_modules = adapter_config.get("target_modules", [])

log(f"  LoRA config: r={lora_r}, alpha={lora_alpha}, scaling={scaling:.4f}")
log(f"  Target modules: {target_modules}")

from safetensors.torch import load_file as st_load, save_file as st_save

adapter_weights_path = os.path.join(ADAPTER_DIR, "adapter_model.safetensors")
adapter_state = st_load(adapter_weights_path, device="cpu")
log(f"  Adapter weights loaded: {len(adapter_state)} tensors ({fmt_time(time.time()-t0)})")

# Build a map: base_layer_name -> (lora_A, lora_B)
# Adapter keys look like: "base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight"
# We need to map to base key: "model.layers.0.self_attn.q_proj.weight"
lora_pairs = {}
for key in sorted(adapter_state.keys()):
    if ".lora_A." in key:
        # Extract the base layer path
        # Remove "base_model.model." prefix and ".lora_A.weight" suffix
        base_key = key.replace("base_model.model.", "").replace(".lora_A.weight", ".weight")
        b_key = key.replace(".lora_A.", ".lora_B.")
        if b_key in adapter_state:
            lora_pairs[base_key] = (adapter_state[key], adapter_state[b_key])

log(f"  Found {len(lora_pairs)} LoRA pairs to merge")
if len(lora_pairs) == 0:
    log("ERROR: No LoRA pairs found. Check adapter key format.")
    # Debug: print first 10 adapter keys
    for i, k in enumerate(sorted(adapter_state.keys())[:10]):
        log(f"    adapter key [{i}]: {k}")
    sys.exit(1)

# Print a few examples
for i, (k, (a, b)) in enumerate(sorted(lora_pairs.items())[:3]):
    log(f"    {k}: A{list(a.shape)} x B{list(b.shape)}")
if len(lora_pairs) > 3:
    log(f"    ... and {len(lora_pairs)-3} more")

# ── [2/5] Resolve base model safetensor shards ────────────────────────
log("[2/5] Resolving base model shard layout...")
t0 = time.time()

from huggingface_hub import hf_hub_download, HfApi, create_repo

api = HfApi(token=HF_TOKEN)

# Download the index file to find shard layout
index_path = hf_hub_download(
    BASE_MODEL, "model.safetensors.index.json",
    token=HF_TOKEN, cache_dir="/workspace/.hf/hub",
)
with open(index_path) as f:
    base_index = json.load(f)

weight_map = base_index["weight_map"]
total_size = base_index["metadata"]["total_size"]

# Group weights by shard file
shard_to_keys = {}
for tensor_name, shard_file in weight_map.items():
    shard_to_keys.setdefault(shard_file, []).append(tensor_name)

shard_files = sorted(shard_to_keys.keys())
log(f"  Base model: {len(weight_map)} tensors in {len(shard_files)} shards ({total_size/1e9:.1f}GB)")
log(f"  Index resolved ({fmt_time(time.time()-t0)})")

# ── [3/5] Create Hub repo ─────────────────────────────────────────────
log("[3/5] Creating Hub repo...")
try:
    create_repo(HUB_REPO, repo_type="model", private=False, token=HF_TOKEN)
    log(f"  Created repo: {HUB_REPO}")
except Exception as e:
    if "already" in str(e).lower() or "409" in str(e):
        log(f"  Repo already exists: {HUB_REPO}")
    else:
        log(f"  Repo create warning: {e}")

# ── [4/5] Streaming merge + upload ────────────────────────────────────
log("[4/5] Streaming merge: processing each shard...")
t0 = time.time()

RESUME_FROM_SHARD = int(os.getenv("RESUME_FROM_SHARD", "0"))  # 0-indexed
if RESUME_FROM_SHARD > 0:
    log(f"  RESUMING from shard {RESUME_FROM_SHARD+1} (skipping first {RESUME_FROM_SHARD})")

new_weight_map = {}
merge_count = 0

for shard_idx, shard_file in enumerate(shard_files):
    shard_keys = shard_to_keys[shard_file]

    # Always populate weight map (needed for index file)
    for key in shard_keys:
        new_weight_map[key] = shard_file

    # Skip already-uploaded shards on resume
    if shard_idx < RESUME_FROM_SHARD:
        log(f"  Shard {shard_idx+1}/{len(shard_files)}: {shard_file} (SKIPPED — already uploaded)")
        continue

    log(f"  Shard {shard_idx+1}/{len(shard_files)}: {shard_file} ({len(shard_keys)} tensors)")

    # Download this shard
    shard_path = hf_hub_download(
        BASE_MODEL, shard_file,
        token=HF_TOKEN, cache_dir="/workspace/.hf/hub",
    )

    # Load shard tensors
    shard_tensors = st_load(shard_path, device="cpu")
    shard_merged = {}

    for key in shard_keys:
        tensor = shard_tensors[key]

        # Check if this key has a LoRA delta
        if key in lora_pairs:
            lora_a, lora_b = lora_pairs[key]
            # W' = W + scaling * (B @ A)
            # lora_a shape: (r, in_features), lora_b shape: (out_features, r)
            delta = (lora_b @ lora_a) * scaling
            tensor = tensor + delta.to(tensor.dtype)
            merge_count += 1

        shard_merged[key] = tensor

    # Free original shard
    del shard_tensors
    gc.collect()

    # Save merged shard to temp
    merged_shard_path = os.path.join(TEMP_DIR, shard_file)
    st_save(shard_merged, merged_shard_path)

    shard_size = os.path.getsize(merged_shard_path)
    log(f"    Saved ({shard_size/1e9:.2f}GB), merged {sum(1 for k in shard_keys if k in lora_pairs)} layers")

    # Upload to Hub
    api.upload_file(
        path_or_fileobj=merged_shard_path,
        path_in_repo=shard_file,
        repo_id=HUB_REPO,
        repo_type="model",
        commit_message=f"Upload merged shard {shard_idx+1}/{len(shard_files)}: {shard_file}",
    )
    log(f"    Uploaded ({fmt_time(time.time()-t0)} elapsed)")

    # Clean up temp file (may already be gone if upload_file moved it)
    try:
        os.remove(merged_shard_path)
    except FileNotFoundError:
        pass
    del shard_merged
    gc.collect()

log(f"  All {len(shard_files)} shards merged and uploaded ({merge_count} layers merged)")

# Upload index file
new_index = {
    "metadata": {"total_size": total_size},
    "weight_map": new_weight_map,
}
index_out_path = os.path.join(TEMP_DIR, "model.safetensors.index.json")
with open(index_out_path, "w") as f:
    json.dump(new_index, f, indent=2)

api.upload_file(
    path_or_fileobj=index_out_path,
    path_in_repo="model.safetensors.index.json",
    repo_id=HUB_REPO,
    repo_type="model",
    commit_message="Upload safetensors index",
)
os.remove(index_out_path)
log(f"  Uploaded model.safetensors.index.json")

# ── [5/5] Upload config, processor, tokenizer, README ──────────────────
log("[5/5] Uploading config, processor, and README...")
t0 = time.time()

# Download and re-upload base model config files
config_files = [
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
]

# Upload tokenizer files from adapter dir (they include chat template)
tokenizer_files = [
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
]

for fname in tokenizer_files:
    fpath = os.path.join(ADAPTER_DIR, fname)
    if os.path.exists(fpath):
        api.upload_file(
            path_or_fileobj=fpath,
            path_in_repo=fname,
            repo_id=HUB_REPO,
            repo_type="model",
            commit_message=f"Upload {fname}",
        )
        log(f"  Uploaded {fname} (from adapter)")

for fname in config_files:
    try:
        fpath = hf_hub_download(
            BASE_MODEL, fname,
            token=HF_TOKEN, cache_dir="/workspace/.hf/hub",
        )
        api.upload_file(
            path_or_fileobj=fpath,
            path_in_repo=fname,
            repo_id=HUB_REPO,
            repo_type="model",
            commit_message=f"Upload {fname}",
        )
        log(f"  Uploaded {fname} (from base)")
    except Exception as e:
        log(f"  Skipped {fname}: {e}")

# Upload README
readme = f"""---
library_name: transformers
license: other
base_model: {BASE_MODEL}
tags:
- sonia
- qwen3-vl
- lora
- fine-tuned
pipeline_tag: image-text-to-text
---

# Sonia-Qwen3-VL-32B

Fine-tuned [Qwen3-VL-32B-Instruct]({BASE_MODEL}) with LoRA for the Sonia companion AI.

## Training Details

- **Base model**: {BASE_MODEL}
- **Method**: LoRA (r=32, alpha=64, dropout=0.05)
- **Precision**: bf16
- **Hardware**: 2x NVIDIA H100 PCIe 80GB
- **Steps**: 984 (2 epochs)
- **Final eval loss**: 0.1128
- **Final train loss**: 0.2146

## Usage

```python
from transformers import AutoProcessor, AutoModelForImageTextToText
import torch

model = AutoModelForImageTextToText.from_pretrained(
    "{HUB_REPO}",
    torch_dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
processor = AutoProcessor.from_pretrained("{HUB_REPO}", trust_remote_code=True)
```
"""

readme_path = os.path.join(TEMP_DIR, "README.md")
with open(readme_path, "w") as f:
    f.write(readme)

api.upload_file(
    path_or_fileobj=readme_path,
    path_in_repo="README.md",
    repo_id=HUB_REPO,
    repo_type="model",
    commit_message="Add model card",
)
log(f"  Uploaded README.md")

# Cleanup temp
shutil.rmtree(TEMP_DIR, ignore_errors=True)

log(f"  Config + processor uploaded ({fmt_time(time.time()-t0)})")

# ── Done ───────────────────────────────────────────────────────────────
total = time.time() - t_start
log("")
log("=" * 60)
log(f"ALL DONE — STREAMING MERGE COMPLETE ({fmt_time(total)})")
log(f"  Merged {merge_count} LoRA layers across {len(shard_files)} shards")
log(f"  Model: https://huggingface.co/{HUB_REPO}")
log("=" * 60)
