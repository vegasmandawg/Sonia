#!/usr/bin/env python3
"""Upload release infrastructure files to HuggingFace Hub."""
import os
from huggingface_hub import HfApi

TOKEN = os.environ.get("HF_TOKEN", "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")
REPO = "medawgyt/Sonia-Qwen3-VL-32B"
BASE = r"S:\training\hf-release"

api = HfApi(token=TOKEN)

files = [
    ("README.md", "README.md"),
    ("RELEASE_CHECKLIST.md", "RELEASE_CHECKLIST.md"),
    ("RELEASE_NOTES.md", "RELEASE_NOTES.md"),
    ("requirements-release.txt", "requirements-release.txt"),
    ("tools/release/verify_artifacts.py", "tools/release/verify_artifacts.py"),
    ("tools/release/smoke_load.py", "tools/release/smoke_load.py"),
    ("tools/release/build_manifest.py", "tools/release/build_manifest.py"),
    ("tools/release/run_release_gate.py", "tools/release/run_release_gate.py"),
]

for local_rel, hub_path in files:
    local_path = os.path.join(BASE, local_rel)
    print(f"Uploading {local_rel} -> {hub_path}...")
    api.upload_file(
        path_or_fileobj=local_path,
        path_in_repo=hub_path,
        repo_id=REPO,
        repo_type="model",
    )
    print(f"  Done: {hub_path}")

print("\nAll release files uploaded.")
