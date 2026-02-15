"""v3.3.0 Release Hash Verification.

Verifies SHA-256 hashes of all release artifacts against the manifest.
Run from a clean shell/session (not the session that assembled them).

Usage:
    python scripts/release/verify-hashes-v33.py [--dir S:\\releases\\v3.3.0]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Verify v3.3.0 release hashes")
    parser.add_argument("--dir", default="S:\\releases\\v3.3.0",
                        help="Release directory to verify")
    args = parser.parse_args()

    release_dir = Path(args.dir)
    manifest_path = release_dir / "release-manifest.json"

    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found")
        return 1

    manifest = json.loads(manifest_path.read_text())
    expected = manifest.get("files", {})

    if not expected:
        print("ERROR: No files in manifest")
        return 1

    print(f"Verifying {len(expected)} files in {release_dir}")
    print(f"Manifest version: {manifest.get('version')}")
    print(f"Manifest tag: {manifest.get('tag', 'N/A')}")
    print()

    all_ok = True
    for filename, expected_hash in sorted(expected.items()):
        filepath = release_dir / filename
        if not filepath.exists():
            print(f"  [MISSING] {filename}")
            all_ok = False
            continue

        actual_hash = sha256_file(filepath)
        if actual_hash == expected_hash:
            print(f"  [OK]      {filename}  {actual_hash[:16]}...")
        else:
            print(f"  [FAIL]    {filename}")
            print(f"            expected: {expected_hash[:32]}...")
            print(f"            actual:   {actual_hash[:32]}...")
            all_ok = False

    print()
    if all_ok:
        print("VERDICT: ALL HASHES VERIFIED")
        return 0
    else:
        print("VERDICT: HASH VERIFICATION FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
