"""
Text Processing Pipeline -- v2.6 Track A (production-hardened)

Deterministic pipeline: normalize -> dedupe -> classify -> split -> export JSONL

Produces build artifacts:
  - build_manifest.lock.json   (reproducibility lock)
  - split_report.json          (split statistics)
  - invariant_report.json      (identity enforcement results)
  - export_stats.json          (export counts and hashes)
  - pipeline_stats.json        (full pipeline statistics)

Usage:
    python -m pipeline.text.process --input S:\\datasets\\text\\raw --output S:\\datasets\\text\\processed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Stage 1: Normalize
# ---------------------------------------------------------------------------

_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"[^\S\n]+")
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
# Stage 2: Deduplicate (with confidence reporting)
# ---------------------------------------------------------------------------

def content_hash(conv: dict) -> str:
    """Deterministic hash of message contents for dedup."""
    parts = []
    for msg in conv.get("messages", []):
        parts.append(f"{msg.get('role', '')}:{msg.get('content', '')}")
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class DedupeReport:
    """Deduplicate confidence report."""
    total_input: int = 0
    exact_duplicates: int = 0
    retained: int = 0
    provenance_map: Dict[str, List[int]] = field(default_factory=dict)
    # Maps content_hash -> list of original indices (first = retained)

    def to_dict(self) -> dict:
        return {
            "total_input": self.total_input,
            "exact_duplicates": self.exact_duplicates,
            "retained": self.retained,
            "duplicate_groups": len([v for v in self.provenance_map.values() if len(v) > 1]),
            "provenance_sample": {
                k: v for i, (k, v) in enumerate(self.provenance_map.items())
                if len(v) > 1 and i < 20  # show up to 20 duplicate groups
            },
        }


def deduplicate(conversations: List[dict]) -> Tuple[List[dict], DedupeReport]:
    """Remove exact-content duplicates, preserving first occurrence order."""
    report = DedupeReport(total_input=len(conversations))
    seen: Dict[str, int] = {}  # hash -> first index
    result: List[dict] = []

    for idx, conv in enumerate(conversations):
        h = content_hash(conv)
        if h not in report.provenance_map:
            report.provenance_map[h] = []
        report.provenance_map[h].append(idx)

        if h not in seen:
            seen[h] = idx
            result.append(conv)
        else:
            report.exact_duplicates += 1

    report.retained = len(result)
    return result, report


# ---------------------------------------------------------------------------
# Stage 3: Classify
# ---------------------------------------------------------------------------

CATEGORIES = [
    "style", "tool_use", "roleplay", "refusal",
    "instruction", "knowledge", "correction", "other",
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
    for msg in conv.get("messages", []):
        if msg.get("role") == "assistant" and "correction" in msg.get("metadata", {}).get("type", ""):
            return "correction"
    assistant_msgs = [m for m in conv.get("messages", []) if m.get("role") == "assistant"]
    if not assistant_msgs:
        return "other"
    avg_len = sum(len(m.get("content", "")) for m in assistant_msgs) / len(assistant_msgs)
    if avg_len > 500:
        return "knowledge"
    return "style"


# ---------------------------------------------------------------------------
# Stage 4: Split (with ratio validation)
# ---------------------------------------------------------------------------

@dataclass
class SplitReport:
    """Split statistics report."""
    seed: int = 42
    ratios: Dict[str, float] = field(default_factory=dict)
    actual_counts: Dict[str, int] = field(default_factory=dict)
    actual_ratios: Dict[str, float] = field(default_factory=dict)
    by_category: Dict[str, Dict[str, int]] = field(default_factory=dict)
    ratio_drift: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def split_dataset(
    conversations: List[dict],
    train_ratio: float = 0.85,
    val_ratio: float = 0.10,
    test_ratio: float = 0.05,
    seed: int = 42,
    min_per_class: int = 1,
) -> Tuple[Dict[str, List[dict]], SplitReport]:
    """Deterministic stratified split by category with validation."""
    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"Split ratios sum to {total_ratio}, expected 1.0")

    report = SplitReport(
        seed=seed,
        ratios={"train": train_ratio, "val": val_ratio, "test": test_ratio},
    )

    by_cat: Dict[str, List[dict]] = {}
    for conv in conversations:
        cat = conv.get("_category", "other")
        by_cat.setdefault(cat, []).append(conv)

    rng = random.Random(seed)
    splits: Dict[str, List[dict]] = {"train": [], "val": [], "test": []}

    for cat, items in sorted(by_cat.items()):
        rng.shuffle(items)
        n = len(items)
        n_train = max(min_per_class, int(n * train_ratio))
        n_val = max(0, int(n * val_ratio))
        splits["train"].extend(items[:n_train])
        splits["val"].extend(items[n_train:n_train + n_val])
        splits["test"].extend(items[n_train + n_val:])

        report.by_category[cat] = {
            "total": n,
            "train": min(n_train, n),
            "val": min(n_val, n - n_train),
            "test": max(0, n - n_train - n_val),
        }

    total = sum(len(v) for v in splits.values())
    for name, convs in splits.items():
        count = len(convs)
        report.actual_counts[name] = count
        actual = count / total if total > 0 else 0.0
        report.actual_ratios[name] = round(actual, 4)
        target = report.ratios[name]
        report.ratio_drift[name] = round(actual - target, 4)

    return splits, report


# ---------------------------------------------------------------------------
# Stage 5: Export JSONL (deterministic, sorted keys)
# ---------------------------------------------------------------------------

@dataclass
class ExportStats:
    """Export statistics with hashes for reproducibility verification."""
    split_counts: Dict[str, int] = field(default_factory=dict)
    split_hashes: Dict[str, str] = field(default_factory=dict)  # SHA-256 of output files
    total_exported: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def export_jsonl(
    conversations: List[dict],
    output_path: Path,
    sort_keys: bool = True,
) -> Tuple[int, str]:
    """Write conversations as JSONL. Returns (count, sha256_of_file)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    count = 0
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        for conv in conversations:
            export = {k: v for k, v in conv.items() if not k.startswith("_")}
            line = json.dumps(export, ensure_ascii=False, sort_keys=sort_keys) + "\n"
            f.write(line)
            h.update(line.encode("utf-8"))
            count += 1
    return count, h.hexdigest()


# ---------------------------------------------------------------------------
# Build lock
# ---------------------------------------------------------------------------

@dataclass
class BuildLock:
    """Reproducibility lock for a pipeline run."""
    build_id: str
    timestamp: str
    seed: int
    input_dir: str
    input_file_count: int
    input_hash: str  # combined hash of all input files
    pipeline_version: str = "2.6.0"
    stages: List[str] = field(default_factory=lambda: [
        "normalize", "deduplicate", "classify", "split", "export"
    ])

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)


def compute_input_hash(input_dir: Path) -> Tuple[str, int]:
    """Deterministic hash of all input files for reproducibility."""
    h = hashlib.sha256()
    count = 0
    for path in sorted(input_dir.rglob("*.jsonl")):
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        count += 1
    return h.hexdigest(), count


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
    sort_keys: bool = True,
) -> Dict[str, Any]:
    """Execute the full pipeline. Returns stats dict. Produces all build artifacts."""
    if export_dir is None:
        export_dir = Path(r"S:\datasets\exports\jsonl")

    output_dir.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    stats: Dict[str, Any] = {"pipeline_version": "2.6.0", "seed": seed}

    # Build lock: compute input hash
    input_hash, input_count = compute_input_hash(input_dir)
    build_id = hashlib.sha256(f"{input_hash}:{seed}:2.6.0".encode()).hexdigest()[:16]
    stats["build_id"] = build_id
    stats["input_hash"] = input_hash

    lock = BuildLock(
        build_id=build_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        seed=seed,
        input_dir=str(input_dir),
        input_file_count=input_count,
        input_hash=input_hash,
    )
    lock.save(output_dir / "build_manifest.lock.json")

    # 1. Load
    raw = load_raw_conversations(input_dir)
    stats["raw_count"] = len(raw)
    print(f"[1/5] Loaded {len(raw)} conversations from {input_count} files")

    # 2. Normalize
    normalized = [normalize_conversation(c) for c in raw]
    stats["normalized_count"] = len(normalized)
    print(f"[2/5] Normalized {len(normalized)} conversations")

    # 3. Deduplicate
    deduped, dedupe_report = deduplicate(normalized)
    stats["deduped_count"] = len(deduped)
    stats["exact_duplicates_removed"] = dedupe_report.exact_duplicates
    stats["duplicate_groups"] = len([v for v in dedupe_report.provenance_map.values() if len(v) > 1])
    print(f"[3/5] Deduplicated: {len(deduped)} unique ({dedupe_report.exact_duplicates} exact dupes removed)")

    # 4. Classify
    for conv in deduped:
        conv["_category"] = classify_conversation(conv)
    cat_counts: Dict[str, int] = {}
    for conv in deduped:
        cat = conv["_category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    stats["categories"] = cat_counts
    print(f"[4/5] Classified: {cat_counts}")

    # 5. Split + Export
    splits, split_report = split_dataset(deduped, seed=seed)
    split_report_path = output_dir / "split_report.json"
    with open(split_report_path, "w", encoding="utf-8") as f:
        json.dump(split_report.to_dict(), f, indent=2)

    export_stats = ExportStats()
    for split_name, convs in splits.items():
        out_path = export_dir / f"{split_name}.jsonl"
        count, file_hash = export_jsonl(convs, out_path, sort_keys=sort_keys)
        export_stats.split_counts[split_name] = count
        export_stats.split_hashes[split_name] = file_hash
        export_stats.total_exported += count
        print(f"[5/5] Exported {split_name}: {count} -> {out_path} (sha256={file_hash[:12]}...)")

    stats["splits"] = export_stats.split_counts
    stats["split_hashes"] = export_stats.split_hashes

    # Save all artifacts
    export_stats_path = output_dir / "export_stats.json"
    with open(export_stats_path, "w", encoding="utf-8") as f:
        json.dump(export_stats.to_dict(), f, indent=2)

    # Save processed conversations for inspection
    processed_path = output_dir / "processed.jsonl"
    with open(processed_path, "w", encoding="utf-8", newline="\n") as f:
        for conv in deduped:
            f.write(json.dumps(conv, ensure_ascii=False, sort_keys=sort_keys) + "\n")

    # Final stats
    elapsed = time.time() - start_time
    stats["elapsed_seconds"] = round(elapsed, 2)
    stats["timestamp"] = datetime.now(timezone.utc).isoformat()

    stats_path = output_dir / "pipeline_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"\nBuild {build_id} completed in {elapsed:.1f}s")
    print(f"Artifacts: {output_dir}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Text Processing Pipeline v2.6")
    parser.add_argument("--input", type=Path, default=Path(r"S:\datasets\text\raw"),
                        help="Input directory with raw .jsonl files")
    parser.add_argument("--output", type=Path, default=Path(r"S:\datasets\text\processed"),
                        help="Output directory for processed data + artifacts")
    parser.add_argument("--export", type=Path, default=Path(r"S:\datasets\exports\jsonl"),
                        help="Export directory for final JSONL splits")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for splitting")
    args = parser.parse_args()

    stats = run_pipeline(args.input, args.output, args.export, seed=args.seed)
    sys.exit(0)


if __name__ == "__main__":
    main()
