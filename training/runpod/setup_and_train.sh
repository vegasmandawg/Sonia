#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# Sonia Fine-Tuning on RunPod - Full Setup & Training Script
# Pod: 2x H100 SXM (160 GB VRAM, 502 GB RAM, 470 GB disk)
# Model: VocaborSilentii/Qwen3-VL-32B-Instruct (33.3B params)
# Datasets: VocaborSilentii/SoniaTraining + VocaborSilentii/glm-4.7-2000x
# =============================================================

echo "============================================"
echo "  Sonia Fine-Tuning - RunPod Setup"
echo "============================================"
echo "Time: $(date -u)"
echo "GPUs: $(nvidia-smi -L 2>/dev/null | wc -l)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
echo ""

# --- Configuration ---
WORK_DIR="/workspace/sonia-training"
MODEL_ID="${MODEL_ID:-VocaborSilentii/Qwen3-VL-32B-Instruct}"
HF_DATASET_REPO="${HF_DATASET_REPO:-VocaborSilentii/SoniaTraining}"
HF_GLM_REPO="${HF_GLM_REPO:-VocaborSilentii/glm-4.7-2000x}"
OUTPUT_DIR="/workspace/output/sonia-lora"
MERGE_DIR="/workspace/output/sonia-qwen3vl-32b-merged"
HF_UPLOAD_REPO="${HF_UPLOAD_REPO:-VocaborSilentii/Sonia-Qwen3-VL-32B}"

# Training hyperparams (override via env vars)
# H100 SXM (80GB each, 3.35 TB/s bandwidth) allows batch_size=2 comfortably
EPOCHS="${EPOCHS:-2.0}"
LR="${LR:-1.5e-4}"
BATCH_SIZE="${BATCH_SIZE:-2}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
LORA_R="${LORA_R:-32}"
LORA_ALPHA="${LORA_ALPHA:-64}"
MAX_SEQ="${MAX_SEQ:-4096}"

# Redirect HF cache to volume (container disk too small for 65GB model)
export HF_HOME="${HF_HOME:-/workspace/.hf}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-/workspace/.hf/datasets}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True,max_split_size_mb:256}"

# NCCL optimizations for SXM (NVLink interconnect)
export NCCL_P2P_LEVEL="${NCCL_P2P_LEVEL:-NVL}"

mkdir -p "$WORK_DIR" "$OUTPUT_DIR" "$HF_HOME"
cd "$WORK_DIR"

# --- Step 1: Install dependencies ---
echo ""
echo "[1/6] Installing dependencies..."
pip install --quiet --upgrade pip

# Core training stack
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
    "tqdm" \
    "wandb"

# Flash Attention 2 (needs special build flags on RunPod)
echo "  Installing flash-attn (this takes a few minutes)..."
pip install flash-attn --no-build-isolation --quiet 2>/dev/null || {
    echo "  WARN: flash-attn install failed, will fall back to sdpa"
}

echo "  Dependencies installed."
python3 -c "import transformers; print(f'  transformers: {transformers.__version__}')"
python3 -c "import peft; print(f'  peft: {peft.__version__}')"
python3 -c "import bitsandbytes; print(f'  bitsandbytes: {bitsandbytes.__version__}')"
python3 -c "import flash_attn; print(f'  flash-attn: {flash_attn.__version__}')" 2>/dev/null || echo "  flash-attn: not available"

# --- Step 2: HF Login ---
echo ""
echo "[2/6] Authenticating with HuggingFace..."
if [ -n "${HF_TOKEN:-}" ]; then
    huggingface-cli login --token "$HF_TOKEN" 2>/dev/null || true
    echo "  Logged in."
else
    echo "  WARNING: HF_TOKEN not set. Model/dataset download may fail for private repos."
    echo "  Set it in RunPod Secrets or: export HF_TOKEN=hf_xxx"
fi

# --- Step 3: Download & combine datasets ---
echo ""
echo "[3/6] Downloading and combining datasets..."
if [ -f "data/sonia_combined_train.jsonl" ]; then
    echo "  Combined dataset already present, skipping download."
else
    echo "  Downloading $HF_DATASET_REPO + $HF_GLM_REPO and combining..."
    echo "  (This uses the HF datasets library to download both repos,"
    echo "   strips <think> tags from glm data, and merges into train/val/test JSONL)"

    python3 combine_datasets_v2.py --output-dir data/ || {
        echo "  ERROR: Dataset combination failed."
        echo "  Check that both repos are accessible: $HF_DATASET_REPO and $HF_GLM_REPO"
        exit 1
    }
fi

# Verify data exists
if [ ! -f "data/sonia_combined_train.jsonl" ]; then
    echo "  ERROR: data/sonia_combined_train.jsonl not found after download."
    echo "  Available files:"
    ls -la data/ 2>/dev/null || echo "  (no data directory)"
    exit 1
fi

TRAIN_COUNT=$(wc -l < data/sonia_combined_train.jsonl)
VAL_COUNT=$(wc -l < data/sonia_combined_val.jsonl)
echo "  Train: $TRAIN_COUNT records"
echo "  Val:   $VAL_COUNT records"

# --- Step 4: Verify model access ---
echo ""
echo "[4/6] Verifying model access for $MODEL_ID..."
python3 -c "
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained('$MODEL_ID', trust_remote_code=True, use_fast=False)
print(f'  Tokenizer loaded: vocab_size={len(tok)}')
" || {
    echo "  ERROR: Cannot access $MODEL_ID. Check HF_TOKEN and model permissions."
    exit 1
}

# --- Step 5: Configure accelerate for multi-GPU ---
echo ""
echo "[5/6] Configuring multi-GPU training..."
NUM_GPUS=$(python3 -c "import torch; print(torch.cuda.device_count())")
echo "  Detected $NUM_GPUS GPUs"

# Write accelerate config for multi-GPU
mkdir -p ~/.cache/huggingface/accelerate
cat > ~/.cache/huggingface/accelerate/default_config.yaml << ACCEL_EOF
compute_environment: LOCAL_MACHINE
distributed_type: MULTI_GPU
downcast_bf16: 'no'
gpu_ids: all
machine_rank: 0
main_training_function: main
mixed_precision: bf16
num_machines: 1
num_processes: $NUM_GPUS
rdzv_backend: static
same_network: true
tpu_env: []
tpu_use_cluster: false
tpu_use_sudo: false
use_cpu: false
ACCEL_EOF
echo "  Accelerate configured for $NUM_GPUS GPUs"

# --- Step 6: Train ---
echo ""
echo "[6/6] Starting training..."
echo "  Model:     $MODEL_ID"
echo "  Output:    $OUTPUT_DIR"
echo "  Merge:     $MERGE_DIR"
echo "  Epochs:    $EPOCHS"
echo "  LR:        $LR"
echo "  Batch:     $BATCH_SIZE x $GRAD_ACCUM accum x $NUM_GPUS GPUs = $((BATCH_SIZE * GRAD_ACCUM * NUM_GPUS)) effective"
echo "  LoRA:      r=$LORA_R, alpha=$LORA_ALPHA"
echo "  Max seq:   $MAX_SEQ"
echo ""

# Use accelerate launch for proper multi-GPU
accelerate launch \
    --num_processes "$NUM_GPUS" \
    --mixed_precision bf16 \
    train_sonia_qwen3vl.py \
    --model-id "$MODEL_ID" \
    --train-file data/sonia_combined_train.jsonl \
    --val-file data/sonia_combined_val.jsonl \
    --output-dir "$OUTPUT_DIR" \
    --merge-output "$MERGE_DIR" \
    --push-to-hub "$HF_UPLOAD_REPO" \
    --max-seq-length "$MAX_SEQ" \
    --num-train-epochs "$EPOCHS" \
    --learning-rate "$LR" \
    --per-device-train-batch-size "$BATCH_SIZE" \
    --per-device-eval-batch-size "$BATCH_SIZE" \
    --gradient-accumulation-steps "$GRAD_ACCUM" \
    --logging-steps 10 \
    --eval-steps 200 \
    --save-steps 200 \
    --save-total-limit 2 \
    --lora-r "$LORA_R" \
    --lora-alpha "$LORA_ALPHA" \
    --lora-dropout 0.05 \
    --bf16

TRAIN_EXIT=$?
if [ $TRAIN_EXIT -ne 0 ]; then
    echo "Training failed with exit code $TRAIN_EXIT"
    # Save logs even on failure
    cp -r "$OUTPUT_DIR"/*.json /workspace/ 2>/dev/null || true
    exit $TRAIN_EXIT
fi

# --- Summary ---
echo ""
echo "============================================"
echo "  Training Complete!"
echo "============================================"
echo ""
echo "Adapter:  $OUTPUT_DIR"
echo "Merged:   $MERGE_DIR"
echo ""
echo "Model pushed to: https://huggingface.co/$HF_UPLOAD_REPO"
echo ""
echo "To manually upload if push failed:"
echo "  huggingface-cli upload $HF_UPLOAD_REPO $MERGE_DIR --token \$HF_TOKEN"
echo ""

# Show disk usage
echo "Disk usage:"
df -h /workspace
du -sh "$OUTPUT_DIR" "$MERGE_DIR" 2>/dev/null || true

echo ""
echo "Done! $(date -u)"
