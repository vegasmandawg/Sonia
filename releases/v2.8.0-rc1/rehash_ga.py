"""Rehash the GA manifest artifacts."""
import os, json, hashlib

GA_DIR = r"S:\releases\v2.8.0"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

manifest_path = os.path.join(GA_DIR, "release_manifest.json")
with open(manifest_path) as f:
    manifest = json.load(f)

for artifact_name in list(manifest["artifacts"].keys()):
    path = os.path.join(GA_DIR, artifact_name)
    if os.path.exists(path):
        manifest["artifacts"][artifact_name] = {
            "sha256": sha256_file(path),
            "size_bytes": os.path.getsize(path),
        }
        print(f"  {artifact_name}: {manifest['artifacts'][artifact_name]['size_bytes']} bytes")

with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
print(f"\nRehashed {len(manifest['artifacts'])} artifacts")
