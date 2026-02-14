#!/usr/bin/env python3
"""Upload combined dataset + training scripts to HuggingFace dataset repo."""
import os
from huggingface_hub import HfApi, create_repo

TOKEN = os.environ.get("HF_TOKEN", "")
if not TOKEN:
    print("ERROR: HF_TOKEN not set. Export it first:")
    print("  set HF_TOKEN=hf_xxx   (Windows)")
    print("  export HF_TOKEN=hf_xxx (Linux)")
    exit(1)
REPO_ID = "VocaborSilentii/SoniaTraining"
REPO_TYPE = "dataset"

api = HfApi(token=TOKEN)

# Create repo if needed
try:
    create_repo(REPO_ID, repo_type=REPO_TYPE, private=True, token=TOKEN)
    print(f"Created repo: {REPO_ID}")
except Exception as e:
    if "already" in str(e).lower() or "409" in str(e):
        print(f"Repo {REPO_ID} already exists")
    else:
        print(f"Repo create: {e}")

# Upload data files
data_dir = r"S:\training\runpod\data"
for fname in os.listdir(data_dir):
    fpath = os.path.join(data_dir, fname)
    if not os.path.isfile(fpath):
        continue
    print(f"Uploading data/{fname} ({os.path.getsize(fpath) / 1024:.0f} KB)...")
    api.upload_file(
        path_or_fileobj=fpath,
        path_in_repo=f"data/{fname}",
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
    )

# Upload training scripts and config
scripts = [
    (r"S:\training\runpod\train_sonia_qwen3vl.py", "train_sonia_qwen3vl.py"),
    (r"S:\training\runpod\setup_and_train.sh", "setup_and_train.sh"),
    (r"S:\training\runpod\requirements.txt", "requirements.txt"),
    (r"S:\training\runpod\combine_datasets.py", "combine_datasets.py"),
    (r"S:\training\runpod\combine_datasets_v2.py", "combine_datasets_v2.py"),
    (r"S:\training\runpod\merge_push_direct.py", "merge_push_direct.py"),
    (r"S:\training\runpod\test_merged_model.py", "test_merged_model.py"),
    (r"S:\training\runpod\quantize_gguf_v2.py", "quantize_gguf_v2.py"),
    (r"S:\training\runpod\scripts\smoke_load_qwen3vl.py", "scripts/smoke_load_qwen3vl.py"),
    (r"S:\training\runpod\RUNBOOK.md", "RUNBOOK.md"),
]
for local_path, repo_path in scripts:
    if not os.path.exists(local_path):
        print(f"  SKIP: {local_path} not found")
        continue
    size = os.path.getsize(local_path) / 1024
    print(f"Uploading {repo_path} ({size:.0f} KB)...")
    api.upload_file(
        path_or_fileobj=local_path,
        path_in_repo=repo_path,
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
    )

print(f"\nAll files uploaded to https://huggingface.co/datasets/{REPO_ID}")
