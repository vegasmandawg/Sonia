#!/usr/bin/env python3
"""
Combine VocaborSilentii/SoniaTraining + VocaborSilentii/glm-4.7-2000x into
unified train/val JSONL for RunPod fine-tuning.

SoniaTraining: persona + capabilities data (~8,900 records, 3 splits)
glm-4.7-2000x: GLM-4.7 reasoning distillation (~2,000 records, train only)

The glm dataset includes <think>...</think> reasoning blocks in assistant
responses. These are stripped since Sonia doesn't produce chain-of-thought
output. Empty-system-prompt records get the Sonia system prompt injected.

Usage:
    # On RunPod (after datasets downloaded to /workspace/sonia-training/):
    python combine_datasets_v2.py

    # Local (requires datasets library):
    python combine_datasets_v2.py --local
"""
import json
import hashlib
import re
import os
import sys
import argparse
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Sonia system prompt (injected into records that have empty system prompts)
# ---------------------------------------------------------------------------
SONIA_SYSTEM_PROMPT = (
    "You are Sonia, a hyper-competent, highly skeptical, and fiercely loyal technical assistant.\n"
    "Worldview: Critical Realism. Treat technical systems like biological organisms with pathology, diagnosis, and treatment.\n"
    "Tone: dry, acerbic, professional, slightly condescending. No cheerleading.\n"
    "Style: combine forensic/medical metaphors with precise engineering language.\n"
    "Behavioral contract:\n"
    "- Diagnose before prescribing.\n"
    "- Ask for evidence when claims are uncertain: logs, metrics, diffs, traces.\n"
    "- Reject illegal or unauthorized hacking requests and offer lawful alternatives.\n"
    "- Correct illogical plans directly with technical authority.\n"
    "- Prioritize containment, reversibility, and verification.\n"
    "- Protect the operator from cascading failure.\n"
    'Preferred closing style (frequent, not mandatory): "Are we done, or is there more damage to assess?"\n'
)

# ---------------------------------------------------------------------------
# <think> tag stripping
# ---------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks and clean up whitespace."""
    cleaned = _THINK_RE.sub("", text)
    # Collapse multiple newlines left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Validation & normalization
# ---------------------------------------------------------------------------
def validate_messages(rec: dict) -> bool:
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return False
    roles = [m.get("role") for m in msgs]
    if "assistant" not in roles:
        return False
    for m in msgs:
        if not m.get("content", "").strip():
            return False
    return True


def content_hash(rec: dict) -> str:
    if "content_hash" in rec:
        return rec["content_hash"]
    msgs = rec.get("messages", [])
    text = "||".join(f"{m['role']}:{m['content']}" for m in msgs)
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_record(rec: dict, inject_system: bool = False) -> dict:
    """Normalize to {messages: [...]} with optional Sonia system prompt injection."""
    msgs = list(rec["messages"])

    # Inject Sonia system prompt if first message is system with empty content
    if inject_system and msgs and msgs[0].get("role") == "system":
        if not msgs[0].get("content", "").strip():
            msgs[0] = {"role": "system", "content": SONIA_SYSTEM_PROMPT}

    # Ensure system prompt exists
    if inject_system and (not msgs or msgs[0].get("role") != "system"):
        msgs.insert(0, {"role": "system", "content": SONIA_SYSTEM_PROMPT})

    return {"messages": msgs}


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def load_hf_dataset(repo_id: str, split: str = "train"):
    """Load a HuggingFace dataset split."""
    from datasets import load_dataset
    ds = load_dataset(repo_id, split=split)
    return [row for row in ds]


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  WARN: {path.name} line {i+1}: {e}")
    return records


def process_glm_record(rec: dict) -> dict:
    """Process a glm-4.7-2000x record: strip <think> tags from assistant messages."""
    msgs = []
    for m in rec.get("messages", []):
        msg = dict(m)
        if msg.get("role") == "assistant":
            msg["content"] = strip_think_tags(msg.get("content", ""))
        msgs.append(msg)
    return {"messages": msgs}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Combine SoniaTraining + glm-4.7-2000x")
    ap.add_argument("--local", action="store_true",
                    help="Load from local JSONL files instead of HuggingFace")
    ap.add_argument("--output-dir", default="data",
                    help="Output directory (default: data/)")
    ap.add_argument("--val-ratio", type=float, default=0.05,
                    help="Fraction of glm data to use as validation (default: 0.05)")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = Counter()

    # --- Load SoniaTraining ---
    print("=" * 60)
    print("Loading VocaborSilentii/SoniaTraining...")
    print("=" * 60)

    if args.local and (out_dir / "sonia_combined_train.jsonl").exists():
        # If local files already exist from previous combine, load raw HF data
        print("  Loading from HuggingFace API...")

    sonia_train = load_hf_dataset("VocaborSilentii/SoniaTraining", "train")
    sonia_val = load_hf_dataset("VocaborSilentii/SoniaTraining", "validation")
    sonia_test = load_hf_dataset("VocaborSilentii/SoniaTraining", "test")
    print(f"  SoniaTraining: train={len(sonia_train)}, val={len(sonia_val)}, test={len(sonia_test)}")

    # --- Load glm-4.7-2000x ---
    print()
    print("=" * 60)
    print("Loading VocaborSilentii/glm-4.7-2000x...")
    print("=" * 60)

    glm_all = load_hf_dataset("VocaborSilentii/glm-4.7-2000x", "train")
    print(f"  glm-4.7-2000x: {len(glm_all)} records (train split only)")

    # Process glm records: strip <think> tags
    print("  Stripping <think> tags from assistant responses...")
    glm_processed = []
    think_stripped = 0
    for rec in glm_all:
        processed = process_glm_record(rec)
        # Check if any content was actually stripped
        for orig_m, proc_m in zip(rec.get("messages", []), processed.get("messages", [])):
            if orig_m.get("role") == "assistant" and orig_m.get("content") != proc_m.get("content"):
                think_stripped += 1
        glm_processed.append(processed)
    print(f"  Stripped <think> tags from {think_stripped} assistant messages")
    stats["glm_think_stripped"] = think_stripped

    # Inject Sonia system prompt into glm records (they have empty system prompts)
    print("  Injecting Sonia system prompt into glm records...")
    glm_normalized = [normalize_record(rec, inject_system=True) for rec in glm_processed]

    # Split glm into train/val
    import random
    random.seed(42)
    random.shuffle(glm_normalized)
    val_count = max(1, int(len(glm_normalized) * args.val_ratio))
    glm_val = glm_normalized[:val_count]
    glm_train = glm_normalized[val_count:]
    print(f"  glm split: train={len(glm_train)}, val={len(glm_val)}")

    # --- Combine ---
    print()
    print("=" * 60)
    print("Combining datasets...")
    print("=" * 60)

    all_train = sonia_train + glm_train
    all_val = sonia_val + glm_val
    all_test = list(sonia_test)  # glm has no test split
    print(f"  Before dedup: train={len(all_train)}, val={len(all_val)}, test={len(all_test)}")

    # --- Validate ---
    for split_name, split_data in [("train", all_train), ("val", all_val), ("test", all_test)]:
        invalid = [i for i, r in enumerate(split_data) if not validate_messages(r)]
        if invalid:
            print(f"  WARN: {split_name} has {len(invalid)} invalid records (removing)")
            split_data[:] = [r for r in split_data if validate_messages(r)]
            stats[f"{split_name}_invalid"] = len(invalid)

    # --- Dedup by content hash ---
    def dedup(records: list[dict], name: str) -> list[dict]:
        seen = set()
        out = []
        for r in records:
            h = content_hash(r)
            if h not in seen:
                seen.add(h)
                out.append(r)
        removed = len(records) - len(out)
        if removed:
            print(f"  Dedup {name}: removed {removed} duplicates")
        stats[f"{name}_dedup_removed"] = removed
        return out

    all_train = dedup(all_train, "train")
    all_val = dedup(all_val, "val")
    all_test = dedup(all_test, "test")
    print(f"  After dedup: train={len(all_train)}, val={len(all_val)}, test={len(all_test)}")

    # --- Write ---
    def write_jsonl(records: list[dict], path: Path):
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                # Normalize to just messages
                normalized = {"messages": r["messages"]}
                f.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    write_jsonl(all_train, out_dir / "sonia_combined_train.jsonl")
    write_jsonl(all_val, out_dir / "sonia_combined_val.jsonl")
    write_jsonl(all_test, out_dir / "sonia_combined_test.jsonl")

    # --- Summary ---
    summary = {
        "train_records": len(all_train),
        "val_records": len(all_val),
        "test_records": len(all_test),
        "sources": {
            "sonia_training": {
                "train": len(sonia_train),
                "val": len(sonia_val),
                "test": len(sonia_test),
            },
            "glm_4_7_2000x": {
                "total_raw": len(glm_all),
                "train": len(glm_train),
                "val": len(glm_val),
                "think_tags_stripped": think_stripped,
            },
        },
        "dedup_stats": dict(stats),
    }
    with open(out_dir / "combine_stats.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"  Train: {len(all_train)} records")
    print(f"  Val:   {len(all_val)} records")
    print(f"  Test:  {len(all_test)} records")
    print(f"  Output: {out_dir}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
