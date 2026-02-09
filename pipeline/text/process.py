"""
Text Processing Pipeline — v2.6 Track A

Deterministic pipeline: normalize -> dedupe -> classify -> split -> export JSONL

Usage:
    python process.py --input S:\\datasets\\text\\raw --output S:\\datasets\\text\\processed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Stage 1: Normalize
# ---------------------------------------------------------------------------

# C0 control chars except \n \r \t
_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# collapse runs of whitespace (preserve newlines)
_WS_RE = re.compile(r"[^\S\n]+")
# collapse 3+ consecutive newlines
_NL_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Strip C0 chars, normalize unicode, collapse whitespace."""
    text = unicodedata.normalize("NFC", text)
    text = _C0_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def normalize_conversation(conv: dict) -> dict:
    """Normalize all message content fields in a conversation."""
    messages = conv.get("messages", [])
    for msg in messages:
        if "content" in msg and isinstance(msg["content"], str):
            msg["content"] = normalize_text(msg["content"])
    return conv


# ---------------------------------------------------------------------------
# Stage 2: Deduplicate
# ---------------------------------------------------------------------------

def content_hash(conv: dict) -> str:
    """Deterministic hash of message contents for dedup."""
    parts = []
    for msg in conv.get("messages", []):
        parts.append(f"{msg.get('role', '')}:{msg.get('content', '')}")
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def deduplicate(conversations: List[dict]) -> List[dict]:
    """Remove exact-content duplicates, preserving first occurrence order."""
    seen: set[str] = set()
    result: List[dict] = []
    for conv in conversations:
        h = content_hash(conv)
        if h not in seen:
            seen.add(h)
            result.append(conv)
    return result


# ---------------------------------------------------------------------------
# Stage 3: Classify
# ---------------------------------------------------------------------------

# Simple keyword/heuristic classifier — will be refined with model-based
# classification in later iterations.

CATEGORIES = [
    "style",        # persona / tone examples
    "tool_use",     # tool calling patterns
    "roleplay",     # creative / scenario conversations
    "refusal",      # safety refusal examples
    "instruction",  # direct instruction following
    "knowledge",    # factual Q&A
    "correction",   # error correction examples
    "other",
]

_TOOL_PATTERNS = re.compile(
    r"(tool_call|function_call|<tool>|action_type|execute_action)", re.IGNORECASE
)
_REFUSAL_PATTERNS = re.compile(
    r"(i can't|i cannot|i'm unable|i am unable|i won't|not appropriate|against my guidelines)",
    re.IGNORECASE,
)
_ROLEPLAY_PATTERNS = re.compile(
    r"(\*[^*]+\*|roleplay|in character|pretend|scenario)", re.IGNORECASE
)


def classify_conversation(conv: dict) -> str:
    """Assign a primary category to a conversation."""
    all_text = " ".join(
        msg.get("content", "") for msg in conv.get("messages", [])
    )
    if _TOOL_PATTERNS.search(all_text):
        return "tool_use"
    if _REFUSAL_PATTERNS.search(all_text):
        return "refusal"
    if _ROLEPLAY_PATTERNS.search(all_text):
        return "roleplay"
    # Check for correction patterns
    for msg in conv.get("messages", []):
        if msg.get("role") == "assistant" and "correction" in msg.get("metadata", {}).get("type", ""):
            return "correction"
    # Default to instruction/knowledge/style based on length heuristic
    assistant_msgs = [m for m in conv.get("messages", []) if m.get("role") == "assistant"]
    if not assistant_msgs:
        return "other"
    avg_len = sum(len(m.get("content", "")) for m in assistant_msgs) / len(assistant_msgs)
    if avg_len > 500:
        return "knowledge"
    return "style"


# ---------------------------------------------------------------------------
# Stage 4: Split
# ---------------------------------------------------------------------------

def split_dataset(
    conversations: List[dict],
    train_ratio: float = 0.85,
    val_ratio: float = 0.10,
    test_ratio: float = 0.05,
    seed: int = 42,
) -> dict[str, List[dict]]:
    """Deterministic stratified split by category."""
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6

    # Group by category
    by_cat: dict[str, List[dict]] = {}
    for conv in conversations:
        cat = conv.get("_category", "other")
        by_cat.setdefault(cat, []).append(conv)

    rng = random.Random(seed)
    splits: dict[str, List[dict]] = {"train": [], "val": [], "test": []}

    for cat, items in sorted(by_cat.items()):
        rng.shuffle(items)
        n = len(items)
        n_train = max(1, int(n * train_ratio))
        n_val = max(0, int(n * val_ratio))
        # rest goes to test
        splits["train"].extend(items[:n_train])
        splits["val"].extend(items[n_train:n_train + n_val])
        splits["test"].extend(items[n_train + n_val:])

    return splits


# ---------------------------------------------------------------------------
# Stage 5: Export JSONL
# ---------------------------------------------------------------------------

def export_jsonl(conversations: List[dict], output_path: Path) -> int:
    """Write conversations as JSONL, stripping internal metadata. Returns count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for conv in conversations:
            # Strip internal fields
            export = {k: v for k, v in conv.items() if not k.startswith("_")}
            f.write(json.dumps(export, ensure_ascii=False) + "\n")
            count += 1
    return count


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def load_raw_conversations(input_dir: Path) -> List[dict]:
    """Load all .jsonl files from input directory."""
    conversations: List[dict] = []
    for path in sorted(input_dir.rglob("*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    conversations.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"WARN: {path}:{line_num} invalid JSON, skipping", file=sys.stderr)
    return conversations


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    export_dir: Optional[Path] = None,
    seed: int = 42,
) -> dict:
    """Execute the full pipeline. Returns stats dict."""
    if export_dir is None:
        export_dir = Path(r"S:\datasets\exports\jsonl")

    stats: dict = {}

    # 1. Load
    raw = load_raw_conversations(input_dir)
    stats["raw_count"] = len(raw)
    print(f"[1/5] Loaded {len(raw)} conversations")

    # 2. Normalize
    normalized = [normalize_conversation(c) for c in raw]
    stats["normalized_count"] = len(normalized)
    print(f"[2/5] Normalized {len(normalized)} conversations")

    # 3. Deduplicate
    deduped = deduplicate(normalized)
    stats["deduped_count"] = len(deduped)
    stats["duplicates_removed"] = len(normalized) - len(deduped)
    print(f"[3/5] Deduplicated: {len(deduped)} unique ({stats['duplicates_removed']} removed)")

    # 4. Classify
    for conv in deduped:
        conv["_category"] = classify_conversation(conv)
    cat_counts = {}
    for conv in deduped:
        cat = conv["_category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    stats["categories"] = cat_counts
    print(f"[4/5] Classified: {cat_counts}")

    # 5. Split + Export
    splits = split_dataset(deduped, seed=seed)
    stats["splits"] = {}
    for split_name, convs in splits.items():
        out_path = export_dir / f"{split_name}.jsonl"
        count = export_jsonl(convs, out_path)
        stats["splits"][split_name] = count
        print(f"[5/5] Exported {split_name}: {count} -> {out_path}")

    # Save processed conversations (with metadata) for inspection
    processed_path = output_dir / "processed.jsonl"
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    with open(processed_path, "w", encoding="utf-8") as f:
        for conv in deduped:
            f.write(json.dumps(conv, ensure_ascii=False) + "\n")

    # Save stats
    stats_path = output_dir / "pipeline_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"\nStats saved to {stats_path}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Text Processing Pipeline v2.6")
    parser.add_argument("--input", type=Path, default=Path(r"S:\datasets\text\raw"),
                        help="Input directory with raw .jsonl files")
    parser.add_argument("--output", type=Path, default=Path(r"S:\datasets\text\processed"),
                        help="Output directory for processed data")
    parser.add_argument("--export", type=Path, default=Path(r"S:\datasets\exports\jsonl"),
                        help="Export directory for final JSONL splits")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for splitting")
    args = parser.parse_args()

    run_pipeline(args.input, args.output, args.export, seed=args.seed)


if __name__ == "__main__":
    main()
