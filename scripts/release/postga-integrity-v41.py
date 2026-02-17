"""Post-GA integrity verification for v4.1.0."""
import json, subprocess, datetime, os

TS = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
CWD = "S:\\"
checks = []

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CWD)
    return r.stdout.strip(), r.returncode

# 1. v4.1.0-rc1 resolves
out, rc = run(["git", "rev-parse", "v4.1.0-rc1"])
checks.append({"check": "v4.1.0-rc1 resolves", "ok": rc == 0, "detail": out[:12]})

# 2. v4.1.0 resolves
out, rc = run(["git", "rev-parse", "v4.1.0"])
checks.append({"check": "v4.1.0 resolves", "ok": rc == 0, "detail": out[:12]})

# 3. main contains GA merge
out, rc = run(["git", "log", "main", "--oneline", "-5"])
has_ga = "v4.1.0 GA release" in out
has_closure = "closure" in out.lower()
checks.append({"check": "main has GA merge", "ok": has_ga, "detail": out.split("\n")[0]})
checks.append({"check": "main has closure docs", "ok": has_closure, "detail": "found" if has_closure else "missing"})

# 4. release/v4.1.x exists
out, rc = run(["git", "rev-parse", "--verify", "release/v4.1.x"])
checks.append({"check": "release/v4.1.x exists", "ok": rc == 0, "detail": out[:12]})

# 5. v4.2-dev exists
out, rc = run(["git", "rev-parse", "--verify", "v4.2-dev"])
checks.append({"check": "v4.2-dev exists", "ok": rc == 0, "detail": out[:12]})

# 6. v4.2-dev tracks origin
out, rc = run(["git", "config", "branch.v4.2-dev.remote"])
tracks = out.strip() == "origin"
if not tracks:
    subprocess.run(["git", "branch", "--set-upstream-to=origin/v4.2-dev", "v4.2-dev"],
                    cwd=CWD, capture_output=True)
    out2, _ = run(["git", "config", "branch.v4.2-dev.remote"])
    tracks = out2.strip() == "origin"
checks.append({"check": "v4.2-dev tracks origin", "ok": tracks, "detail": "origin" if tracks else out})

# 7. Release bundle exists
bundle = os.path.exists(os.path.join("S:", "releases", "v4.1.0", "release-manifest.json"))
checks.append({"check": "Release bundle present", "ok": bundle, "detail": "S:\\releases\\v4.1.0"})

# 8. Evidence frozen
evidence = os.path.exists(os.path.join("S:", "reports", "audit", "v4.1-evidence-frozen", "evidence-manifest.json"))
checks.append({"check": "Evidence frozen", "ok": evidence, "detail": "manifest found" if evidence else "missing"})

all_ok = all(c["ok"] for c in checks)
report = {
    "version": "4.1.0",
    "type": "post-ga-integrity",
    "timestamp": TS,
    "checks": checks,
    "passed": sum(1 for c in checks if c["ok"]),
    "total": len(checks),
    "verdict": "PASS" if all_ok else "FAIL",
}

path = os.path.join("S:", "reports", "audit", f"v4.1-postga-integrity-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

for c in checks:
    status = "PASS" if c["ok"] else "FAIL"
    print(f"  [{status}] {c['check']}: {c['detail']}")
print(f"\nPost-GA integrity: {report['verdict']} ({report['passed']}/{report['total']})")
print(f"Artifact: {path}")
