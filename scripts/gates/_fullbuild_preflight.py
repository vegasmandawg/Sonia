"""Phase 0: Root precheck + preflight artifact."""
import json, datetime, subprocess, sys, os

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = r"S:\\"

os.chdir(ROOT)

commit_full = subprocess.run(["git","rev-parse","HEAD"], capture_output=True, text=True).stdout.strip()
branch = subprocess.run(["git","branch","--show-current"], capture_output=True, text=True).stdout.strip()
tag = subprocess.run(["git","describe","--tags","--always"], capture_output=True, text=True).stdout.strip()

dirs_required = ["services","scripts","tests","reports","docs","config"]
dirs_present = [d for d in dirs_required if os.path.isdir(d)]
dirs_missing = [d for d in dirs_required if not os.path.isdir(d)]
forbidden = os.path.isdir(os.path.join(ROOT, "Sonia"))

preflight = {
    "timestamp_utc": TS,
    "root": "S:\\",
    "branch": branch,
    "commit": commit_full,
    "tag": tag,
    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    "dirs_required": dirs_required,
    "dirs_present": dirs_present,
    "dirs_missing": dirs_missing,
    "forbidden_path_check": "FAIL" if forbidden else "PASS",
    "root_valid": len(dirs_missing) == 0 and not forbidden
}

os.makedirs("reports/audit", exist_ok=True)
path = f"reports/audit/fullbuild-preflight-{TS}.json"
with open(path, "w") as f:
    json.dump(preflight, f, indent=2)
print(json.dumps(preflight, indent=2))
print(f"\nArtifact: {path}")
