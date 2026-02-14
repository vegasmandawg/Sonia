#!/usr/bin/env python3
"""
Full GGUF quantization pipeline for Sonia-Qwen3-VL-32B.
Steps:
  1. Clone llama.cpp and install Python deps
  2. Download merged model from HF Hub
  3. Convert to F16 GGUF (model + mmproj)
  4. Quantize to Q4_K_M and Q8_0
  5. Upload all GGUF files to HF Hub
"""
import os, sys, time, subprocess, shutil

HF_TOKEN = os.environ.get("HF_TOKEN", "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")
MODEL_REPO = "VocaborSilentii/Sonia-Qwen3-VL-32B"
GGUF_REPO = "VocaborSilentii/Sonia-Qwen3-VL-32B-GGUF"
WORK_DIR = "/workspace/quantize"
LLAMA_CPP_DIR = "/workspace/llama.cpp"
MODEL_DIR = f"{WORK_DIR}/model"
GGUF_DIR = f"{WORK_DIR}/gguf"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run(cmd, cwd=None, check=True):
    log(f"  CMD: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=False)
    if check and result.returncode != 0:
        log(f"  FAILED (exit {result.returncode})")
        sys.exit(1)
    return result

def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(GGUF_DIR, exist_ok=True)

    # ──────────────────────────────────────────────
    # Step 1: Clone llama.cpp and install deps
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("STEP 1: Setting up llama.cpp")
    log("=" * 60)

    if not os.path.exists(LLAMA_CPP_DIR):
        run(f"git clone --depth 1 https://github.com/ggml-org/llama.cpp.git {LLAMA_CPP_DIR}")
    else:
        log("  llama.cpp already cloned, pulling latest...")
        run("git pull", cwd=LLAMA_CPP_DIR)

    # Install Python requirements for convert script
    reqs_file = f"{LLAMA_CPP_DIR}/requirements.txt"
    if os.path.exists(reqs_file):
        run(f"pip install -r {reqs_file}")
    # Also need gguf package
    run("pip install gguf")

    # Build llama-quantize (needs cmake)
    log("Building llama-quantize...")
    build_dir = f"{LLAMA_CPP_DIR}/build"
    os.makedirs(build_dir, exist_ok=True)
    run(f"cmake .. -DGGML_CUDA=OFF", cwd=build_dir)
    run(f"cmake --build . --target llama-quantize -j$(nproc)", cwd=build_dir)

    quantize_bin = f"{build_dir}/bin/llama-quantize"
    if not os.path.exists(quantize_bin):
        log(f"  ERROR: llama-quantize not found at {quantize_bin}")
        sys.exit(1)
    log(f"  llama-quantize built: {quantize_bin}")

    # ──────────────────────────────────────────────
    # Step 2: Download model from HF Hub
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("STEP 2: Downloading model from HuggingFace Hub")
    log("=" * 60)

    if os.path.exists(f"{MODEL_DIR}/config.json"):
        log("  Model directory already exists, skipping download")
    else:
        from huggingface_hub import snapshot_download
        t0 = time.time()
        snapshot_download(
            repo_id=MODEL_REPO,
            local_dir=MODEL_DIR,
            token=HF_TOKEN,
            ignore_patterns=["*.md", "*.txt", "tools/*", "RELEASE*"],
        )
        log(f"  Download complete ({time.time()-t0:.0f}s)")

    # Verify download
    safetensors = [f for f in os.listdir(MODEL_DIR) if f.endswith(".safetensors")]
    log(f"  Found {len(safetensors)} safetensors files")

    # ──────────────────────────────────────────────
    # Step 3: Convert to F16 GGUF
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("STEP 3: Converting to F16 GGUF")
    log("=" * 60)

    convert_script = f"{LLAMA_CPP_DIR}/convert_hf_to_gguf.py"

    # 3a: Convert main model to F16
    f16_gguf = f"{GGUF_DIR}/Sonia-Qwen3-VL-32B-F16.gguf"
    if os.path.exists(f16_gguf):
        log(f"  F16 GGUF already exists: {f16_gguf}")
    else:
        t0 = time.time()
        run(f"python3 {convert_script} {MODEL_DIR} --outfile {f16_gguf} --outtype f16")
        log(f"  F16 conversion complete ({time.time()-t0:.0f}s)")
        size_gb = os.path.getsize(f16_gguf) / 1e9
        log(f"  F16 GGUF size: {size_gb:.1f} GB")

    # 3b: Convert mmproj (vision encoder) to F16
    mmproj_gguf = f"{GGUF_DIR}/mmproj-Sonia-Qwen3-VL-32B-F16.gguf"
    if os.path.exists(mmproj_gguf):
        log(f"  mmproj GGUF already exists: {mmproj_gguf}")
    else:
        t0 = time.time()
        run(f"python3 {convert_script} {MODEL_DIR} --mmproj --outfile {mmproj_gguf} --outtype f16")
        log(f"  mmproj conversion complete ({time.time()-t0:.0f}s)")
        size_mb = os.path.getsize(mmproj_gguf) / 1e6
        log(f"  mmproj GGUF size: {size_mb:.0f} MB")

    # ──────────────────────────────────────────────
    # Step 4: Quantize
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("STEP 4: Quantizing")
    log("=" * 60)

    quants = [
        ("Q8_0", f"{GGUF_DIR}/Sonia-Qwen3-VL-32B-Q8_0.gguf"),
        ("Q4_K_M", f"{GGUF_DIR}/Sonia-Qwen3-VL-32B-Q4_K_M.gguf"),
    ]

    for qtype, qpath in quants:
        if os.path.exists(qpath):
            log(f"  {qtype} already exists: {qpath}")
            continue
        log(f"  Quantizing to {qtype}...")
        t0 = time.time()
        run(f"{quantize_bin} {f16_gguf} {qpath} {qtype}")
        elapsed = time.time() - t0
        size_gb = os.path.getsize(qpath) / 1e9
        log(f"  {qtype} complete ({elapsed:.0f}s, {size_gb:.1f} GB)")

    # ──────────────────────────────────────────────
    # Step 5: Upload to HuggingFace Hub
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("STEP 5: Uploading to HuggingFace Hub")
    log("=" * 60)

    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)

    # Create GGUF repo if it doesn't exist
    try:
        api.create_repo(repo_id=GGUF_REPO, repo_type="model", exist_ok=True)
        log(f"  Repo ready: {GGUF_REPO}")
    except Exception as e:
        log(f"  Repo creation: {e}")

    # Upload all GGUF files
    upload_files = [
        (mmproj_gguf, "mmproj-Sonia-Qwen3-VL-32B-F16.gguf"),
        (f"{GGUF_DIR}/Sonia-Qwen3-VL-32B-Q8_0.gguf", "Sonia-Qwen3-VL-32B-Q8_0.gguf"),
        (f"{GGUF_DIR}/Sonia-Qwen3-VL-32B-Q4_K_M.gguf", "Sonia-Qwen3-VL-32B-Q4_K_M.gguf"),
    ]

    for local_path, hub_name in upload_files:
        if not os.path.exists(local_path):
            log(f"  SKIP (missing): {hub_name}")
            continue
        size_gb = os.path.getsize(local_path) / 1e9
        log(f"  Uploading {hub_name} ({size_gb:.1f} GB)...")
        t0 = time.time()
        api.upload_file(
            path_or_fileobj=local_path,
            path_in_repo=hub_name,
            repo_id=GGUF_REPO,
            repo_type="model",
        )
        log(f"  Uploaded ({time.time()-t0:.0f}s)")

    # Also upload the mmproj Q8_0 version
    mmproj_q8 = f"{GGUF_DIR}/mmproj-Sonia-Qwen3-VL-32B-Q8_0.gguf"
    if os.path.exists(mmproj_q8):
        log(f"  Uploading mmproj Q8_0...")
        api.upload_file(
            path_or_fileobj=mmproj_q8,
            path_in_repo="mmproj-Sonia-Qwen3-VL-32B-Q8_0.gguf",
            repo_id=GGUF_REPO,
            repo_type="model",
        )

    # Upload README
    readme_content = """---
language:
- en
license: apache-2.0
tags:
- vision-language
- image-text-to-text
- qwen3-vl
- sonia
- gguf
pipeline_tag: image-text-to-text
base_model:
- VocaborSilentii/Sonia-Qwen3-VL-32B
---

# Sonia-Qwen3-VL-32B-GGUF

GGUF quantized versions of [VocaborSilentii/Sonia-Qwen3-VL-32B](https://huggingface.co/VocaborSilentii/Sonia-Qwen3-VL-32B) for use with [llama.cpp](https://github.com/ggml-org/llama.cpp), Ollama, and other GGUF-compatible runtimes.

## Available files

| File | Quant | Size | Description |
|------|-------|------|-------------|
| `Sonia-Qwen3-VL-32B-Q4_K_M.gguf` | Q4_K_M | ~20 GB | 4-bit quantization, best balance of quality and size |
| `Sonia-Qwen3-VL-32B-Q8_0.gguf` | Q8_0 | ~35 GB | 8-bit quantization, near-lossless quality |
| `mmproj-Sonia-Qwen3-VL-32B-F16.gguf` | F16 | ~1.5 GB | Vision encoder (required for image inputs) |

## Usage with llama.cpp

```bash
# Text-only
llama-cli -m Sonia-Qwen3-VL-32B-Q4_K_M.gguf -p "Hello Sonia!" --jinja

# With vision (image input)
llama-mtmd-cli \\
  -m Sonia-Qwen3-VL-32B-Q4_K_M.gguf \\
  --mmproj mmproj-Sonia-Qwen3-VL-32B-F16.gguf \\
  --image photo.jpg \\
  --jinja

# Server mode
llama-server \\
  -m Sonia-Qwen3-VL-32B-Q4_K_M.gguf \\
  --mmproj mmproj-Sonia-Qwen3-VL-32B-F16.gguf \\
  --jinja
```

## Base model

- Source: [VocaborSilentii/Sonia-Qwen3-VL-32B](https://huggingface.co/VocaborSilentii/Sonia-Qwen3-VL-32B)
- Architecture: Qwen3VLForConditionalGeneration (33.4B params)
- Fine-tune: LoRA (rank 32, alpha 64) merged into base weights
- Training: 984 steps on 2x A100 80GB, eval_loss 0.1128

## Quantization details

- Converted with [llama.cpp](https://github.com/ggml-org/llama.cpp) `convert_hf_to_gguf.py`
- Vision encoder (mmproj) kept at F16 for quality
- LLM weights quantized independently
"""

    readme_path = f"{GGUF_DIR}/README.md"
    with open(readme_path, "w") as f:
        f.write(readme_content)
    api.upload_file(
        path_or_fileobj=readme_path,
        path_in_repo="README.md",
        repo_id=GGUF_REPO,
        repo_type="model",
    )
    log("  README uploaded")

    # ──────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────
    log("=" * 60)
    log("QUANTIZATION PIPELINE COMPLETE")
    log(f"  Repo: https://huggingface.co/{GGUF_REPO}")
    for local_path, hub_name in upload_files:
        if os.path.exists(local_path):
            size_gb = os.path.getsize(local_path) / 1e9
            log(f"  {hub_name}: {size_gb:.1f} GB")
    log("=" * 60)

if __name__ == "__main__":
    main()
