#!/usr/bin/env python3
"""Create GA tag on HuggingFace Hub repo."""
import os
from huggingface_hub import HfApi

TOKEN = os.environ.get("HF_TOKEN", "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")
REPO = "medawgyt/Sonia-Qwen3-VL-32B"
TAG = "v1.0.0"

api = HfApi(token=TOKEN)

# Create tag on the main branch
print(f"Creating tag {TAG} on {REPO}...")
api.create_tag(
    repo_id=REPO,
    repo_type="model",
    tag=TAG,
    tag_message=f"GA release: Sonia-Qwen3-VL-32B {TAG} — 14-shard merged LoRA, release gate PASS",
)
print(f"[OK] Tag {TAG} created on {REPO}")
print(f"     https://huggingface.co/{REPO}/tree/{TAG}")
