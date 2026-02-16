#!/usr/bin/env python3
"""
v4.1 Cross-Epic Evidence Integrity Gate
=========================================
Verifies structural evidence artifacts exist and are well-formed.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path("S:/")

CHECKS = [
    "scope_lock_present",
    "epic_map_present",
    "promotion_criteria_present",
    "scorer_contract_present",
    "non_goals_present",
]

def main():
    results = []

    # Check 1: Scope lock
    ok = (ROOT / "docs" / "governance" / "V4_1_SCOPE_LOCK.md").exists()
    results.append(("scope_lock_present", ok))

    # Check 2: Epic map
    path = ROOT / "docs" / "governance" / "V4_1_EPIC_MAP.json"
    ok = False
    if path.exists():
        try:
            data = json.loads(path.read_text())
            ok = "epics" in data and len(data["epics"]) == 3
        except Exception:
            pass
    results.append(("epic_map_present", ok))

    # Check 3: Promotion criteria
    path = ROOT / "docs" / "governance" / "V4_1_PROMOTION_CRITERIA.json"
    ok = False
    if path.exists():
        try:
            data = json.loads(path.read_text())
            ok = "gates" in data and "tests" in data and "dual_pass" in data
        except Exception:
            pass
    results.append(("promotion_criteria_present", ok))

    # Check 4: Scorer contract
    ok = (ROOT / "docs" / "governance" / "SCORER_CONTRACT_V41.md").exists()
    results.append(("scorer_contract_present", ok))

    # Check 5: Non-goals
    path = ROOT / "docs" / "governance" / "V4_1_NON_GOALS.json"
    ok = False
    if path.exists():
        try:
            data = json.loads(path.read_text())
            ok = "non_goals" in data and len(data["non_goals"]) >= 5
        except Exception:
            pass
    results.append(("non_goals_present", ok))

    passed = 0
    for name, ok in results:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}")
        if ok:
            passed += 1

    total = len(results)
    print(f"\n{passed}/{total} checks PASS")
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
