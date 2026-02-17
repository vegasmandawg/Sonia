"""Update release bundle manifests after soak."""
import json, hashlib, os, subprocess
from pathlib import Path
from datetime import datetime, timezone

BUNDLE = Path(r"S:\releases\v4.2.0-rc1")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# Update evidence-manifest
evidence_files = sorted(os.listdir(BUNDLE / "evidence"))
ev_manifest = {"version": "4.2.0-rc1", "evidence_count": len(evidence_files), "files": {}}
for ef in evidence_files:
    ep = BUNDLE / "evidence" / ef
    ev_manifest["files"][ef] = {"sha256": sha256(ep), "size_bytes": os.path.getsize(ep)}
(BUNDLE / "evidence-manifest.json").write_text(json.dumps(ev_manifest, indent=2))

# Update release-manifest
try:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=r"S:\\", text=True
    ).strip()
except Exception:
    commit = "unknown"

all_files = {}
for root_dir, dirs, files in os.walk(str(BUNDLE)):
    for fname in files:
        fpath = os.path.join(root_dir, fname)
        rel = os.path.relpath(fpath, str(BUNDLE))
        if rel == "release-manifest.json":
            continue
        all_files[rel] = sha256(fpath)

manifest = {
    "sonia_version": "4.2.0-rc1",
    "tag": "v4.2.0-rc1",
    "commit": commit,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "file_count": len(all_files),
    "files": all_files,
}
(BUNDLE / "release-manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Updated manifests: {len(all_files)} files")
