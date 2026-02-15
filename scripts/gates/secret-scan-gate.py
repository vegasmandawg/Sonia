#!/usr/bin/env python3
"""
Repo secret scan gate - evidence-grade secret detection.

Scans all .py files under S:\services\ for hardcoded secrets.
Outputs deterministic JSON report for audit verification.

Exit codes:
  0 - Clean (no secrets found)
  1 - Secrets detected (real credentials found)
"""

import re
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple


# Secret patterns to detect
SECRET_PATTERNS = [
    (r'sk-ant-[a-zA-Z0-9_-]{95,}', 'anthropic_api_key'),
    (r'sk-or-v1-[a-zA-Z0-9_-]{64,}', 'openrouter_api_key'),
    (r'ANTHROPIC_API_KEY\s*=\s*["\']([^"\']+)["\']', 'anthropic_key_assignment'),
    (r'Bearer\s+[A-Za-z0-9_-]{20,}', 'bearer_token'),
    (r'password\s*=\s*["\']([^"\']{8,})["\']', 'password_literal'),
    (r'secret\s*=\s*["\']([^"\']{8,})["\']', 'secret_literal'),
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', 'private_key_block'),
    (r'api[_-]?key\s*=\s*["\']([a-zA-Z0-9_-]{20,})["\']', 'api_key_assignment'),
]

# Exclude patterns for false positives
EXCLUDE_PATTERNS = [
    r'example',
    r'test',
    r'fake',
    r'xxx+',
    r'dummy',
    r'placeholder',
    r'sample',
]

# Files to exclude from scanning
EXCLUDE_FILES = [
    'log_redaction.py',
    '__pycache__',
]


def is_test_file(file_path: Path) -> bool:
    """Check if file is a test file."""
    return 'test_' in file_path.name or file_path.name.endswith('_test.py')


def is_example_value(match_text: str) -> bool:
    """Check if matched text is likely an example/test value."""
    lower_text = match_text.lower()
    return any(re.search(pattern, lower_text) for pattern in EXCLUDE_PATTERNS)


def scan_file(file_path: Path) -> List[Dict]:
    """Scan a single file for secrets."""
    findings = []

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        lines = content.split('\n')

        for pattern, pattern_name in SECRET_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line_num = content[:match.start()].count('\n') + 1
                match_text = match.group(0)

                # Extract context (surrounding line)
                context_line = lines[line_num - 1] if line_num <= len(lines) else match_text

                # Determine if this is a warning or a real finding
                is_example = is_example_value(match_text)

                findings.append({
                    'file': str(file_path),
                    'line': line_num,
                    'pattern': pattern_name,
                    'matched_text': match_text[:50] + ('...' if len(match_text) > 50 else ''),
                    'context': context_line.strip()[:100],
                    'severity': 'warning' if is_example else 'critical',
                    'is_example': is_example,
                })

    except Exception as e:
        findings.append({
            'file': str(file_path),
            'error': f"Failed to scan: {str(e)}",
            'severity': 'error',
        })

    return findings


def scan_repository(root_dir: Path) -> Tuple[List[Dict], Dict]:
    """Scan all Python files in services directory."""
    services_dir = root_dir / 'services'
    all_findings = []
    stats = {
        'files_scanned': 0,
        'files_excluded': 0,
        'critical_findings': 0,
        'warnings': 0,
        'errors': 0,
    }

    if not services_dir.exists():
        return all_findings, stats

    for py_file in services_dir.rglob('*.py'):
        # Exclude test files and specific files
        if is_test_file(py_file):
            stats['files_excluded'] += 1
            continue

        if any(exclude in str(py_file) for exclude in EXCLUDE_FILES):
            stats['files_excluded'] += 1
            continue

        stats['files_scanned'] += 1
        findings = scan_file(py_file)

        for finding in findings:
            severity = finding.get('severity', 'unknown')
            if severity == 'critical':
                stats['critical_findings'] += 1
            elif severity == 'warning':
                stats['warnings'] += 1
            elif severity == 'error':
                stats['errors'] += 1

        all_findings.extend(findings)

    return all_findings, stats


def generate_report(findings: List[Dict], stats: Dict, output_path: Path) -> None:
    """Generate JSON audit report."""
    timestamp = datetime.now(timezone.utc).isoformat()

    report = {
        'scan_timestamp': timestamp,
        'gate_name': 'secret-scan-gate',
        'gate_version': '1.0.0',
        'statistics': stats,
        'findings': findings,
        'verdict': {
            'passed': stats['critical_findings'] == 0,
            'gate_status': 'PASS' if stats['critical_findings'] == 0 else 'FAIL',
            'exit_code': 0 if stats['critical_findings'] == 0 else 1,
        },
        'evidence': {
            'scan_root': 'S:\\services',
            'patterns_used': [name for _, name in SECRET_PATTERNS],
            'exclusions': EXCLUDE_FILES,
        }
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')


def main() -> int:
    """Main execution."""
    repo_root = Path('S:/')
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    report_path = repo_root / 'reports' / 'audit' / f'secret-scan-{timestamp}.json'

    print("=== SONIA Secret Scan Gate ===")
    print(f"Scanning: {repo_root / 'services'}")
    print()

    findings, stats = scan_repository(repo_root)
    generate_report(findings, stats, report_path)

    print(f"Files scanned: {stats['files_scanned']}")
    print(f"Files excluded: {stats['files_excluded']}")
    print(f"Critical findings: {stats['critical_findings']}")
    print(f"Warnings (test/example values): {stats['warnings']}")
    print(f"Errors: {stats['errors']}")
    print()
    print(f"Report: {report_path}")
    print()

    if stats['critical_findings'] > 0:
        print("FAIL: Hardcoded secrets detected!")
        print()
        print("Critical findings:")
        for finding in findings:
            if finding.get('severity') == 'critical':
                print(f"  {finding['file']}:{finding.get('line', '?')}")
                print(f"    Pattern: {finding['pattern']}")
                print(f"    Context: {finding.get('context', 'N/A')}")
        return 1

    print("PASS: No hardcoded secrets detected.")
    return 0


if __name__ == '__main__':
    exit(main())
