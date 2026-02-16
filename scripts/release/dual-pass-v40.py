#!/usr/bin/env python3
"""
v4.0 Dual-Pass Reassessment Runner
====================================
- Contract-locked A..Y scoring (0..20 per section, total 500)
- Standard + Conservative scorers
- Evidence-driven deductions only
- Closed-deduction sections protected when all 3 Epic gates pass

Adapted from v3.9 dual-pass for gate-matrix schema v7.0 (37 gates).
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

SECTIONS = [chr(c) for c in range(ord("A"), ord("Y") + 1)]

# Sections with closed deductions when all 3 epic gates pass
CLOSED_DEDUCTION_SECTIONS = {
    "C", "D", "E", "G", "H", "J", "K", "L", "M", "N",
    "O", "Q", "R", "S", "T", "U", "V", "W", "X", "Y",
}

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
    evidence_pass: int
    evidence_total: int
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
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict in {"pass", "passed", "promote", "ok"}:
        return True
    if verdict in {"fail", "failed", "hold"}:
        return False
    checks = data.get("checks")
    if isinstance(checks, list) and checks:
        statuses = [str(c.get("status", "")).strip().lower() for c in checks if isinstance(c, dict)]
        if statuses and all(s in {"pass", "passed", "ok"} for s in statuses):
            return True
    passed = data.get("passed") or data.get("checks_passed")
    total = data.get("total") or data.get("checks_total")
    if isinstance(passed, (int, float)) and isinstance(total, (int, float)) and int(total) > 0:
        return int(passed) == int(total)
    return False


def _parse_gate_matrix(data: Dict[str, Any]) -> Tuple[int, int, int, int, int, int]:
    """
    Returns: inherited_pass, inherited_total, delta_pass, delta_total, evidence_pass, evidence_total
    Supports gate-matrix schema v7.0.
    """
    inherited_pass = inherited_total = 0
    delta_pass = delta_total = 0
    evidence_pass = evidence_total = 0

    if not data:
        return inherited_pass, inherited_total, delta_pass, delta_total, evidence_pass, evidence_total

    gates = data.get("gates")
    if isinstance(gates, list):
        for g in gates:
            if not isinstance(g, dict):
                continue
            is_pass = bool(g.get("passed", False))
            category = str(g.get("category", "")).strip().lower()
            gate_class = str(g.get("class", "")).strip().upper()

            if category == "test_floor":
                continue
            elif gate_class == "C" or category == "evidence":
                evidence_total += 1
                if is_pass:
                    evidence_pass += 1
            elif gate_class == "B" or category == "delta":
                delta_total += 1
                if is_pass:
                    delta_pass += 1
            else:
                inherited_total += 1
                if is_pass:
                    inherited_pass += 1

    # Fallback: use top-level counts
    if inherited_total == 0 and delta_total == 0:
        total = _safe_int(data.get("gates_total", 0))
        passed = _safe_int(data.get("gates_passed", 0))
        class_a = _safe_int(data.get("class_a_count", 0))
        class_b = _safe_int(data.get("class_b_count", 0))
        class_c = _safe_int(data.get("class_c_count", 0))

        inherited_total = class_a
        delta_total = class_b
        evidence_total = class_c
        if passed == total:
            inherited_pass = inherited_total
            delta_pass = delta_total
            evidence_pass = evidence_total

    return inherited_pass, inherited_total, delta_pass, delta_total, evidence_pass, evidence_total


def _parse_unit_from_matrix(data: Dict[str, Any]) -> Tuple[int, int]:
    if not data:
        return 0, 0
    p = _safe_int(data.get("unit_tests_passed", 0))
    f = _safe_int(data.get("unit_tests_failed", 0))
    return p, f


def build_snapshot(root: Path, expected_unit_tests: int, expected_inherited_gates: int,
                   expected_delta_gates: int, ts: str) -> EvidenceSnapshot:
    reports = root / "reports" / "audit"
    docs = root / "docs"

    scorer_contract = docs / "SCORER_CONTRACT.md"
    scope_lock = docs / "V4_0_SCOPE_LOCK.md"

    # Find the latest v4.0 gate matrix
    gate_matrix = _latest_file(str(reports / "v4.0-baseline" / "gate-matrix-v40*.json"))

    epic_gate_files = {
        "e1_session_memory": _latest_file(str(reports / "v40-e1-gate-*.json")),
        "e2_recovery_lineage": _latest_file(str(reports / "v40-e2-gate-*.json")),
        "e3_runtime_qos": _latest_file(str(reports / "v40-e3-gate-*.json")),
    }

    # Also check v3.9 epic gates (inherited evidence)
    inherited_epic_files = {
        "coverage_completeness": _latest_file(str(reports / "coverage-completeness-*.json")),
        "data_durability": _latest_file(str(reports / "data-durability-*.json")),
        "deduction_sweep": _latest_file(str(reports / "deduction-sweep-*.json")),
        "test_strategy": _latest_file(str(reports / "test-strategy-*.json")),
    }

    baseline_manifest = _latest_file(str(reports / "v4.0-baseline" / "*manifest*"))
    release_manifest = _latest_file(str(root / "releases" / "v4.0.0" / "*manifest*"))

    gate_data = _read_json(gate_matrix)
    inh_p, inh_t, dlt_p, dlt_t, ev_p, ev_t = _parse_gate_matrix(gate_data)
    unit_p, unit_f = _parse_unit_from_matrix(gate_data)

    # Epic gate pass booleans
    epic_pass = {k: _json_verdict_pass(_read_json(v)) for k, v in epic_gate_files.items()}
    inherited_pass_map = {k: _json_verdict_pass(_read_json(v)) for k, v in inherited_epic_files.items()}

    checks = {
        "scorer_contract_present": scorer_contract.exists(),
        "scope_lock_present": scope_lock.exists(),
        "baseline_manifest_present": baseline_manifest is not None,
        "release_manifest_present": release_manifest is not None,
        "gate_matrix_present": gate_matrix is not None,
        "inherited_floor_pass": (inh_t >= expected_inherited_gates and inh_p == inh_t),
        "delta_gates_pass": (dlt_t >= expected_delta_gates and dlt_p == dlt_t),
        "evidence_gate_pass": (ev_t >= 1 and ev_p == ev_t),
        "unit_floor_pass": (unit_p >= expected_unit_tests and unit_f == 0),
        # v4.0 epic gates
        "e1_pass": epic_pass.get("e1_session_memory", False),
        "e2_pass": epic_pass.get("e2_recovery_lineage", False),
        "e3_pass": epic_pass.get("e3_runtime_qos", False),
        "all_epics_pass": all(epic_pass.values()) and len(epic_pass) == 3,
        # v3.9 inherited epic gates
        "coverage_completeness_pass": inherited_pass_map.get("coverage_completeness", False),
        "data_durability_pass": inherited_pass_map.get("data_durability", False),
        "deduction_sweep_pass": inherited_pass_map.get("deduction_sweep", False),
        "test_strategy_pass": inherited_pass_map.get("test_strategy", False),
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
        epic_gate_files={**epic_gate_files, **inherited_epic_files},
        baseline_manifest_file=baseline_manifest,
        release_manifest_file=release_manifest,
        inherited_pass=inh_p,
        inherited_total=inh_t,
        delta_pass=dlt_p,
        delta_total=dlt_t,
        evidence_pass=ev_p,
        evidence_total=ev_t,
        unit_passed=unit_p,
        unit_failed=unit_f,
        checks=checks,
    )


def _section_requirements() -> Dict[str, Dict[str, List[str]]]:
    return {
        "A": {"required": ["scorer_contract_present", "scope_lock_present"], "bonus": ["baseline_manifest_present"]},
        "B": {"required": ["gate_matrix_present"], "bonus": ["release_manifest_present"]},
        "C": {"required": ["e3_pass", "deduction_sweep_pass"], "bonus": ["unit_floor_pass"]},
        "D": {"required": ["e3_pass", "deduction_sweep_pass"], "bonus": ["scope_lock_present"]},
        "E": {"required": ["inherited_floor_pass", "e3_pass"], "bonus": ["unit_floor_pass"]},
        "F": {"required": ["inherited_floor_pass"], "bonus": ["gate_matrix_present"]},
        "G": {"required": ["inherited_floor_pass", "e2_pass"], "bonus": ["unit_floor_pass"]},
        "H": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "I": {"required": ["inherited_floor_pass"], "bonus": ["unit_floor_pass"]},
        "J": {"required": ["e1_pass", "data_durability_pass"], "bonus": ["unit_floor_pass"]},
        "K": {"required": ["e3_pass", "deduction_sweep_pass"], "bonus": ["unit_floor_pass"]},
        "L": {"required": ["e3_pass", "test_strategy_pass"], "bonus": ["gate_matrix_present"]},
        "M": {"required": ["e1_pass", "data_durability_pass"], "bonus": ["coverage_completeness_pass"]},
        "N": {"required": ["e2_pass", "deduction_sweep_pass"], "bonus": ["inherited_floor_pass"]},
        "O": {"required": ["e3_pass", "coverage_completeness_pass"], "bonus": ["inherited_floor_pass"]},
        "P": {"required": ["inherited_floor_pass"], "bonus": ["release_manifest_present"]},
        "Q": {"required": ["e1_pass", "coverage_completeness_pass"], "bonus": ["inherited_floor_pass"]},
        "R": {"required": ["e3_pass", "unit_floor_pass"], "bonus": ["test_strategy_pass"]},
        "S": {"required": ["e3_pass", "test_strategy_pass"], "bonus": ["gate_matrix_present"]},
        "T": {"required": ["deduction_sweep_pass", "test_strategy_pass"], "bonus": ["release_manifest_present"]},
        "U": {"required": ["e2_pass", "data_durability_pass"], "bonus": ["baseline_manifest_present"]},
        "V": {"required": ["e2_pass", "inherited_floor_pass"], "bonus": ["data_durability_pass"]},
        "W": {"required": ["e3_pass", "scope_lock_present"], "bonus": ["baseline_manifest_present"]},
        "X": {"required": ["e3_pass", "unit_floor_pass"], "bonus": ["gate_matrix_present"]},
        "Y": {"required": ["inherited_floor_pass", "delta_gates_pass", "evidence_gate_pass", "unit_floor_pass"], "bonus": ["all_epics_pass"]},
    }


def score_run(snapshot: EvidenceSnapshot, scorer_type: str) -> Dict[str, Any]:
    if scorer_type not in {"standard", "conservative"}:
        raise ValueError("scorer_type must be standard or conservative")

    req = _section_requirements()
    req_penalty = 2 if scorer_type == "standard" else 3
    bonus_penalty = 1

    sections: Dict[str, Dict[str, Any]] = {}
    total = 0

    for s in SECTIONS:
        required_checks = req[s]["required"]
        bonus_checks = req[s]["bonus"]

        missing_required = [c for c in required_checks if not snapshot.checks.get(c, False)]
        missing_bonus = [c for c in bonus_checks if not snapshot.checks.get(c, False)]

        score = 20 - req_penalty * len(missing_required) - bonus_penalty * len(missing_bonus)

        # Closed-deduction protection
        if s in CLOSED_DEDUCTION_SECTIONS and snapshot.checks.get("all_epics_pass", False):
            pass  # no extra deductions beyond concrete evidence misses

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
            reason_parts.append(f"missing required: {', '.join(missing_required)}")
        if missing_bonus:
            reason_parts.append(f"missing bonus: {', '.join(missing_bonus)}")
        if not reason_parts:
            reason_parts.append("all evidence checks satisfied")

        sections[s] = {
            "label": SECTION_LABELS.get(s, ""),
            "score": score,
            "max": 20,
            "reason": "; ".join(reason_parts),
            "evidence": sorted(set(evidence_refs)),
        }

    percent = round((total / 500) * 100, 1)

    return {
        "run_id": f"v4.0-dual-pass-{snapshot.timestamp}",
        "scorer_type": scorer_type,
        "version": "4.0.0-dev",
        "scale": "0-20 per section",
        "sections": sections,
        "total": total,
        "percent": percent,
        "floor_98_pass": total >= 490,
        "notes": [
            "Scoring uses v4.0 gate-matrix schema v7.0 evidence",
            "3 epic gates (E1+E2+E3) contribute to section requirements",
            "Closed deduction sections protected when all 3 epic gates pass",
            f"Unit floor: {snapshot.expected_unit_tests}, observed: {snapshot.unit_passed}/{snapshot.unit_passed + snapshot.unit_failed}",
            f"Inherited gates: {snapshot.inherited_pass}/{snapshot.inherited_total}, "
            f"delta gates: {snapshot.delta_pass}/{snapshot.delta_total}, "
            f"evidence gates: {snapshot.evidence_pass}/{snapshot.evidence_total}",
        ],
    }


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
        "version": "4.0.0-dev",
        "standard_total": standard["total"],
        "conservative_total": conservative["total"],
        "mean_total": mean_score,
        "inter_pass_gap_points": total_gap,
        "inter_pass_gap_pct": round((total_gap / 500) * 100, 1),
        "dispersion_from_mean_points": round(total_gap / 2.0, 1),
        "dispersion_from_mean_pct": round(((total_gap / 2.0) / 500) * 100, 1),
        "both_floor_98_pass": bool(standard["floor_98_pass"] and conservative["floor_98_pass"]),
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


def write_summary_md(path: Path, snapshot: EvidenceSnapshot, std: Dict[str, Any],
                     con: Dict[str, Any], diff: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v4.0 Dual-Pass Reassessment Summary",
        "",
        f"- Timestamp (UTC): {snapshot.timestamp}",
        f"- Version: 4.0.0-dev",
        f"- Standard: {std['total']}/500 ({std['percent']}%)",
        f"- Conservative: {con['total']}/500 ({con['percent']}%)",
        f"- Mean: {diff['mean_total']}/500 ({round((diff['mean_total']/500)*100,1)}%)",
        f"- Inter-pass gap: {diff['inter_pass_gap_points']} points ({diff['inter_pass_gap_pct']}%)",
        f"- Floor (>=490/500 both): {'PASS' if diff['both_floor_98_pass'] else 'FAIL'}",
        "",
        "## Evidence Snapshot",
        f"- Gate matrix: `{snapshot.gate_matrix_file}`",
        f"- Inherited gates: {snapshot.inherited_pass}/{snapshot.inherited_total}",
        f"- Delta gates: {snapshot.delta_pass}/{snapshot.delta_total}",
        f"- Evidence gates: {snapshot.evidence_pass}/{snapshot.evidence_total}",
        f"- Unit tests: {snapshot.unit_passed} passed, {snapshot.unit_failed} failed",
        "",
        "## Epic Gate Artifacts",
    ]
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

    # Verdict
    both_pass = diff["both_floor_98_pass"]
    no_below_15 = len(diff["sections_below_15_conservative"]) == 0
    variance_ok = diff["inter_pass_gap_points"] <= 30
    verdict = "PROMOTE" if (both_pass and no_below_15 and variance_ok) else "HOLD"

    lines.extend([
        "## Verdict",
        "",
        f"- Both >= 490/500: {'PASS' if both_pass else 'FAIL'}",
        f"- No section < 15: {'PASS' if no_below_15 else 'FAIL'}",
        f"- Variance <= 30: {'PASS' if variance_ok else 'FAIL'} ({diff['inter_pass_gap_points']})",
        "",
        f"**Verdict: {verdict}**",
    ])

    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run v4.0 dual-pass reassessment")
    parser.add_argument("--root", default="S:\\", help="Project root path")
    parser.add_argument("--timestamp", default=_now_ts(), help="UTC timestamp suffix")
    parser.add_argument("--expected-unit-tests", type=int, default=613)
    parser.add_argument("--expected-inherited-gates", type=int, default=32)
    parser.add_argument("--expected-delta-gates", type=int, default=3)
    parser.add_argument("--outdir", default=None, help="Output directory")
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
    std_path = outdir / f"v4.0-dualpass-standard-{ts}.json"
    con_path = outdir / f"v4.0-dualpass-conservative-{ts}.json"
    diff_path = outdir / f"v4.0-dualpass-diff-{ts}.json"
    md_path = outdir / f"v4.0-dualpass-summary-{ts}.md"

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
        f"FLOOR {'PASS' if diff['both_floor_98_pass'] else 'FAIL'}"
    )


if __name__ == "__main__":
    exit(main())
