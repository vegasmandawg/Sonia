"""Build evidence binder + SHA-256 manifest for v3.5 conservative gap closure."""
import json, os, sys, datetime, hashlib, glob

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Collect all audit artifacts
audit_dir = os.path.join(ROOT, "reports", "audit")
artifacts = []
for f in sorted(glob.glob(os.path.join(audit_dir, "*.json")) + glob.glob(os.path.join(audit_dir, "*.md"))):
    name = os.path.basename(f)
    size = os.path.getsize(f)
    with open(f, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    artifacts.append({"file": name, "size_bytes": size, "sha256": sha})

# Key source files
source_files = [
    "services/api-gateway/main.py",
    "services/api-gateway/clients/router_client.py",
    "services/shared/rate_limiter.py",
    "services/shared/log_redaction.py",
    "services/api-gateway/tool_policy.py",
    "services/api-gateway/turn_quality.py",
]
source_hashes = []
for rel in source_files:
    full = os.path.join(ROOT, rel)
    if os.path.isfile(full):
        with open(full, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        source_hashes.append({"file": rel, "sha256": sha})

# Unit test files
test_files = sorted(glob.glob(os.path.join(ROOT, "tests", "unit", "test_*.py")))
test_hashes = []
for f in test_files:
    with open(f, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    test_hashes.append({"file": os.path.relpath(f, ROOT), "sha256": sha})

# Gate scripts
gate_files = sorted(glob.glob(os.path.join(ROOT, "scripts", "gates", "*.py")))
gate_hashes = []
for f in gate_files:
    with open(f, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    gate_hashes.append({"file": os.path.relpath(f, ROOT), "sha256": sha})

binder = {
    "evidence_binder": "v3.5_conservative_gap_closure",
    "timestamp_utc": TS,
    "audit_artifacts": artifacts,
    "source_hashes": source_hashes,
    "test_hashes": test_hashes,
    "gate_hashes": gate_hashes,
    "total_artifacts": len(artifacts),
    "total_source_files": len(source_hashes),
    "total_test_files": len(test_hashes),
    "total_gate_scripts": len(gate_hashes),
}

out_path = os.path.join(audit_dir, f"v35-evidence-binder-{TS}.json")
with open(out_path, "w") as f:
    json.dump(binder, f, indent=2)

# SHA-256 manifest of the binder itself
with open(out_path, "rb") as fh:
    binder_sha = hashlib.sha256(fh.read()).hexdigest()

manifest_path = os.path.join(audit_dir, f"v35-evidence-manifest-{TS}.sha256")
with open(manifest_path, "w") as f:
    f.write(f"{binder_sha}  v35-evidence-binder-{TS}.json\n")
    for a in artifacts:
        f.write(f"{a['sha256']}  {a['file']}\n")

print(f"Evidence binder: {out_path}")
print(f"  Audit artifacts: {len(artifacts)}")
print(f"  Source files:    {len(source_hashes)}")
print(f"  Test files:      {len(test_hashes)}")
print(f"  Gate scripts:    {len(gate_hashes)}")
print(f"SHA-256 manifest:  {manifest_path}")
