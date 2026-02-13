#!/usr/bin/env python3
"""
Combine production package + SoniaDataset into unified train/val JSONL for RunPod.
Validates schema consistency and deduplicates by content_hash where available.
"""
import json
import hashlib
import sys
from pathlib import Path
from collections import Counter

PROD_DIR = Path(r"S:\temp_training_pkg\data")
SONIA_CAP = Path(r"S:\datasets\SoniaDataset\sonia_capabilities\exports")
SONIA_PER = Path(r"S:\datasets\SoniaDataset\sonia_persona\exports")
OUT_DIR = Path(r"S:\training\runpod\data")


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


def validate_messages(rec: dict) -> bool:
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return False
    roles = [m.get("role") for m in msgs]
    if roles[0] != "system":
        return False
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


def strip_to_messages(rec: dict) -> dict:
    """Normalize record to just messages format for training."""
    return {"messages": rec["messages"]}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = Counter()

    # --- Load production package recommended splits ---
    print("Loading production package recommended splits...")
    prod_train = load_jsonl(PROD_DIR / "Sonia_no_think_recommended_train.jsonl")
    prod_val = load_jsonl(PROD_DIR / "Sonia_no_think_recommended_val.jsonl")
    prod_test = load_jsonl(PROD_DIR / "Sonia_no_think_recommended_test.jsonl")
    print(f"  Prod train: {len(prod_train)}, val: {len(prod_val)}, test: {len(prod_test)}")

    # --- Load SoniaDataset full splits ---
    print("Loading SoniaDataset capabilities...")
    cap_train = load_jsonl(SONIA_CAP / "sonia_capabilities_v1_train.jsonl")
    cap_val = load_jsonl(SONIA_CAP / "sonia_capabilities_v1_val.jsonl")
    cap_test = load_jsonl(SONIA_CAP / "sonia_capabilities_v1_test.jsonl")
    print(f"  Cap train: {len(cap_train)}, val: {len(cap_val)}, test: {len(cap_test)}")

    print("Loading SoniaDataset persona...")
    per_train = load_jsonl(SONIA_PER / "sonia_persona_dense_v1_train.jsonl")
    per_val = load_jsonl(SONIA_PER / "sonia_persona_dense_v1_val.jsonl")
    per_test = load_jsonl(SONIA_PER / "sonia_persona_dense_v1_test.jsonl")
    print(f"  Per train: {len(per_train)}, val: {len(per_val)}, test: {len(per_test)}")

    # --- Combine ---
    all_train = prod_train + cap_train + per_train
    all_val = prod_val + cap_val + per_val
    all_test = prod_test + cap_test + per_test
    print(f"\nBefore dedup: train={len(all_train)}, val={len(all_val)}, test={len(all_test)}")

    # --- Validate messages ---
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
    print(f"After dedup: train={len(all_train)}, val={len(all_val)}, test={len(all_test)}")

    # --- Write normalized outputs ---
    def write_jsonl(records: list[dict], path: Path):
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                normalized = strip_to_messages(r)
                f.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    write_jsonl(all_train, OUT_DIR / "sonia_combined_train.jsonl")
    write_jsonl(all_val, OUT_DIR / "sonia_combined_val.jsonl")
    write_jsonl(all_test, OUT_DIR / "sonia_combined_test.jsonl")

    # --- Summary ---
    summary = {
        "train_records": len(all_train),
        "val_records": len(all_val),
        "test_records": len(all_test),
        "sources": {
            "prod_recommended": {"train": len(prod_train), "val": len(prod_val), "test": len(prod_test)},
            "sonia_capabilities": {"train": len(cap_train), "val": len(cap_val), "test": len(cap_test)},
            "sonia_persona": {"train": len(per_train), "val": len(per_val), "test": len(per_test)},
        },
        "dedup_stats": dict(stats),
    }
    with open(OUT_DIR / "combine_stats.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nFinal: train={len(all_train)}, val={len(all_val)}, test={len(all_test)}")
    print(f"Written to {OUT_DIR}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
