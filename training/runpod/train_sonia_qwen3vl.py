#!/usr/bin/env python3
"""
RunPod-optimized LoRA SFT for Sonia on Qwen3-VL-32B-Instruct.
2x H100 SXM (160 GB VRAM, NVLink) — uses accelerate for multi-GPU.
Assistant-only loss masking across ALL assistant turns (multi-turn safe).
bf16 only — quantization disabled for Qwen3-VL (bitsandbytes set_submodule bug).

Usage:
    # Single-GPU debug:
    CUDA_VISIBLE_DEVICES=0 accelerate launch --num_processes 1 --mixed_precision bf16 \
        train_sonia_qwen3vl.py \
        --model-id VocaborSilentii/Qwen3-VL-32B-Instruct \
        --train-file data/sonia_combined_train.jsonl \
        --val-file data/sonia_combined_val.jsonl \
        --output-dir /workspace/output/sonia-lora

    # Multi-GPU:
    CUDA_VISIBLE_DEVICES=0,1 accelerate launch --num_processes 2 --mixed_precision bf16 \
        train_sonia_qwen3vl.py \
        --model-id VocaborSilentii/Qwen3-VL-32B-Instruct \
        --train-file data/sonia_combined_train.jsonl \
        --val-file data/sonia_combined_val.jsonl \
        --output-dir /workspace/output/sonia-lora \
        --merge-output /workspace/output/sonia-merged \
        --push-to-hub VocaborSilentii/Sonia-Qwen3-VL-32B
"""
import argparse
import json
import os
import sys
import time
import traceback

import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoProcessor,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
    set_seed,
)
from peft import LoraConfig, get_peft_model, PeftModel

# ---------------------------------------------------------------------------
# Per-rank exception logging
# ---------------------------------------------------------------------------
_OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/output")

def _write_rank_traceback(exc: Exception):
    """Write traceback to /workspace/output/rank_<RANK>_traceback.log."""
    rank = int(os.environ.get("LOCAL_RANK", os.environ.get("RANK", "0")))
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    path = os.path.join(_OUTPUT_DIR, f"rank_{rank}_traceback.log")
    with open(path, "w") as f:
        f.write(f"RANK {rank} EXCEPTION at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
        f.write("=" * 70 + "\n")
        traceback.print_exc(file=f)
        f.write("\n" + "=" * 70 + "\n")
        f.write(repr(exc) + "\n")
    print(f"[rank {rank}] Traceback written to {path}", file=sys.stderr)


def parse_args():
    ap = argparse.ArgumentParser(description="Sonia LoRA fine-tuning on Qwen3-VL-32B")
    ap.add_argument("--model-id", default="VocaborSilentii/Qwen3-VL-32B-Instruct",
                     help="HuggingFace model ID or local path")
    ap.add_argument("--train-file", required=True)
    ap.add_argument("--val-file", required=True)
    ap.add_argument("--output-dir", default="/workspace/output/sonia-lora")
    ap.add_argument("--merge-output", default=None,
                     help="If set, merge adapter into full model at this path after training")
    ap.add_argument("--push-to-hub", default=None,
                     help="If set, push merged model to this HF repo")

    # Training hyperparams
    ap.add_argument("--max-seq-length", type=int, default=4096)
    ap.add_argument("--num-train-epochs", type=float, default=2.0)
    ap.add_argument("--learning-rate", type=float, default=1.5e-4)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--warmup-ratio", type=float, default=0.03)
    ap.add_argument("--per-device-train-batch-size", type=int, default=2)
    ap.add_argument("--per-device-eval-batch-size", type=int, default=2)
    ap.add_argument("--gradient-accumulation-steps", type=int, default=8)

    # Logging / checkpointing
    ap.add_argument("--logging-steps", type=int, default=10)
    ap.add_argument("--eval-steps", type=int, default=200)
    ap.add_argument("--save-steps", type=int, default=200)
    ap.add_argument("--save-total-limit", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)

    # Precision
    ap.add_argument("--bf16", action="store_true", default=True)
    ap.add_argument("--no-bf16", action="store_true", default=False)

    # Quantization flags (accepted but FORCED OFF for Qwen3-VL)
    ap.add_argument("--load-in-4bit", action="store_true", default=False)
    ap.add_argument("--load-in-8bit", action="store_true", default=False)
    ap.add_argument("--no-4bit", action="store_true", default=False)

    # LoRA
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=int, default=64)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", type=str,
                     default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj")

    ap.add_argument("--resume-from-checkpoint", type=str, default=None)
    ap.add_argument("--num-proc", type=int, default=4, help="dataset.map workers")

    args = ap.parse_args()
    if args.no_bf16:
        args.bf16 = False

    # FORCE disable quantization for Qwen3-VL (bitsandbytes set_submodule bug)
    if args.load_in_4bit or args.load_in_8bit:
        print("WARNING: --load-in-4bit / --load-in-8bit requested but DISABLED for Qwen3-VL.")
        print("         bitsandbytes quantization causes 'set_submodule' AttributeError.")
        print("         Using bf16 full precision instead (160GB VRAM is sufficient).")
    args.load_in_4bit = False
    args.load_in_8bit = False
    return args


def load_chat_tokenizer(model_id: str):
    """Load tokenizer with fallback to processor for VL models."""
    tok = None
    template_owner = None
    try:
        tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, use_fast=False)
        template_owner = tok
    except Exception:
        pass

    if tok is None:
        proc = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        if hasattr(proc, "tokenizer") and proc.tokenizer is not None:
            tok = proc.tokenizer
            template_owner = proc if hasattr(proc, "apply_chat_template") else tok
        else:
            raise RuntimeError(f"Cannot load tokenizer from {model_id}")

    if getattr(tok, "pad_token", None) is None:
        if getattr(tok, "eos_token", None) is not None:
            tok.pad_token = tok.eos_token
    return tok, template_owner


def load_model(model_id: str, torch_dtype=None, is_distributed: bool = False):
    """Load Qwen3-VL model. No quantization. No device_map in distributed mode.

    Loader order:
      1. AutoModelForImageTextToText (canonical HF auto class)
      2. Qwen3VLForConditionalGeneration (direct class if available)
    If both fail, raise RuntimeError with full traceback immediately.
    No AutoModelForCausalLM fallback (wrong architecture for Qwen3-VL).
    No retries (avoids memory fragmentation).
    """
    common = dict(
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
        use_safetensors=True,
    )

    # In distributed mode (accelerate multi-process), do NOT use device_map.
    # Let accelerate.prepare() handle device placement.
    if not is_distributed:
        common["device_map"] = "auto"

    # Try flash_attention_2 first, fall back to sdpa, then eager
    attn_impls = ["flash_attention_2", "sdpa", "eager"]

    # Loader classes: only VL-compatible loaders, NO AutoModelForCausalLM
    loader_classes = []
    try:
        from transformers import AutoModelForImageTextToText
        loader_classes.append(("AutoModelForImageTextToText", AutoModelForImageTextToText))
    except ImportError:
        pass
    try:
        from transformers import Qwen3VLForConditionalGeneration
        loader_classes.append(("Qwen3VLForConditionalGeneration", Qwen3VLForConditionalGeneration))
    except ImportError:
        pass

    if not loader_classes:
        raise RuntimeError(
            "Neither AutoModelForImageTextToText nor Qwen3VLForConditionalGeneration "
            "available in this transformers version. Need transformers >= 5.0."
        )

    last_err = None
    for attn in attn_impls:
        load_kwargs = {**common, "attn_implementation": attn}
        for name, cls in loader_classes:
            try:
                print(f"  Trying {name} with attn={attn}...")
                model = cls.from_pretrained(model_id, **load_kwargs)
                print(f"  SUCCESS: Loaded with {name} (attn={attn})")
                return model
            except Exception as e:
                last_err = e
                err_str = str(e)
                # If set_submodule error, skip immediately (won't be fixed by attn change)
                if "set_submodule" in err_str:
                    print(f"  FATAL: {name}+{attn} hit set_submodule bug: {e}")
                    raise RuntimeError(
                        f"Qwen3-VL model loading failed due to set_submodule bug. "
                        f"This usually means bitsandbytes quantization is still active. "
                        f"Ensure quantization is disabled. Original error: {e}"
                    ) from e
                print(f"  {name}+{attn} failed: {e}")
                continue

    raise RuntimeError(
        f"Failed to load Qwen3-VL model after trying all loader+attn combinations.\n"
        f"Last error: {last_err}\n"
        f"Full traceback:\n{traceback.format_exc()}"
    )


def discover_lora_targets(model, requested_targets: list[str]) -> list[str]:
    """Discover valid LoRA target modules, excluding vision tower/projector."""
    VISION_EXCLUDE_PATTERNS = ["visual", "vision", "vit", "image", "pixel", "patch_embed"]
    valid_targets = set()
    for name, _ in model.named_modules():
        # Skip vision-related modules
        name_lower = name.lower()
        if any(pat in name_lower for pat in VISION_EXCLUDE_PATTERNS):
            continue
        # Check if any requested target is a suffix of the module name
        for target in requested_targets:
            if name.endswith(f".{target}") or name == target:
                valid_targets.add(target)
    found = [t for t in requested_targets if t in valid_targets]
    if not found:
        raise RuntimeError(
            f"No valid LoRA target modules found. Requested: {requested_targets}. "
            f"Check model architecture."
        )
    return found


def build_features(example, tokenizer, template_owner, max_seq_length):
    """Tokenize with assistant-only loss masking for ALL assistant turns."""
    msgs = example.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return {"input_ids": [], "attention_mask": [], "labels": [], "valid": False}

    roles = [m.get("role") for m in msgs]
    if "assistant" not in roles:
        return {"input_ids": [], "attention_mask": [], "labels": [], "valid": False}

    # Tokenize the full conversation
    full_text = template_owner.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=False
    )
    full_ids = tokenizer(
        full_text, truncation=True, max_length=max_seq_length, add_special_tokens=False
    )["input_ids"]

    if not full_ids:
        return {"input_ids": [], "attention_mask": [], "labels": [], "valid": False}

    # Build labels: mask everything, then unmask each assistant segment
    labels = [-100] * len(full_ids)

    for i, msg in enumerate(msgs):
        if msg["role"] != "assistant":
            continue

        # Prefix = everything up to (but not including) this assistant message
        prefix_msgs = msgs[:i]
        prefix_text = template_owner.apply_chat_template(
            prefix_msgs, tokenize=False, add_generation_prompt=True
        )
        prefix_ids = tokenizer(
            prefix_text, truncation=True, max_length=max_seq_length, add_special_tokens=False
        )["input_ids"]

        # Including this assistant message
        incl_msgs = msgs[:i + 1]
        incl_text = template_owner.apply_chat_template(
            incl_msgs, tokenize=False, add_generation_prompt=False
        )
        incl_ids = tokenizer(
            incl_text, truncation=True, max_length=max_seq_length, add_special_tokens=False
        )["input_ids"]

        # Unmask from prefix end to incl end
        start = min(len(prefix_ids), len(full_ids))
        end = min(len(incl_ids), len(full_ids))
        for j in range(start, end):
            labels[j] = full_ids[j]

    if all(x == -100 for x in labels):
        return {"input_ids": [], "attention_mask": [], "labels": [], "valid": False}

    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
        "valid": True,
    }


def merge_adapter(model_id: str, adapter_dir: str, output_dir: str, dtype=None):
    """Merge LoRA adapter into base model for deployment."""
    print(f"\n{'='*60}")
    print(f"Merging adapter into base model...")
    print(f"  Base: {model_id}")
    print(f"  Adapter: {adapter_dir}")
    print(f"  Output: {output_dir}")

    common = dict(
        trust_remote_code=True,
        torch_dtype=dtype,
        device_map="auto",
        low_cpu_mem_usage=True,
        use_safetensors=True,
    )

    # Use same VL-only loaders
    loaders = []
    try:
        from transformers import AutoModelForImageTextToText
        loaders.append(AutoModelForImageTextToText)
    except ImportError:
        pass
    try:
        from transformers import Qwen3VLForConditionalGeneration
        loaders.append(Qwen3VLForConditionalGeneration)
    except ImportError:
        pass
    if not loaders:
        raise RuntimeError("No VL model loaders available for merge")

    model = None
    for cls in loaders:
        try:
            model = cls.from_pretrained(model_id, **common)
            break
        except Exception:
            continue
    if model is None:
        raise RuntimeError("Cannot load base model for merge")

    model = PeftModel.from_pretrained(model, adapter_dir)
    merged = model.merge_and_unload()

    os.makedirs(output_dir, exist_ok=True)
    merged.save_pretrained(output_dir, safe_serialization=True)

    tok, _ = load_chat_tokenizer(model_id)
    tok.save_pretrained(output_dir)
    print(f"Merged model saved to {output_dir}")
    return output_dir


def main():
    try:
        _main_inner()
    except Exception as e:
        _write_rank_traceback(e)
        raise


def _main_inner():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    set_seed(args.seed)
    t0 = time.time()

    rank = int(os.environ.get("LOCAL_RANK", os.environ.get("RANK", "0")))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    is_distributed = world_size > 1

    print("=" * 60)
    print("Sonia LoRA Fine-Tuning on Qwen3-VL-32B")
    print("=" * 60)
    print(f"Rank: {rank}/{world_size}  Distributed: {is_distributed}")
    print(f"Model: {args.model_id}")
    print(f"Train: {args.train_file}")
    print(f"Val: {args.val_file}")
    print(f"Output: {args.output_dir}")
    print(f"Quantization: DISABLED (bf16 only)")
    print(f"LoRA r={args.lora_r}, alpha={args.lora_alpha}")
    print(f"Batch: {args.per_device_train_batch_size} x {args.gradient_accumulation_steps} accum")
    print(f"Epochs: {args.num_train_epochs}, LR: {args.learning_rate}")
    print(f"GPUs: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_memory / 1e9
        print(f"  GPU {i}: {name} ({mem:.1f} GB)")
    print()

    # --- Tokenizer ---
    print("Loading tokenizer...")
    tokenizer, template_owner = load_chat_tokenizer(args.model_id)
    print(f"  Vocab size: {len(tokenizer)}")

    # --- Dataset ---
    print("Loading dataset...")
    ds = load_dataset("json", data_files={
        "train": args.train_file,
        "validation": args.val_file,
    })
    print(f"  Raw: train={len(ds['train'])}, val={len(ds['validation'])}")

    def _map_fn(ex):
        return build_features(ex, tokenizer, template_owner, args.max_seq_length)

    ds = ds.map(_map_fn, num_proc=args.num_proc, desc="Tokenizing")
    ds = ds.filter(lambda x: x["valid"], desc="Filtering invalid")
    ds = ds.remove_columns([c for c in ds["train"].column_names
                            if c not in ("input_ids", "attention_mask", "labels")])
    print(f"  Valid: train={len(ds['train'])}, val={len(ds['validation'])}")

    # --- Model (bf16 only, no quantization) ---
    torch_dtype = torch.bfloat16 if args.bf16 else torch.float32

    print("Loading model (bf16, no quantization)...")
    model = load_model(args.model_id, torch_dtype=torch_dtype, is_distributed=is_distributed)

    # Disable cache for training (required for gradient checkpointing)
    model.config.use_cache = False

    # Enable gradient checkpointing
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    # --- LoRA ---
    requested_targets = [m.strip() for m in args.target_modules.split(",") if m.strip()]
    target_modules = discover_lora_targets(model, requested_targets)
    print(f"  LoRA target_modules (after discovery): {target_modules}")

    peft_cfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=target_modules,
        task_type="CAUSAL_LM",
        bias="none",
    )
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()

    # --- Training ---
    effective_batch = (args.per_device_train_batch_size *
                       args.gradient_accumulation_steps *
                       max(1, world_size))
    steps_per_epoch = len(ds["train"]) / effective_batch
    total_steps = int(steps_per_epoch * args.num_train_epochs)
    print(f"\nEffective batch size: {effective_batch}")
    print(f"Steps/epoch: {steps_per_epoch:.0f}, Total steps: {total_steps}")

    # Detect wandb
    report_to = []
    try:
        import wandb
        if os.environ.get("WANDB_API_KEY"):
            report_to = ["wandb"]
            os.environ.setdefault("WANDB_PROJECT", "sonia-finetune")
            os.environ.setdefault("WANDB_RUN_NAME", f"sonia-qwen3vl-32b-r{args.lora_r}")
            print("  Logging to Weights & Biases")
    except ImportError:
        pass

    train_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        logging_steps=args.logging_steps,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=args.bf16,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        lr_scheduler_type="cosine",
        optim="adamw_torch",
        report_to=report_to,
        seed=args.seed,
        dataloader_num_workers=2,
        dataloader_pin_memory=True,
        ddp_find_unused_parameters=False,
        remove_unused_columns=False,
    )

    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=model,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )

    # transformers 5.x renamed tokenizer -> processing_class in Trainer
    trainer_kwargs = dict(
        model=model,
        args=train_args,
        train_dataset=ds["train"],
        eval_dataset=ds["validation"],
        data_collator=collator,
    )
    import inspect
    trainer_params = inspect.signature(Trainer.__init__).parameters
    if "processing_class" in trainer_params:
        trainer_kwargs["processing_class"] = tokenizer
    else:
        trainer_kwargs["tokenizer"] = tokenizer
    trainer = Trainer(**trainer_kwargs)

    print(f"\nStarting training...")
    train_result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    eval_result = trainer.evaluate()

    # Save adapter
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    elapsed = time.time() - t0
    summary = {
        "model_id": args.model_id,
        "train_records": len(ds["train"]),
        "val_records": len(ds["validation"]),
        "max_seq_length": args.max_seq_length,
        "effective_batch_size": effective_batch,
        "total_steps": total_steps,
        "train_metrics": train_result.metrics,
        "eval_metrics": eval_result,
        "elapsed_seconds": round(elapsed, 1),
        "gpu_count": torch.cuda.device_count(),
        "lora_config": {"r": args.lora_r, "alpha": args.lora_alpha, "dropout": args.lora_dropout},
        "args": {k: v for k, v in vars(args).items() if k not in ("resume_from_checkpoint",)},
    }
    with open(os.path.join(args.output_dir, "training_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Training complete in {elapsed/60:.1f} minutes")
    print(f"Train loss: {train_result.metrics.get('train_loss', 'N/A')}")
    print(f"Eval loss: {eval_result.get('eval_loss', 'N/A')}")
    print(f"Adapter saved to: {args.output_dir}")

    # --- Optional merge ---
    if args.merge_output:
        merge_adapter(args.model_id, args.output_dir, args.merge_output, dtype=torch_dtype)
        print(f"Merged model at: {args.merge_output}")

        # --- Optional push to HF ---
        if args.push_to_hub:
            print(f"\nPushing merged model to {args.push_to_hub}...")
            from huggingface_hub import HfApi
            api = HfApi()
            api.upload_folder(
                folder_path=args.merge_output,
                repo_id=args.push_to_hub,
                repo_type="model",
                commit_message=f"Sonia fine-tune: {len(ds['train'])} samples, {args.num_train_epochs} epochs, LoRA r={args.lora_r}",
            )
            print(f"  Pushed to https://huggingface.co/{args.push_to_hub}")

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
