import json, sys, glob
# Sort by modification time to get latest
import os
files = sorted(glob.glob(r"S:\reports\audit\v4.2-baseline\gate-matrix-v42-2*.json"), key=os.path.getmtime)
report = json.load(open(files[-1]))
print(f"Report: {files[-1]}")
print(f"Verdict: {report['verdict']}, {report['gates_passed']}/{report['gates_total']}")
print(f"Hold reasons: {report.get('hold_reasons', [])}")
for g in report["gates"]:
    if not g.get("passed"):
        print(f"\nFAILED: {g['gate']}")
        print(f"  detail: {g.get('detail','')}")
        print(f"  failure_class: {g.get('failure_class','')}")
        print(f"  stderr_tail: {g.get('stderr','')[-300:]}")
        print(f"  stdout_tail: {g.get('stdout','')[-300:]}")
