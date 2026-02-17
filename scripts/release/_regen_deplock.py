"""Regenerate dependency-lock.json from requirements-frozen.txt."""
import json
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

req_path = Path(r"S:\requirements-frozen.txt")
req_text = req_path.read_text()
req_sha = hashlib.sha256(req_text.encode()).hexdigest()

packages = []
for line in req_text.strip().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^([^=<>!]+)==(.+)$", line)
    if m:
        packages.append({"name": m.group(1).strip(), "version": m.group(2).strip()})

pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

lock = {
    "schema_version": "1.0",
    "sonia_version": "4.2.0",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "python_version": pyver,
    "requirements_sha256": req_sha,
    "package_count": len(packages),
    "packages": packages,
}

out = Path(r"S:\dependency-lock.json")
out.write_text(json.dumps(lock, indent=2))
print(f"Written {out}: {len(packages)} packages, sonia_version=4.2.0")
