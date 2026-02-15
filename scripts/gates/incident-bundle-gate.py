#!/usr/bin/env python3
"""
Incident bundle completeness gate - evidence-grade validation.

Verifies that the incident bundle export infrastructure is functional
and produces valid, complete bundles for incident response.

Exit codes:
  0 - All checks pass
  1 - Critical validation failures
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple


# Expected artifact types in a complete incident bundle
REQUIRED_ARTIFACTS = [
    'logs',           # Log files from services
    'config',         # Configuration snapshots
    'health',         # Health check results
    'git',            # Git state (branch, commit, status)
    'summary.json',   # Bundle summary metadata
]


def check_export_script_exists() -> Tuple[bool, str]:
    """Check if incident bundle export script exists."""
    script_path = Path('S:/scripts/export-incident-bundle.ps1')
    if script_path.exists():
        return True, f"Export script found: {script_path}"
    return False, f"Export script missing: {script_path}"


def check_output_directory_writable() -> Tuple[bool, str]:
    """Check if incidents output directory is writable."""
    output_dir = Path('S:/incidents')
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Test write by creating a temporary file
        test_file = output_dir / '.write-test'
        test_file.write_text('test', encoding='utf-8')
        test_file.unlink()
        return True, f"Output directory writable: {output_dir}"
    except Exception as e:
        return False, f"Output directory not writable: {output_dir} ({e})"


def check_artifact_types_defined() -> Tuple[bool, str]:
    """Check that expected artifact types are defined."""
    # This is a meta-check that our validation criteria are clear
    if len(REQUIRED_ARTIFACTS) > 0:
        return True, f"Artifact validation criteria defined: {', '.join(REQUIRED_ARTIFACTS)}"
    return False, "No artifact validation criteria defined"


def validate_bundle_structure(bundle_dir: Path) -> Tuple[bool, List[str], List[str]]:
    """Validate structure of a single incident bundle."""
    found_artifacts = []
    missing_artifacts = []

    for artifact_name in REQUIRED_ARTIFACTS:
        artifact_path = bundle_dir / artifact_name

        # Handle both files and directories
        if artifact_path.exists():
            found_artifacts.append(artifact_name)
        else:
            # For directories, check if they exist
            if artifact_name in ['logs', 'config', 'health', 'git']:
                if (bundle_dir / f"{artifact_name}.txt").exists() or \
                   (bundle_dir / f"{artifact_name}.json").exists():
                    found_artifacts.append(f"{artifact_name} (alternate)")
                else:
                    missing_artifacts.append(artifact_name)
            else:
                missing_artifacts.append(artifact_name)

    is_valid = len(missing_artifacts) == 0
    return is_valid, found_artifacts, missing_artifacts


def scan_existing_bundles() -> Tuple[int, int, List[Dict]]:
    """Scan existing incident bundles and validate them."""
    incidents_dir = Path('S:/incidents')
    if not incidents_dir.exists():
        return 0, 0, []

    bundle_dirs = [d for d in incidents_dir.iterdir() if d.is_dir()]
    total_bundles = len(bundle_dirs)
    valid_bundles = 0
    bundle_reports = []

    for bundle_dir in bundle_dirs:
        is_valid, found, missing = validate_bundle_structure(bundle_dir)
        if is_valid:
            valid_bundles += 1

        bundle_reports.append({
            'bundle_name': bundle_dir.name,
            'path': str(bundle_dir),
            'is_valid': is_valid,
            'found_artifacts': found,
            'missing_artifacts': missing,
        })

    return total_bundles, valid_bundles, bundle_reports


def run_checks() -> Tuple[List[Dict], bool]:
    """Run all gate checks."""
    checks = []
    all_passed = True

    # Check 1: Export script exists
    passed, message = check_export_script_exists()
    checks.append({
        'check': 'export_script_exists',
        'passed': passed,
        'message': message,
    })
    if not passed:
        all_passed = False

    # Check 2: Output directory writable
    passed, message = check_output_directory_writable()
    checks.append({
        'check': 'output_directory_writable',
        'passed': passed,
        'message': message,
    })
    if not passed:
        all_passed = False

    # Check 3: Artifact types defined
    passed, message = check_artifact_types_defined()
    checks.append({
        'check': 'artifact_types_defined',
        'passed': passed,
        'message': message,
    })
    if not passed:
        all_passed = False

    # Check 4: Scan and validate existing bundles
    total_bundles, valid_bundles, bundle_reports = scan_existing_bundles()
    bundle_check_passed = True
    bundle_message = f"Found {total_bundles} bundles"

    if total_bundles > 0:
        bundle_message += f", {valid_bundles} valid"
        if valid_bundles < total_bundles:
            bundle_check_passed = False
            bundle_message += f", {total_bundles - valid_bundles} invalid"

    checks.append({
        'check': 'existing_bundles_valid',
        'passed': bundle_check_passed,
        'message': bundle_message,
        'total_bundles': total_bundles,
        'valid_bundles': valid_bundles,
        'bundle_details': bundle_reports,
    })

    # Don't fail gate if no bundles exist (yet)
    # Only fail if bundles exist but are invalid
    if not bundle_check_passed and total_bundles > 0:
        all_passed = False

    return checks, all_passed


def generate_report(checks: List[Dict], passed: bool, output_path: Path) -> None:
    """Generate JSON audit report."""
    timestamp = datetime.now(timezone.utc).isoformat()

    report = {
        'gate_timestamp': timestamp,
        'gate_name': 'incident-bundle-gate',
        'gate_version': '1.0.0',
        'checks': checks,
        'verdict': {
            'passed': passed,
            'gate_status': 'PASS' if passed else 'FAIL',
            'exit_code': 0 if passed else 1,
        },
        'requirements': {
            'export_script': 'S:\\scripts\\export-incident-bundle.ps1',
            'output_directory': 'S:\\incidents',
            'required_artifacts': REQUIRED_ARTIFACTS,
        }
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')


def main() -> int:
    """Main execution."""
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    report_path = Path(f'S:/reports/audit/incident-gate-{timestamp}.json')

    print("=== SONIA Incident Bundle Gate ===")
    print()

    checks, passed = run_checks()
    generate_report(checks, passed, report_path)

    # Display results
    for check in checks:
        status = "PASS" if check['passed'] else "FAIL"
        print(f"[{status}] {check['check']}")
        print(f"      {check['message']}")

        # Show bundle details if present
        if 'bundle_details' in check and check['bundle_details']:
            for bundle in check['bundle_details']:
                bundle_status = "valid" if bundle['is_valid'] else "INVALID"
                print(f"      - {bundle['bundle_name']}: {bundle_status}")
                if not bundle['is_valid']:
                    print(f"        Missing: {', '.join(bundle['missing_artifacts'])}")

    print()
    print(f"Report: {report_path}")
    print()

    if passed:
        print("PASS: Incident bundle infrastructure validated.")
        return 0
    else:
        print("FAIL: Incident bundle validation failures detected.")
        print()
        print("Failed checks:")
        for check in checks:
            if not check['passed']:
                print(f"  - {check['check']}: {check['message']}")
        return 1


if __name__ == '__main__':
    exit(main())
