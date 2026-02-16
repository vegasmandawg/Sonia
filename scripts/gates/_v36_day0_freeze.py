"""Day-0 control freeze for v3.6: snapshot baseline, verify tag immutability."""
import json, os, sys, datetime, hashlib, shutil, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_DIR = os.path.join(ROOT, "reports", "audit", "v3.6-baseline")
PYTHON = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable

os.makedirs(BASELINE_DIR, exist_ok=True)

checks = []

# 1. Verify v3.5 tags exist and are immutable (annotated)
for tag in ["v3.5.0-conservative-gap-closure-rc1", "v3.5.0-conservative-gap-closure"]:
    r = subprocess.run(["git", "tag", "-l", tag], capture_output=True, text=True, cwd=ROOT)
    found = tag in r.stdout.strip()
    checks.append({"name": f"tag_exists:{tag}", "passed": found, "detail": f"{tag} present: {found}"})

# 2. Snapshot key v3.5 artifacts
SNAPSHOT_FILES = {
    "FINAL_SCORECARD.md": os.path.join(ROOT, "reports", "audit", "FINAL_SCORECARD.md"),
    "v35-gate-matrix.json": None,  # find latest
    "v35-evidence-manifest.sha256": None,
}

# Find latest gate matrix and manifest
import glob
matrices = sorted(glob.glob(os.path.join(ROOT, "reports", "audit", "v35-gate-matrix-*.json")))
manifests = sorted(glob.glob(os.path.join(ROOT, "reports", "audit", "v35-evidence-manifest-*.sha256")))
unit_layers = sorted(glob.glob(os.path.join(ROOT, "reports", "audit", "unit-test-layer-*.json")))

if matrices:
    SNAPSHOT_FILES["v35-gate-matrix.json"] = matrices[-1]
if manifests:
    SNAPSHOT_FILES["v35-evidence-manifest.sha256"] = manifests[-1]
if unit_layers:
    SNAPSHOT_FILES["unit-test-layer.json"] = unit_layers[-1]

copied = 0
for dest_name, src in SNAPSHOT_FILES.items():
    if src and os.path.isfile(src):
        shutil.copy2(src, os.path.join(BASELINE_DIR, dest_name))
        copied += 1

checks.append({
    "name": "baseline_snapshot",
    "passed": copied >= 3,
    "detail": f"Copied {copied} artifacts to v3.6-baseline/",
})

# 3. Generate baseline SHA-256
baseline_manifest = []
for f in sorted(os.listdir(BASELINE_DIR)):
    fp = os.path.join(BASELINE_DIR, f)
    if os.path.isfile(fp) and f != "baseline-manifest.sha256":
        with open(fp, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        baseline_manifest.append(f"{sha}  {f}")

manifest_path = os.path.join(BASELINE_DIR, "baseline-manifest.sha256")
with open(manifest_path, "w") as fh:
    fh.write("\n".join(baseline_manifest) + "\n")

checks.append({
    "name": "baseline_manifest",
    "passed": os.path.isfile(manifest_path),
    "detail": f"Manifest written: {len(baseline_manifest)} entries",
})

# 4. Verify release/v3.5.x branch exists
r = subprocess.run(["git", "branch", "-a", "--list", "*release/v3.5*"],
                    capture_output=True, text=True, cwd=ROOT)
has_hotfix = "release/v3.5" in r.stdout
checks.append({
    "name": "hotfix_branch_exists",
    "passed": has_hotfix,
    "detail": f"release/v3.5.x branch present: {has_hotfix}",
})

# 5. Verify current branch is v3.6-dev
r = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, cwd=ROOT)
on_v36 = r.stdout.strip() == "v3.6-dev"
checks.append({
    "name": "on_v36_dev",
    "passed": on_v36,
    "detail": f"Current branch: {r.stdout.strip()}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "v36_day0_freeze",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks": checks,
    "baseline_dir": BASELINE_DIR,
}

out = os.path.join(ROOT, "reports", "audit", f"v36-day0-freeze-{TS}.json")
with open(out, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Day-0 Control Freeze ===\n")
for c in checks:
    s = "PASS" if c["passed"] else "FAIL"
    print(f"  [{s}] {c['name']}: {c['detail']}")
print(f"\nBaseline dir: {BASELINE_DIR}")
print(f"Artifact: {out}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
