"""
Unified CLI -- v2.6 Track A Pipeline Commands

Subcommands:
    validate-manifest    Validate a dataset manifest
    process-text         Run full text processing pipeline
    enforce-invariants   Run identity invariant enforcement on processed data
    export-jsonl         Export conversations to JSONL splits
    run-eval             Run evaluation harness against a model endpoint

Usage:
    python -m pipeline.cli validate-manifest --manifest S:\\datasets\\manifests\\my_dataset.json
    python -m pipeline.cli process-text --input S:\\datasets\\text\\raw
    python -m pipeline.cli enforce-invariants --input S:\\datasets\\text\\processed\\processed.jsonl
    python -m pipeline.cli export-jsonl --input S:\\datasets\\text\\processed\\processed.jsonl
    python -m pipeline.cli run-eval --model-endpoint http://127.0.0.1:7010
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import List


def cmd_validate_manifest(args: argparse.Namespace) -> int:
    """Validate a dataset manifest for strict schema compliance."""
    from datasets.manifests.schema import DatasetManifest, ManifestValidationError

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        manifest = DatasetManifest.load(manifest_path)
        manifest.validate_or_raise(strict=True)
    except ManifestValidationError as e:
        print(f"VALIDATION FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR loading manifest: {e}", file=sys.stderr)
        return 1

    print(f"Manifest valid: {manifest.name} v{manifest.version}")
    print(f"  Schema: {manifest.schema_version}")
    print(f"  Files: {len(manifest.files)}")
    print(f"  Build ID: {manifest.build_id or '(not computed)'}")

    if args.verify_files:
        base_dir = Path(args.base_dir) if args.base_dir else manifest_path.parent
        errors = manifest.verify(base_dir)
        if errors:
            print(f"\nIntegrity errors ({len(errors)}):")
            for err in errors:
                print(f"  - {err}")
            return 1
        print(f"\n  File integrity: {len(manifest.files)} files verified OK")

    return 0


def cmd_process_text(args: argparse.Namespace) -> int:
    """Run the full text processing pipeline."""
    from pipeline.text.process import run_pipeline

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    export_dir = Path(args.export)

    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    stats = run_pipeline(input_dir, output_dir, export_dir, seed=args.seed)
    return 0


def cmd_enforce_invariants(args: argparse.Namespace) -> int:
    """Run identity invariant enforcement on processed data."""
    from pipeline.text.identity_invariants import IdentityInvariantEnforcer

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        return 1

    # Load conversations
    conversations: List[dict] = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                conversations.append(json.loads(line))

    enforcer = IdentityInvariantEnforcer(mode=args.mode)
    passed, report = enforcer.process(conversations)

    # Save report
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "invariant_report.json"
    report.save(report_path)

    print(f"Invariant enforcement ({args.mode} mode):")
    print(f"  Total: {report.total_conversations}")
    print(f"  Violations: {len(report.violations)}")
    print(f"  Removed: {report.conversations_removed}")
    print(f"  Passed: {report.conversations_passed}")
    print(f"  Violation rate: {report.violation_rate:.2%}")
    print(f"  Report: {report_path}")

    if args.output_jsonl:
        out_path = output_dir / "enforced.jsonl"
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            for conv in passed:
                f.write(json.dumps(conv, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"  Output: {out_path} ({len(passed)} conversations)")

    # In enforce mode, return non-zero if violations exceed thresholds
    if args.mode == "enforce":
        critical = sum(1 for v in report.violations
                       if any(kw in v.pattern_matched for kw in ["my name is", "i am sonia", "i'm sonia"]))
        if critical > 0:
            print(f"\nFAILED: {critical} CRITICAL violation(s) found", file=sys.stderr)
            return 1

    return 0


def cmd_export_jsonl(args: argparse.Namespace) -> int:
    """Export conversations to JSONL splits."""
    from pipeline.text.process import export_jsonl, split_dataset

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        return 1

    conversations: List[dict] = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                conversations.append(json.loads(line))

    export_dir = Path(args.export)
    if args.split:
        splits, report = split_dataset(conversations, seed=args.seed)
        for name, convs in splits.items():
            out = export_dir / f"{name}.jsonl"
            count, sha = export_jsonl(convs, out)
            print(f"  {name}: {count} -> {out} (sha256={sha[:12]}...)")
    else:
        out = export_dir / "all.jsonl"
        count, sha = export_jsonl(conversations, out)
        print(f"  all: {count} -> {out} (sha256={sha[:12]}...)")

    return 0


def cmd_run_eval(args: argparse.Namespace) -> int:
    """Run evaluation harness against a model endpoint."""
    from pipeline.eval.harness import run_eval

    eval_dir = Path(args.eval_set)
    if not eval_dir.exists():
        print(f"ERROR: Eval set not found: {eval_dir}", file=sys.stderr)
        return 1

    summary = asyncio.run(run_eval(args.model_endpoint, eval_dir, args.model_id))

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"eval_{args.model_id}_{int(time.time())}.json"
    summary.save(out_path)

    print(f"\nEval: {summary.model_id}")
    print(f"Total: {summary.total}  Passed: {summary.passed}  Failed: {summary.failed}")
    print(f"Pass rate: {summary.pass_rate:.1%}")
    for cat, info in sorted(summary.by_category.items()):
        print(f"  {cat}: {info['passed']}/{info['total']} ({info['pass_rate']:.1%})")
    print(f"Results: {out_path}")

    # Regression gate: non-zero exit if pass rate below threshold
    if args.min_pass_rate > 0 and summary.pass_rate < args.min_pass_rate:
        print(f"\nFAILED: pass rate {summary.pass_rate:.1%} < threshold {args.min_pass_rate:.1%}",
              file=sys.stderr)
        return 1

    # Baseline comparison
    if args.baseline:
        baseline_path = Path(args.baseline)
        if baseline_path.exists():
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            baseline_rate = baseline.get("pass_rate", 0)
            delta = summary.pass_rate - baseline_rate
            print(f"\nBaseline delta: {delta:+.1%} (baseline={baseline_rate:.1%})")
            if delta < -args.regression_threshold:
                print(f"REGRESSION: delta {delta:.1%} exceeds threshold -{args.regression_threshold:.1%}",
                      file=sys.stderr)
                return 1

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="v2.6 Track A Pipeline CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate-manifest
    p_vm = sub.add_parser("validate-manifest", help="Validate a dataset manifest")
    p_vm.add_argument("--manifest", required=True, help="Path to manifest JSON")
    p_vm.add_argument("--verify-files", action="store_true", help="Also verify file hashes")
    p_vm.add_argument("--base-dir", default="", help="Base directory for file verification")

    # process-text
    p_pt = sub.add_parser("process-text", help="Run full text processing pipeline")
    p_pt.add_argument("--input", type=str, default=r"S:\datasets\text\raw")
    p_pt.add_argument("--output", type=str, default=r"S:\datasets\text\processed")
    p_pt.add_argument("--export", type=str, default=r"S:\datasets\exports\jsonl")
    p_pt.add_argument("--seed", type=int, default=42)

    # enforce-invariants
    p_ei = sub.add_parser("enforce-invariants", help="Run identity invariant enforcement")
    p_ei.add_argument("--input", required=True, help="Path to processed.jsonl")
    p_ei.add_argument("--output", type=str, default=r"S:\datasets\text\processed")
    p_ei.add_argument("--mode", choices=["audit", "enforce"], default="enforce")
    p_ei.add_argument("--output-jsonl", action="store_true", help="Write filtered output")

    # export-jsonl
    p_ej = sub.add_parser("export-jsonl", help="Export to JSONL splits")
    p_ej.add_argument("--input", required=True, help="Path to processed.jsonl")
    p_ej.add_argument("--export", type=str, default=r"S:\datasets\exports\jsonl")
    p_ej.add_argument("--split", action="store_true", help="Split into train/val/test")
    p_ej.add_argument("--seed", type=int, default=42)

    # run-eval
    p_re = sub.add_parser("run-eval", help="Run evaluation harness")
    p_re.add_argument("--model-endpoint", default="http://127.0.0.1:7010")
    p_re.add_argument("--eval-set", type=str, default=r"S:\datasets\eval")
    p_re.add_argument("--model-id", default="unknown")
    p_re.add_argument("--output", type=str, default=r"S:\datasets\eval\results")
    p_re.add_argument("--min-pass-rate", type=float, default=0.0,
                       help="Fail if pass rate below this (0-1)")
    p_re.add_argument("--baseline", default="", help="Path to baseline eval JSON for regression comparison")
    p_re.add_argument("--regression-threshold", type=float, default=0.05,
                       help="Max acceptable regression from baseline (0-1)")

    args = parser.parse_args()
    dispatch = {
        "validate-manifest": cmd_validate_manifest,
        "process-text": cmd_process_text,
        "enforce-invariants": cmd_enforce_invariants,
        "export-jsonl": cmd_export_jsonl,
        "run-eval": cmd_run_eval,
    }
    handler = dispatch.get(args.command)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
