#!/usr/bin/env python3
"""Merge LoRA adapter into base model IN-PLACE, push shard-by-shard to HF Hub.

Key difference from merge_push_sharded.py: uses safe_merge=True with
progressbar=True to merge LoRA weights in-place without doubling memory.
Then saves shards one at a time to /tmp and uploads immediately.

Peak memory: ~70GB (base model + adapter + overhead), not 130GB.
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
MAX_SHARD_BYTES = 4 * 1024**3  # 4GB per shard
TEMP_DIR = "/tmp/merge_upload"

# Force temp to /tmp overlay (NOT /workspace NFS which has quota limits)
for v in ("TMPDIR", "TEMP", "TMP"):
    os.environ[v] = "/tmp"

def log(msg):
    print(msg, flush=True)

def fmt_time(s):
    m, s = divmod(int(s), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"

def mem_gb():
    """Current RSS in GB."""
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2)

# ── Startup checks ─────────────────────────────────────────────────────
log("=" * 60)
log("MERGE IN-PLACE + SHARD-BY-SHARD PUSH PIPELINE")
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
log(f"  Max shard:   {MAX_SHARD_BYTES / 1e9:.1f}GB")
log(f"  Temp dir:    {TEMP_DIR}")
log(f"  GPUs:        {torch.cuda.device_count()}")

import shutil
for path in ["/tmp", "/workspace"]:
    usage = shutil.disk_usage(path)
    log(f"  {path}: {usage.free / 1e9:.1f}G free / {usage.total / 1e9:.1f}G total")
log("")

t_start = time.time()

# ── [1/5] Load base model on CPU ───────────────────────────────────────
log("[1/5] Loading base model on CPU...")
t0 = time.time()

from transformers import AutoProcessor, AutoModelForImageTextToText

processor = AutoProcessor.from_pretrained(BASE_MODEL, trust_remote_code=True)
log(f"  Processor loaded ({fmt_time(time.time()-t0)})")

model = AutoModelForImageTextToText.from_pretrained(
    BASE_MODEL,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
    device_map="cpu",
    low_cpu_mem_usage=True,
    use_safetensors=True,
)
log(f"  Model loaded on CPU ({fmt_time(time.time()-t0)})")
log(f"  Model class: {type(model).__name__}")

# ── [2/5] Load adapter + merge IN-PLACE ──────────────────────────────
log("[2/5] Loading LoRA adapter and merging IN-PLACE...")
t0 = time.time()

from peft import PeftModel

peft_model = PeftModel.from_pretrained(model, ADAPTER_DIR)
log(f"  Adapter loaded ({fmt_time(time.time()-t0)})")

# Merge in-place: safe_merge modifies base weights directly,
# then unload removes the adapter layers
# This avoids creating a full copy of all weights
log("  Merging adapter weights in-place...")
merged_model = peft_model.merge_and_unload(safe_merge=True, progressbar=True)
log(f"  Merge complete ({fmt_time(time.time()-t0)})")

gc.collect()

# ── [3/5] Smoke inference ──────────────────────────────────────────────
log("[3/5] Smoke inference on GPU...")
t0 = time.time()

model_gpu = merged_model.to("cuda:0")
messages = [{"role": "user", "content": [{"type": "text", "text": "Say hello in one word."}]}]
text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = processor.tokenizer(text, return_tensors="pt").to("cuda:0")

with torch.no_grad():
    out = model_gpu.generate(**inputs, max_new_tokens=20)

decoded = processor.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
log(f"  Generated: {decoded!r}")
log(f"  Smoke inference passed ({fmt_time(time.time()-t0)})")

merged_model = model_gpu.to("cpu")
del model_gpu, inputs, out
gc.collect()
torch.cuda.empty_cache()

# ── [4/5] Shard-by-shard upload to Hub ─────────────────────────────────
log("[4/5] Uploading model shard-by-shard to HuggingFace Hub...")
t0 = time.time()

from huggingface_hub import HfApi, create_repo
from safetensors.torch import save_file

api = HfApi(token=HF_TOKEN)

# Create repo if needed
try:
    create_repo(HUB_REPO, repo_type="model", private=False, token=HF_TOKEN)
    log(f"  Created repo: {HUB_REPO}")
except Exception as e:
    if "already" in str(e).lower() or "409" in str(e):
        log(f"  Repo already exists: {HUB_REPO}")
    else:
        log(f"  Repo create warning: {e}")

os.makedirs(TEMP_DIR, exist_ok=True)

# Get state dict and compute sharding plan
log("  Getting state dict...")
state_dict = merged_model.state_dict()
log(f"  State dict has {len(state_dict)} tensors")

# Compute size of each tensor
tensor_sizes = {}
for key, tensor in state_dict.items():
    tensor_sizes[key] = tensor.numel() * tensor.element_size()

total_size = sum(tensor_sizes.values())
log(f"  Total model size: {total_size / 1e9:.1f}GB")

# Build shards (group tensors into ~4GB chunks)
shards = []
current_shard = {}
current_size = 0

for key in sorted(state_dict.keys()):
    t_size = tensor_sizes[key]
    if current_size + t_size > MAX_SHARD_BYTES and current_shard:
        shards.append(current_shard)
        current_shard = {}
        current_size = 0
    current_shard[key] = state_dict[key]
    current_size += t_size

if current_shard:
    shards.append(current_shard)

log(f"  Split into {len(shards)} shards")

# Build the index file
weight_map = {}
shard_filenames = []
for i, shard in enumerate(shards):
    if len(shards) == 1:
        fname = "model.safetensors"
    else:
        fname = f"model-{i+1:05d}-of-{len(shards):05d}.safetensors"
    shard_filenames.append(fname)
    for key in shard:
        weight_map[key] = fname

# Upload each shard one at a time
for i, (shard_data, fname) in enumerate(zip(shards, shard_filenames)):
    shard_path = os.path.join(TEMP_DIR, fname)
    shard_size = sum(t.numel() * t.element_size() for t in shard_data.values())
    log(f"  Shard {i+1}/{len(shards)}: {fname} ({shard_size / 1e9:.2f}GB, {len(shard_data)} tensors)")

    # Save to temp
    save_file(shard_data, shard_path)
    log(f"    Saved to {shard_path}")

    # Upload to Hub
    api.upload_file(
        path_or_fileobj=shard_path,
        path_in_repo=fname,
        repo_id=HUB_REPO,
        repo_type="model",
        commit_message=f"Upload shard {i+1}/{len(shards)}: {fname}",
    )
    log(f"    Uploaded to Hub ({fmt_time(time.time()-t0)} elapsed)")

    # Delete temp file immediately to free space
    os.remove(shard_path)

    # Clear shard data from memory
    for key in list(shard_data.keys()):
        del shard_data[key]
    gc.collect()

# Upload index file
if len(shards) > 1:
    index = {
        "metadata": {"total_size": total_size},
        "weight_map": weight_map,
    }
    index_path = os.path.join(TEMP_DIR, "model.safetensors.index.json")
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

    api.upload_file(
        path_or_fileobj=index_path,
        path_in_repo="model.safetensors.index.json",
        repo_id=HUB_REPO,
        repo_type="model",
        commit_message="Upload safetensors index",
    )
    os.remove(index_path)
    log(f"  Uploaded model.safetensors.index.json")

# Free state dict
del state_dict
gc.collect()

log(f"  All {len(shards)} shards uploaded ({fmt_time(time.time()-t0)})")

# ── [5/5] Upload config, processor, tokenizer, README ──────────────────
log("[5/5] Uploading config, processor, and README...")
t0 = time.time()

# Save config files to temp and upload
config_dir = os.path.join(TEMP_DIR, "config_files")
os.makedirs(config_dir, exist_ok=True)

# Save model config
merged_model.config.save_pretrained(config_dir)
# Save processor/tokenizer
processor.save_pretrained(config_dir)

# Upload all config files
for fname in os.listdir(config_dir):
    fpath = os.path.join(config_dir, fname)
    if os.path.isfile(fpath):
        api.upload_file(
            path_or_fileobj=fpath,
            path_in_repo=fname,
            repo_id=HUB_REPO,
            repo_type="model",
            commit_message=f"Upload {fname}",
        )
        log(f"  Uploaded {fname}")

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
log(f"ALL DONE — PIPELINE COMPLETE ({fmt_time(total)})")
log(f"  Model: https://huggingface.co/{HUB_REPO}")
log("=" * 60)
