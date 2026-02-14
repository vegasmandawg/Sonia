# Sonia Qwen3-VL-32B Fine-Tuning Runbook

## Pod Specification

| Resource | Value |
|----------|-------|
| GPU | 2x H100 SXM (80 GB each, 160 GB VRAM total) |
| RAM | 502 GB |
| vCPU | 52 |
| Disk | 470 GB total (50 GB container + 420 GB volume) |
| Container | `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` |
| Volume mount | `/workspace` |

## Model

| Property | Value |
|----------|-------|
| Model ID | `VocaborSilentii/Qwen3-VL-32B-Instruct` |
| Parameters | 33.3B |
| Architecture | `qwen3_vl` (vision-language) |
| Auto class | `AutoModelForImageTextToText` |
| Disk footprint | ~65 GB (safetensors) |
| VRAM per GPU (bf16) | ~35 GB base + ~35-40 GB activations/LoRA |
| License | Apache 2.0 |

## Datasets

| Dataset | Records | Purpose |
|---------|---------|---------|
| [`VocaborSilentii/SoniaTraining`](https://huggingface.co/datasets/VocaborSilentii/SoniaTraining) | ~8,900 (train+val+test) | Sonia persona, capabilities, behavioral contract |
| [`VocaborSilentii/glm-4.7-2000x`](https://huggingface.co/datasets/VocaborSilentii/glm-4.7-2000x) | ~2,000 (train only) | GLM-4.7 reasoning distillation |

Both datasets use JSONL format with `{"messages": [{"role": "...", "content": "..."}]}`.

The `combine_datasets_v2.py` script:
- Downloads both datasets from HuggingFace
- Strips `<think>...</think>` blocks from glm assistant responses
- Injects Sonia system prompt into glm records (which have empty system prompts)
- Splits glm into 95% train / 5% val
- Deduplicates by content hash
- Outputs: `data/sonia_combined_{train,val,test}.jsonl`

## Training Configuration

| Hyperparameter | Value | Notes |
|----------------|-------|-------|
| Method | LoRA (PEFT) | Language layers only, vision tower frozen |
| Precision | bf16 | No quantization (bitsandbytes bug with Qwen3-VL) |
| LoRA rank (r) | 32 | |
| LoRA alpha | 64 | Scaling factor = alpha/r = 2.0 |
| LoRA dropout | 0.05 | |
| Target modules | q,k,v,o,gate,up,down_proj | All linear layers in LLM backbone |
| Epochs | 2.0 | |
| Learning rate | 1.5e-4 | Cosine schedule with 3% warmup |
| Per-device batch | 2 | H100 SXM can handle batch=2 at seq_len=4096 |
| Gradient accum | 8 | |
| Effective batch | 32 | 2 batch x 8 accum x 2 GPUs |
| Max seq length | 4096 | |
| Optimizer | AdamW (torch) | Weight decay 0.01 |
| Gradient checkpointing | Yes | Saves ~30% VRAM |
| Flash Attention 2 | Yes (with fallback to sdpa) | |

## Quick Start (One Command)

```bash
# SSH into the RunPod pod, then:
cd /workspace
mkdir -p sonia-training && cd sonia-training

# Download training scripts from HuggingFace
huggingface-cli login --token "$HF_TOKEN"
huggingface-cli download VocaborSilentii/SoniaTraining \
    --repo-type dataset --local-dir . \
    --include "*.py" "*.sh" "*.txt" "*.md"

# Make executable and run
chmod +x setup_and_train.sh
nohup bash setup_and_train.sh 2>&1 | tee /workspace/training.log &
```

The `setup_and_train.sh` script handles everything:
1. Installs all Python dependencies (transformers, peft, accelerate, flash-attn, etc.)
2. Authenticates with HuggingFace using `$HF_TOKEN`
3. Downloads both datasets, strips `<think>` tags, combines into train/val JSONL
4. Verifies model access (tokenizer download)
5. Configures `accelerate` for 2-GPU distributed training
6. Launches `train_sonia_qwen3vl.py` via `accelerate launch`
7. After training: merges LoRA adapter into base model, pushes to `VocaborSilentii/Sonia-Qwen3-VL-32B`

## Required Environment Variables

```bash
# REQUIRED - set in RunPod pod template or manually
export HF_TOKEN=<your-huggingface-token>

# AUTO-SET by setup_and_train.sh (override if needed)
export HF_HOME=/workspace/.hf
export HF_DATASETS_CACHE=/workspace/.hf/datasets
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:256
export NCCL_P2P_LEVEL=NVL  # NVLink optimization for SXM
```

## Step-by-Step Manual Setup

If you prefer to run each step individually instead of `setup_and_train.sh`:

### Step 1: Install Dependencies

```bash
cd /workspace
mkdir -p sonia-training && cd sonia-training

pip install --quiet --upgrade pip
pip install --quiet \
    "transformers>=4.57.0" \
    "datasets>=2.21.0" \
    "peft>=0.12.0" \
    "accelerate>=0.35.0" \
    "bitsandbytes>=0.45.0" \
    "safetensors>=0.4.5" \
    "sentencepiece>=0.2.0" \
    "scipy>=1.11.0" \
    "huggingface_hub>=0.25.0" \
    "tqdm" "wandb"

# Flash Attention 2 (recommended, takes 3-5 min to compile)
pip install flash-attn --no-build-isolation --quiet 2>/dev/null || echo "WARN: flash-attn not available"
```

### Step 2: HuggingFace Auth

```bash
export HF_TOKEN=<your-token>
export HF_HOME=/workspace/.hf
huggingface-cli login --token "$HF_TOKEN"
```

### Step 3: Download Scripts

```bash
huggingface-cli download VocaborSilentii/SoniaTraining \
    --repo-type dataset --local-dir . \
    --include "*.py" "*.sh" "*.txt" "*.md"
```

### Step 4: Download & Combine Datasets

```bash
python combine_datasets_v2.py --output-dir data/
```

Expected output:
```
Train: ~10,600 records (8,900 sonia + 1,900 glm)
Val:   ~200 records
Test:  ~200 records
```

### Step 5: Smoke Test (Optional but Recommended)

```bash
CUDA_VISIBLE_DEVICES=0 python scripts/smoke_load_qwen3vl.py \
    --model-id VocaborSilentii/Qwen3-VL-32B-Instruct \
    --attn flash_attention_2
```

Expected: `SMOKE PASSED` in ~3 minutes (model download on first run takes longer).

### Step 6: Single-GPU Debug Run

Test on one GPU first to catch errors with clean tracebacks:

```bash
export HF_HOME=/workspace/.hf
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:256

CUDA_VISIBLE_DEVICES=0 \
accelerate launch --num_processes 1 --mixed_precision bf16 \
    train_sonia_qwen3vl.py \
    --model-id VocaborSilentii/Qwen3-VL-32B-Instruct \
    --train-file data/sonia_combined_train.jsonl \
    --val-file data/sonia_combined_val.jsonl \
    --output-dir /workspace/output/sonia-lora-debug \
    --per-device-train-batch-size 2 \
    --gradient-accumulation-steps 8 \
    --num-train-epochs 0.01 \
    --lora-r 32 --lora-alpha 64 --lora-dropout 0.05 \
    --max-seq-length 4096 \
    --logging-steps 1 --eval-steps 50 --save-steps 50 \
    --bf16 2>&1 | tee /workspace/output/debug.log
```

What to verify:
- Model loads without errors
- Tokenizer loads and applies chat template
- Dataset tokenization completes
- First optimizer step runs without OOM
- Loss is decreasing

### Step 7: Full Multi-GPU Training

```bash
export HF_HOME=/workspace/.hf
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:256
export NCCL_P2P_LEVEL=NVL

accelerate launch --num_processes 2 --mixed_precision bf16 \
    train_sonia_qwen3vl.py \
    --model-id VocaborSilentii/Qwen3-VL-32B-Instruct \
    --train-file data/sonia_combined_train.jsonl \
    --val-file data/sonia_combined_val.jsonl \
    --output-dir /workspace/output/sonia-lora \
    --merge-output /workspace/output/sonia-merged \
    --push-to-hub VocaborSilentii/Sonia-Qwen3-VL-32B \
    --per-device-train-batch-size 2 \
    --per-device-eval-batch-size 2 \
    --gradient-accumulation-steps 8 \
    --num-train-epochs 2.0 \
    --learning-rate 1.5e-4 \
    --lora-r 32 --lora-alpha 64 --lora-dropout 0.05 \
    --max-seq-length 4096 \
    --logging-steps 10 --eval-steps 200 --save-steps 200 \
    --save-total-limit 2 \
    --bf16 2>&1 | tee /workspace/output/train.log
```

### Step 8: Post-Training

After training completes, the script automatically:
1. Saves the LoRA adapter to `/workspace/output/sonia-lora/`
2. Merges the adapter into the full base model at `/workspace/output/sonia-merged/`
3. Pushes the merged model to `VocaborSilentii/Sonia-Qwen3-VL-32B`

If the push fails, upload manually:
```bash
huggingface-cli upload VocaborSilentii/Sonia-Qwen3-VL-32B \
    /workspace/output/sonia-merged --token "$HF_TOKEN"
```

## Expected Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Dependency install | ~5 min | flash-attn compile is the bottleneck |
| Dataset download + combine | ~3 min | Both datasets are small (<50 MB) |
| Model download (first run) | ~10 min | 65 GB over RunPod's network |
| Single-GPU debug | ~5 min | Just to verify model loads + first step |
| Full training (2 epochs) | ~2-4 hours | ~10,600 train records, batch=32, ~660 steps |
| Adapter merge | ~15 min | Reload base model + merge LoRA weights |
| Push to HuggingFace | ~20 min | 65 GB upload |
| **Total** | **~3-5 hours** | |

## Estimated Cost

| Resource | Rate | Duration | Cost |
|----------|------|----------|------|
| 2x H100 SXM compute | $5.38/hr | ~4 hours | ~$21.52 |
| Container storage | ~$0.01/hr | ~4 hours | ~$0.04 |
| Volume storage | ~$0.06/hr | ~4 hours | ~$0.24 |
| **Total** | | | **~$22** |

## VRAM Budget (per GPU)

| Component | VRAM |
|-----------|------|
| Qwen3-VL-32B bf16 parameters | ~34 GB |
| LoRA adapter (r=32) | ~0.5 GB |
| Optimizer states (AdamW) | ~2 GB |
| Gradient checkpointing activations | ~15-25 GB |
| Batch activations (batch=2, seq=4096) | ~10-15 GB |
| **Total** | **~62-77 GB / 80 GB** |

## Disk Budget

| Item | Size | Location |
|------|------|----------|
| Model cache (safetensors) | ~65 GB | `/workspace/.hf/` |
| Training datasets | ~50 MB | `/workspace/sonia-training/data/` |
| Training checkpoints (2 kept) | ~2 GB | `/workspace/output/sonia-lora/` |
| Merged model output | ~65 GB | `/workspace/output/sonia-merged/` |
| Logs + misc | ~1 GB | `/workspace/output/` |
| Python packages | ~10 GB | Container disk |
| **Total** | **~143 GB / 470 GB** | |

## Troubleshooting

### OOM (Out of Memory)
- Reduce `--per-device-train-batch-size` to 1
- Increase `--gradient-accumulation-steps` to 16 to keep effective batch at 32
- Reduce `--max-seq-length` to 3072 or 2048
- Verify gradient checkpointing is enabled (it is by default)

### Flash Attention 2 Build Failure
- The script auto-falls back to `sdpa` then `eager` attention
- To install manually: `pip install flash-attn --no-build-isolation`
- Requires CUDA dev toolkit (included in RunPod pytorch image)

### NCCL Issues (Multi-GPU)
```bash
export NCCL_DEBUG=INFO
export TORCH_DISTRIBUTED_DEBUG=DETAIL
nvidia-smi -L  # Verify both GPUs visible
nvidia-smi topo -m  # Verify NVLink topology
```

### set_submodule AttributeError
- This is a known bitsandbytes bug with Qwen3-VL architecture
- Solution: quantization is FORCE-DISABLED in the training script
- If it appears, check no quantization config leaks through env vars

### Training Loss Not Decreasing
- Check dataset tokenization: look for high "invalid" count in combine_stats.json
- Verify assistant-only loss masking: check training_summary.json for train/val record counts
- Try lower learning rate (1e-4 or 5e-5) if loss spikes

### Disk Space Issues
- Model cache (~65 GB) goes to `/workspace/.hf/` (volume, not container)
- If volume runs low, clear old checkpoints: `rm -rf /workspace/output/sonia-lora/checkpoint-*`
- Container disk (50 GB) is only for Python packages

### Resuming from Checkpoint
```bash
accelerate launch --num_processes 2 --mixed_precision bf16 \
    train_sonia_qwen3vl.py \
    ... (same args as before) \
    --resume-from-checkpoint /workspace/output/sonia-lora/checkpoint-400
```

### Error Logs
- Per-rank tracebacks: `/workspace/output/rank_{0,1}_traceback.log`
- Full training log: `/workspace/output/train.log` (if using tee)
- `training_summary.json` in output dir after successful training

## File Inventory

| File | Purpose |
|------|---------|
| `setup_and_train.sh` | One-command setup + training launcher |
| `train_sonia_qwen3vl.py` | Core training script (LoRA SFT with assistant-only loss masking) |
| `combine_datasets_v2.py` | Dataset download, `<think>` stripping, merge, dedup |
| `scripts/smoke_load_qwen3vl.py` | Quick model load + generate smoke test |
| `merge_push_direct.py` | Standalone adapter merge + HF push |
| `test_merged_model.py` | Test merged model inference |
| `quantize_gguf_v2.py` | Optional GGUF quantization for local inference |
| `upload_to_hf.py` | Upload scripts to HuggingFace dataset repo |
| `RUNBOOK.md` | This file |
