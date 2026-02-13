#!/usr/bin/env python3
"""Upload patched files to HF dataset repo."""
from huggingface_hub import HfApi

TOKEN = "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"
REPO_ID = "VocaborSilentii/SoniaTraining"

api = HfApi(token=TOKEN)

files = [
    ("train_sonia_qwen3vl.py", "train_sonia_qwen3vl.py"),
    ("scripts/smoke_load_qwen3vl.py", "scripts/smoke_load_qwen3vl.py"),
    ("RUNBOOK.md", "RUNBOOK.md"),
]

for local, remote in files:
    print(f"Uploading {local} -> {remote}...")
    api.upload_file(
        path_or_fileobj=local,
        path_in_repo=remote,
        repo_id=REPO_ID,
        repo_type="dataset",
    )
    print(f"  Done.")

print("All files uploaded.")
