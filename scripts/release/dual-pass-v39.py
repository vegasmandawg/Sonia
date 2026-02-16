#!/usr/bin/env python3
"""
v3.9 Dual-Pass Reassessment Runner (User-provided architecture)
===============================================================
- Contract-locked A..Y scoring (0..20 per section, total 500)
- Standard + Conservative scorers
- Evidence-driven deductions only
- Legacy deductions removed for closed sections when Epic evidence exists

Adapted to match SONIA gate-matrix schema v6.0 output format.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

SECTIONS = [chr(c) for c in range(ord("A"), ord("Y") + 1)]

# Closed-deduction sections (Epic 1 + Epic 2)
CLOSED_DEDUCTION_SECTIONS = {"J", "S", "M", "O", "Q", "W", "C", "D", "K", "L", "N", "T"}

# Canonical section labels
SECTION_LABELS = {
    "A": "Governance & Process",
    "B": "Architecture & Design",
    "C": "Code Quality",
    "D": "Configuration Mgmt",
    "E": "Deployment & Release",
    "F": "API Design",
    "G": "Error Handling",
    "H": "Logging & Monitoring",
    "I": "Auth & Authorization",
    "J": "Data Management",
    "K": "Performance",
    "L": "Testing Strategy",
    "M": "Data Stores",
    "N": "Observability",
    "O": "Operational Readiness",
    "P": "Security Controls",
    "Q": "Privacy & Data",
    "R": "Dependency Mgmt",
    "S": "CI/CD & Automation",
    "T": "Documentation Quality",
    "U": "Backup & Recovery",
    "V": "Incident Response",
    "W": "Operations Docs",
    "X": "Release Management",
    "Y": "Compliance & Audit",
}


@dataclass
class EvidenceSnapshot:
    root: Path
    timestamp: str
    expected_unit_tests: int
    expected_inherited_gates: int
    expected_delta_gates: int

    # Core evidence files
    scorer_contract_path: Path
    scope_lock_path: Path

    # Discovered artifacts
    gate_matrix_file: Path | None
    epic_gate_files: Dict[str, Path | None]
    baseline_manifest_file: Path | None
    release_manifest_file: Path | None

    # Parsed facts
    inherited_pass: int
    inherited_total: int
    delta_pass: int
    delta_total: int
    unit_passed: int
    unit_failed: int

    # booleans used in scoring
    checks: Dict[str, bool]


def _now_ts() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _latest_file(pattern: str) -> Path | None:
    matches = glob.glob(pattern)
    if not matches:
        return None
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return Path(matches[0])


def _read_json(path: Path | None) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _json_verdict_pass(data: Dict[str, Any]) -> bool:
    if not data:
        return False

    # common variants
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict in {"pass", "passed", "promote", "ok"}:
        return True
    if verdict in {"fail", "failed", "hold"}:
        return False

    # check arrays
    checks = data.get("checks")
    if isinstance(checks, list) and checks:
        statuses = [str(c.get("status", "")).strip().lower() for c in checks if isinstance(c, dict)]
        if statuses and all(s in {"pass", "passed", "ok"} for s in statuses):
            return True

    # summary counts
    passed = data.get("passed")
    total = data.get("total") or data.get("checks_total")
    if isinstance(passed, (int, float)) and isinstance(total, (int, float)) and int(total) > 0:
        return int(passed) == int(total)

    return False


def _parse_gate_matrix(data: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """
    Returns: inherited_pass, inherited_total, delta_pass, delta_total
    Supports SONIA gate-matrix schema v6.0.
    """
    inherited_pass = inherited_total = delta_pass = delta_total = 0

    if not data:
        return inherited_pass, inherited_total, delta_pass, delta_total

    # Schema v6.0: flat gates list with "category" field
    gates = data.get("gates")
    if isinstance(gates, list):
        for g in gates:
            if not isinstance(g, dict):
                continue
            status_bool = g.get("passed", False)
            category = str(g.get("category", "")).strip().lower()

            is_pass = bool(status_bool)

            if category == "delta":
                delta_total += 1
                if is_pass:
                    delta_pass += 1
            elif category == "inherited":
                inherited_total += 1
                if is_pass:
                    inherited_pass += 1
            # test_floor category is tracked separately

    # Fallback: use top-level counts if gates list parsing yields nothing
    if inherited_total == 0 and delta_total == 0:
        total = _safe_int(data.get("gates_total", 0))
        passed = _safe_int(data.get("gates_passed", 0))
        delta_wired = _safe_int(data.get("delta_gates_wired", 0))
        inh_floor = _safe_int(data.get("inherited_floor", 0))

        inherited_total = inh_floor
        delta_total = delta_wired
        # If all passed
        if passed == total:
            inherited_pass = inherited_total
            delta_pass = delta_total
        else:
            # Conservative: assume inherited passed, delta uncertain
            inherited_pass = min(inh_floor, passed)
            delta_pass = max(0, passed - inherited_pass - 1)  # -1 for test_floor

    return inherited_pass, inherited_total, delta_pass, delta_total


def _parse_unit_from_matrix(data: Dict[str, Any]) -> Tuple[int, int]:
    """Extract unit test counts from gate-matrix (schema v6.0 embeds them)."""
    if not data:
        return 0, 0
    p = _safe_int(data.get("unit_tests_passed", 0))
    f = _safe_int(data.get("unit_tests_failed", 0))
    return p, f


def build_snapshot(root: Path, expected_unit_tests: int, expected_inherited_gates: int, expected_delta_gates: int, ts: str) -> EvidenceSnapshot:
    reports = root / "reports" / "audit"
    docs = root / "docs"

    scorer_contract = docs / "SCORER_CONTRACT_V39.md"
    scope_lock = docs / "V3_9_SCOPE_LOCK.md"

    gate_matrix = _latest_file(str(reports / "gate-matrix-v39*.json"))

    epic_gate_files = {
        "coverage_completeness": _latest_file(str(reports / "coverage-completeness-*.json")),
        "data_durability": _latest_file(str(reports / "data-durability-*.json")),
        "deduction_sweep": _latest_file(str(reports / "deduction-sweep-*.json")),
        "test_strategy": _latest_file(str(reports / "test-strategy-*.json")),
    }

    baseline_manifest = _latest_file(str(reports / "v3.9-baseline" / "*manifest*"))
    release_manifest = _latest_file(str(root / "releases" / "v3.9.0" / "*manifest*"))

    gate_data = _read_json(gate_matrix)
    inh_p, inh_t, dlt_p, dlt_t = _parse_gate_matrix(gate_data)

    # Unit tests from gate-matrix (schema v6.0 embeds them)
    unit_p, unit_f = _parse_unit_from_matrix(gate_data)

    # Epic gate pass booleans
    epic_pass = {k: _json_verdict_pass(_read_json(v)) for k, v in epic_gate_files.items()}

    checks = {
        "scorer_contract_present": scorer_contract.exists(),
        "scope_lock_present": scope_lock.exists(),
        "baseline_manifest_present": baseline_manifest is not None,
        "release_manifest_present": release_manifest is not None,
        "gate_matrix_present": gate_matrix is not None,
        "inherited_floor_pass": (inh_t >= expected_inherited_gates and inh_p == inh_t),
        "delta_gates_pass": (dlt_t >= expected_delta_gates and dlt_p == dlt_t),
        "unit_floor_pass": (unit_p >= expected_unit_tests and unit_f == 0),
        "epic1_pass": epic_pass.get("coverage_completeness", False) and epic_pass.get("data_durability", False),
        "epic2_pass": epic_pass.get("deduction_sweep", False) and epic_pass.get("test_strategy", False),
        "coverage_completeness_pass": epic_pass.get("coverage_completeness", False),
        "data_durability_pass": epic_pass.get("data_durability", False),
        "deduction_sweep_pass": epic_pass.get("deduction_sweep", False),
        "test_strategy_pass": epic_pass.get("test_strategy", False),
        "non_goals_locked": scope_lock.exists(),
    }

    return EvidenceSnapshot(
        root=root,
        timestamp=ts,
        expected_unit_tests=expected_unit_tests,
        expected_inherited_gates=expected_inherited_gates,
        expected_delta_gates=expected_delta_gates,
        scorer_contract_path=scorer_contract,
        scope_lock_path=scope_lock,
        gate_matrix_file=gate_matrix,
        epic_gate_files=epic_gate_files,
        baseline_manifest_file=baseline_manifest,
        release_manifest_file=release_manifest,
        inherited_pass=inh_p,
        inherited_total=inh_t,
        delta_pass=dlt_p,
        delta_total=dlt_t,
        unit_passed=unit_p,
        unit_failed=unit_f,
        checks=checks,
    )


def _section_requirements() -> Dict[str, Dict[str, List[str]]]:
    """
    requirements per section:
    - required: missing => stronger deduction
    - bonus: missing => lighter deduction
    """
    return {
        "A": {"required": ["scorer_contract_present", "scope_lock_present"], "bonus": ["baseline_manifest_present"]},
        "B": {"required": ["gate_matrix_present"], "bonus": ["release_manifest_present"]},
        "C": {"required": ["deduction_sweep_pass"], "bonus": ["unit_floor_pass"]},
        "D": {"required": ["deduction_sweep_pass"], "bonus": ["scope_lock_present"]},
        "E": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "F": {"required": ["inherited_floor_pass"], "bonus": ["gate_matrix_present"]},
        "G": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "H": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "I": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "J": {"required": ["data_durability_pass", "coverage_completeness_pass"], "bonus": ["unit_floor_pass"]},
        "K": {"required": ["deduction_sweep_pass"], "bonus": ["unit_floor_pass"]},
        "L": {"required": ["deduction_sweep_pass", "test_strategy_pass"], "bonus": ["gate_matrix_present"]},
        "M": {"required": ["data_durability_pass"], "bonus": ["coverage_completeness_pass"]},
        "N": {"required": ["deduction_sweep_pass"], "bonus": ["inherited_floor_pass"]},
        "O": {"required": ["coverage_completeness_pass"], "bonus": ["inherited_floor_pass"]},
        "P": {"required": ["inherited_floor_pass"], "bonus": ["release_manifest_present"]},
        "Q": {"required": ["coverage_completeness_pass"], "bonus": ["inherited_floor_pass"]},
        "R": {"required": ["unit_floor_pass"], "bonus": ["test_strategy_pass"]},
        "S": {"required": ["coverage_completeness_pass", "test_strategy_pass"], "bonus": ["gate_matrix_present"]},
        "T": {"required": ["deduction_sweep_pass", "test_strategy_pass"], "bonus": ["release_manifest_present"]},
        "U": {"required": ["data_durability_pass"], "bonus": ["baseline_manifest_present"]},
        "V": {"required": ["inherited_floor_pass"], "bonus": ["data_durability_pass"]},
        "W": {"required": ["coverage_completeness_pass", "scope_lock_present"], "bonus": ["baseline_manifest_present"]},
        "X": {"required": ["unit_floor_pass"], "bonus": ["gate_matrix_present"]},
        "Y": {"required": ["inherited_floor_pass", "delta_gates_pass", "unit_floor_pass"], "bonus": ["release_manifest_present"]},
    }


def score_run(snapshot: EvidenceSnapshot, scorer_type: str) -> Dict[str, Any]:
    if scorer_type not in {"standard", "conservative"}:
        raise ValueError("scorer_type must be standard or conservative")

    req = _section_requirements()

    # Deduction weights
    if scorer_type == "standard":
        req_penalty = 2
        bonus_penalty = 1
    else:
        req_penalty = 3
        bonus_penalty = 1

    sections: Dict[str, Dict[str, Any]] = {}
    total = 0

    for s in SECTIONS:
        required_checks = req[s]["required"]
        bonus_checks = req[s]["bonus"]

        missing_required = [c for c in required_checks if not snapshot.checks.get(c, False)]
        missing_bonus = [c for c in bonus_checks if not snapshot.checks.get(c, False)]

        score = 20 - req_penalty * len(missing_required) - bonus_penalty * len(missing_bonus)

        # Closed-deduction protection:
        # if section is in CLOSED_DEDUCTION_SECTIONS and both epic packages pass,
        # do not apply any "legacy deduction" beyond concrete evidence misses.
        if s in CLOSED_DEDUCTION_SECTIONS and snapshot.checks["epic1_pass"] and snapshot.checks["epic2_pass"]:
            # No extra adjustment; explicit here to document elimination behavior.
            pass

        score = max(0, min(20, score))
        total += score

        evidence_refs = []
        if snapshot.gate_matrix_file:
            evidence_refs.append(str(snapshot.gate_matrix_file))
        for k, p in snapshot.epic_gate_files.items():
            if p:
                evidence_refs.append(str(p))

        reason_parts = []
        if missing_required:
            reason_parts.append(f"missing required checks: {', '.join(missing_required)}")
        if missing_bonus:
            reason_parts.append(f"missing bonus checks: {', '.join(missing_bonus)}")
        if not reason_parts:
            reason_parts.append("all mapped evidence checks satisfied")

        sections[s] = {
            "label": SECTION_LABELS.get(s, ""),
            "score": score,
            "max": 20,
            "reason": "; ".join(reason_parts),
            "evidence": sorted(set(evidence_refs)),
        }

    percent = round((total / 500) * 100, 1)

    run = {
        "run_id": f"v3.9-dual-pass-{snapshot.timestamp}",
        "scorer_type": scorer_type,
        "version": "3.9.0-dev",
        "scale": "0-20 per section",
        "sections": sections,
        "total": total,
        "percent": percent,
        "floor_78_pass": total >= 390,
        "notes": [
            "Scoring constrained by SCORER_CONTRACT_V39.md",
            "Non-goal penalties invalidated by scope lock policy",
            "Closed deduction sections protected when Epic 1+2 evidence is present",
            f"Expected unit floor: {snapshot.expected_unit_tests}, observed: {snapshot.unit_passed}/{snapshot.unit_passed + snapshot.unit_failed}",
            f"Inherited gates: {snapshot.inherited_pass}/{snapshot.inherited_total}, delta gates: {snapshot.delta_pass}/{snapshot.delta_total}",
        ],
    }
    return run


def build_diff(standard: Dict[str, Any], conservative: Dict[str, Any]) -> Dict[str, Any]:
    diffs = []
    for s in SECTIONS:
        st = _safe_int(standard["sections"][s]["score"])
        cv = _safe_int(conservative["sections"][s]["score"])
        diffs.append({
            "section": s,
            "label": SECTION_LABELS.get(s, ""),
            "standard": st,
            "conservative": cv,
            "gap": abs(st - cv),
        })

    diffs_sorted = sorted(diffs, key=lambda x: x["gap"], reverse=True)
    total_gap = abs(_safe_int(standard["total"]) - _safe_int(conservative["total"]))
    mean_score = (_safe_int(standard["total"]) + _safe_int(conservative["total"])) / 2.0

    return {
        "run_id": standard["run_id"],
        "version": "3.9.0-dev",
        "standard_total": standard["total"],
        "conservative_total": conservative["total"],
        "mean_total": mean_score,
        "inter_pass_gap_points": total_gap,
        "inter_pass_gap_pct": round((total_gap / 500) * 100, 1),
        "dispersion_from_mean_points": round(total_gap / 2.0, 1),
        "dispersion_from_mean_pct": round(((total_gap / 2.0) / 500) * 100, 1),
        "both_floor_78_pass": bool(standard["floor_78_pass"] and conservative["floor_78_pass"]),
        "sections_below_15_conservative": [
            s for s in SECTIONS if _safe_int(conservative["sections"][s]["score"]) < 15
        ],
        "top_5_disagreements": diffs_sorted[:5],
        "all_section_gaps": diffs_sorted,
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_summary_md(path: Path, snapshot: EvidenceSnapshot, std: Dict[str, Any], con: Dict[str, Any], diff: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# v3.9 Dual-Pass Reassessment Summary (artifact-driven)")
    lines.append("")
    lines.append(f"- Timestamp (UTC): {snapshot.timestamp}")
    lines.append(f"- Version: 3.9.0-dev")
    lines.append(f"- Standard: {std['total']}/500 ({std['percent']}%)")
    lines.append(f"- Conservative: {con['total']}/500 ({con['percent']}%)")
    lines.append(f"- Mean: {diff['mean_total']}/500 ({round((diff['mean_total']/500)*100,1)}%)")
    lines.append(f"- Inter-pass gap: {diff['inter_pass_gap_points']} points ({diff['inter_pass_gap_pct']}%)")
    lines.append(f"- Dispersion from mean: +/-{diff['dispersion_from_mean_points']} points (+/-{diff['dispersion_from_mean_pct']}%)")
    lines.append(f"- Floor (>=78% both): {'PASS' if diff['both_floor_78_pass'] else 'FAIL'}")
    lines.append("")
    lines.append("## Evidence Snapshot")
    lines.append(f"- Gate matrix: `{snapshot.gate_matrix_file}`")
    lines.append(f"- Inherited gates: {snapshot.inherited_pass}/{snapshot.inherited_total}")
    lines.append(f"- Delta gates: {snapshot.delta_pass}/{snapshot.delta_total}")
    lines.append(f"- Unit tests: {snapshot.unit_passed} passed, {snapshot.unit_failed} failed")
    lines.append("")

    lines.append("## Epic Gate Artifacts")
    for k, p in snapshot.epic_gate_files.items():
        status = "FOUND" if p else "MISSING"
        lines.append(f"- {k}: `{p}` [{status}]")
    lines.append("")

    lines.append("## Checks Summary")
    for k, v in sorted(snapshot.checks.items()):
        lines.append(f"- {k}: {'PASS' if v else 'FAIL'}")
    lines.append("")

    lines.append("## Per-Section Scores")
    lines.append("")
    lines.append("| # | Section | Std | Con | Gap |")
    lines.append("|---|---------|-----|-----|-----|")
    for s in SECTIONS:
        st = std["sections"][s]["score"]
        cv = con["sections"][s]["score"]
        gap = abs(st - cv)
        lines.append(f"| {s} | {SECTION_LABELS.get(s, '')} | {st} | {cv} | {gap} |")
    lines.append(f"| | **TOTAL** | **{std['total']}** | **{con['total']}** | **{diff['inter_pass_gap_points']}** |")
    lines.append("")

    lines.append("## Top 5 Disagreement Sections")
    lines.append("")
    lines.append("| Section | Label | Standard | Conservative | Gap |")
    lines.append("|---|---|---:|---:|---:|")
    for row in diff["top_5_disagreements"]:
        lines.append(
            f"| {row['section']} | {row['label']} | {row['standard']} | {row['conservative']} | {row['gap']} |"
        )
    lines.append("")
    lines.append("## Conservative Sections < 15")
    if diff["sections_below_15_conservative"]:
        for s in diff["sections_below_15_conservative"]:
            lines.append(f"- {s}: {SECTION_LABELS.get(s, '')}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Closed-Deduction Protection")
    lines.append(
        "- Legacy deductions for J,S,M,O,Q,W and C,D,K,L,N,T are not applied when Epic 1+2 evidence is present and passing."
    )

    # Verdict
    both_pass = diff["both_floor_78_pass"]
    no_below_15 = len(diff["sections_below_15_conservative"]) == 0
    variance_ok = diff["inter_pass_gap_points"] <= 50
    verdict = "PROMOTE" if (both_pass and no_below_15 and variance_ok) else "HOLD"

    lines.extend([
        "",
        "## Verdict",
        "",
        f"- Both >= 78%: {'PASS' if both_pass else 'FAIL'}",
        f"- No section < 15: {'PASS' if no_below_15 else 'FAIL'}",
        f"- Variance <= 50: {'PASS' if variance_ok else 'FAIL'} ({diff['inter_pass_gap_points']})",
        f"",
        f"**Verdict: {verdict}**",
    ])

    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v3.9 dual-pass reassessment (artifact-driven)")
    parser.add_argument("--root", default="S:\\", help="Project root path (default: S:\\)")
    parser.add_argument("--timestamp", default=_now_ts(), help="UTC timestamp suffix")
    parser.add_argument("--expected-unit-tests", type=int, default=523)
    parser.add_argument("--expected-inherited-gates", type=int, default=28)
    parser.add_argument("--expected-delta-gates", type=int, default=4)
    parser.add_argument("--outdir", default=None, help="Output directory (default: <root>/reports/audit)")
    args = parser.parse_args()

    root = Path(args.root)
    outdir = Path(args.outdir) if args.outdir else root / "reports" / "audit"

    snapshot = build_snapshot(
        root=root,
        expected_unit_tests=args.expected_unit_tests,
        expected_inherited_gates=args.expected_inherited_gates,
        expected_delta_gates=args.expected_delta_gates,
        ts=args.timestamp,
    )

    standard = score_run(snapshot, "standard")
    conservative = score_run(snapshot, "conservative")
    diff = build_diff(standard, conservative)

    ts = args.timestamp
    std_path = outdir / f"v3.9-artdriven-standard-{ts}.json"
    con_path = outdir / f"v3.9-artdriven-conservative-{ts}.json"
    diff_path = outdir / f"v3.9-artdriven-diff-{ts}.json"
    md_path = outdir / f"v3.9-artdriven-summary-{ts}.md"

    write_json(std_path, standard)
    write_json(con_path, conservative)
    write_json(diff_path, diff)
    write_summary_md(md_path, snapshot, standard, conservative, diff)

    print(f"[OK] standard:      {std_path}")
    print(f"[OK] conservative:  {con_path}")
    print(f"[OK] diff:          {diff_path}")
    print(f"[OK] summary:       {md_path}")
    print(
        f"[RESULT] STD {standard['total']}/500 | CON {conservative['total']}/500 | "
        f"GAP {diff['inter_pass_gap_points']} | "
        f"FLOOR {'PASS' if diff['both_floor_78_pass'] else 'FAIL'}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
