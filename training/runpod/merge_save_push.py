#!/usr/bin/env python3
"""Merge LoRA adapter into base model, save to NFS, upload to HuggingFace Hub."""
import gc
import os
import sys
import time

import torch

# ── Config ──────────────────────────────────────────────────────────────
BASE_MODEL = "VocaborSilentii/Qwen3-VL-32B-Instruct"
ADAPTER_DIR = "/workspace/output/sonia-lora"
SAVE_DIR = "/workspace/output/sonia-merged"
HUB_REPO = "VocaborSilentii/Sonia-Qwen3-VL-32B"
HF_TOKEN = os.environ.get("HF_TOKEN", "")
MAX_SHARD = "4GB"

# Redirect temp files to NFS (container /tmp is too small)
os.environ["TMPDIR"] = "/workspace/tmp"
os.environ["TEMP"] = "/workspace/tmp"
os.environ["TMP"] = "/workspace/tmp"
os.makedirs("/workspace/tmp", exist_ok=True)

def log(msg):
    print(msg, flush=True)

def fmt_time(s):
    m, s = divmod(int(s), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"

# ── Startup checks ─────────────────────────────────────────────────────
log("=" * 60)
log("MERGE + SAVE + PUSH PIPELINE")
log("=" * 60)

if not HF_TOKEN:
    log("ERROR: HF_TOKEN not set")
    sys.exit(1)

if not os.path.isdir(ADAPTER_DIR):
    log(f"ERROR: Adapter dir not found: {ADAPTER_DIR}")
    sys.exit(1)

adapter_cfg = os.path.join(ADAPTER_DIR, "adapter_config.json")
adapter_weights = os.path.join(ADAPTER_DIR, "adapter_model.safetensors")
if not os.path.exists(adapter_cfg) or not os.path.exists(adapter_weights):
    log(f"ERROR: Missing adapter files in {ADAPTER_DIR}")
    sys.exit(1)

log(f"  Base model:  {BASE_MODEL}")
log(f"  Adapter:     {ADAPTER_DIR}")
log(f"  Save dir:    {SAVE_DIR}")
log(f"  Hub repo:    {HUB_REPO}")
log(f"  GPUs:        {torch.cuda.device_count()}")
log(f"  TMPDIR:      {os.environ['TMPDIR']}")
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

# ── [2/5] Load adapter + merge ─────────────────────────────────────────
log("[2/5] Loading LoRA adapter and merging...")
t0 = time.time()

from peft import PeftModel

model = PeftModel.from_pretrained(model, ADAPTER_DIR)
log(f"  Adapter loaded ({fmt_time(time.time()-t0)})")

model = model.merge_and_unload()
log(f"  Merge complete ({fmt_time(time.time()-t0)})")

gc.collect()

# ── [3/5] Smoke inference ──────────────────────────────────────────────
log("[3/5] Smoke inference on GPU...")
t0 = time.time()

model_gpu = model.to("cuda:0")

messages = [{"role": "user", "content": [{"type": "text", "text": "Say hello in one word."}]}]
text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = processor.tokenizer(text, return_tensors="pt").to("cuda:0")

with torch.no_grad():
    out = model_gpu.generate(**inputs, max_new_tokens=20)

decoded = processor.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
log(f"  Generated: {decoded!r}")
log(f"  Smoke inference passed ({fmt_time(time.time()-t0)})")

# Move back to CPU and free GPU
model = model_gpu.to("cpu")
del model_gpu, inputs, out
gc.collect()
torch.cuda.empty_cache()

# ── [4/5] Save to NFS ─────────────────────────────────────────────────
log("[4/5] Saving merged model to NFS...")
t0 = time.time()

os.makedirs(SAVE_DIR, exist_ok=True)

model.save_pretrained(SAVE_DIR, max_shard_size=MAX_SHARD)
log(f"  Model saved ({fmt_time(time.time()-t0)})")

processor.save_pretrained(SAVE_DIR)
log(f"  Processor saved")

# Write model card
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
with open(os.path.join(SAVE_DIR, "README.md"), "w") as f:
    f.write(readme)
log(f"  README.md written")

# Count files
files = os.listdir(SAVE_DIR)
total_bytes = sum(os.path.getsize(os.path.join(SAVE_DIR, f)) for f in files if os.path.isfile(os.path.join(SAVE_DIR, f)))
log(f"  {len(files)} files, {total_bytes / 1e9:.1f} GB total")
log(f"  Save complete ({fmt_time(time.time()-t0)})")

# Free model from memory
del model
gc.collect()

# ── [5/5] Upload to HuggingFace Hub ───────────────────────────────────
log("[5/5] Uploading to HuggingFace Hub...")
t0 = time.time()

from huggingface_hub import HfApi, create_repo

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

# Upload folder (reads from NFS, streams to Hub — no /tmp usage)
api.upload_folder(
    folder_path=SAVE_DIR,
    repo_id=HUB_REPO,
    repo_type="model",
    commit_message="Upload Sonia-Qwen3-VL-32B (LoRA merged, bf16)",
)
log(f"  Upload complete ({fmt_time(time.time()-t0)})")

# ── Done ───────────────────────────────────────────────────────────────
total = time.time() - t_start
log("")
log("=" * 60)
log(f"PIPELINE COMPLETE ({fmt_time(total)})")
log(f"  Model: https://huggingface.co/{HUB_REPO}")
log("=" * 60)
