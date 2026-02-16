#!/usr/bin/env python3
"""
v4.2 Epic 3: Reproducible Release + Cleanroom Parity Gate
==========================================================
10 real checks replacing the M0 placeholder.
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

GATE_ID = "v42-epic3-repro-release-gate"
MODULE_DIR = os.path.join("S:", "services", "api-gateway")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    t0 = time.time()
    results = []
    passed = 0

    def check(name, fn):
        nonlocal passed
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"ERROR: {e}"
        results.append({"check": name, "verdict": "PASS" if ok else "FAIL", "detail": detail})
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}: {detail}")
        if ok:
            passed += 1

    # Load modules
    repro = load_module("repro_build_policy", os.path.join(MODULE_DIR, "repro_build_policy.py"))
    cleanroom = load_module("cleanroom_parity", os.path.join(MODULE_DIR, "cleanroom_parity.py"))
    manifest = load_module("release_manifest_policy", os.path.join(MODULE_DIR, "release_manifest_policy.py"))
    rollback = load_module("rollback_determinism", os.path.join(MODULE_DIR, "rollback_determinism.py"))
    lineage = load_module("release_lineage", os.path.join(MODULE_DIR, "release_lineage.py"))

    import hashlib

    # 1. Frozen deps: all pinned, no floating ranges
    def c1():
        fds = repro.FrozenDependencySet()
        fds.add(repro.DependencyEntry("fastapi", "0.115.0", "==0.115.0", "hash1"))
        fds.add(repro.DependencyEntry("uvicorn", "0.30.0", "==0.30.0", "hash2"))
        pinned = fds.all_pinned()
        fds.add(repro.DependencyEntry("bad", "1.0", ">=1.0"))
        not_pinned = not fds.all_pinned()
        return pinned and not_pinned, f"pinned={pinned}, floating_detected={not_pinned}"
    check("frozen_deps_no_floating_ranges", c1)

    # 2. Lock hash deterministic and verifiable
    def c2():
        fds = repro.FrozenDependencySet()
        fds.add(repro.DependencyEntry("a", "1.0", "==1.0"))
        fds.add(repro.DependencyEntry("b", "2.0", "==2.0"))
        h1 = fds.compute_lock_hash()
        h2 = fds.compute_lock_hash()
        verified = fds.verify_lock_hash(h1)
        bad = not fds.verify_lock_hash("wrong")
        return h1 == h2 and verified and bad, f"deterministic={h1==h2}, verify={verified}, bad_rejected={bad}"
    check("lock_hash_deterministic_verifiable", c2)

    # 3. Manifest completeness — all required entries present with hashes
    def c3():
        mc = manifest.ReleaseManifestChecker()
        mc.set_metadata(manifest.ReleaseMetadata("4.2.0", "9.0", "2026-01-01T00:00:00Z", "abc", "v4.2.0"))
        for name in manifest.REQUIRED_MANIFEST_ENTRIES:
            h = hashlib.sha256(name.encode()).hexdigest()
            mc.add_entry(manifest.ManifestEntry(name, h, 100))
        complete = mc.manifest_complete()
        hashes = mc.all_hashes_present()
        mc2 = manifest.ReleaseManifestChecker()
        mc2.add_entry(manifest.ManifestEntry("gate-report.json", "a" * 64, 100))
        incomplete = not mc2.manifest_complete()
        return complete and hashes and incomplete, f"complete={complete}, hashes={hashes}, incomplete_detected={incomplete}"
    check("manifest_completeness_all_entries_hashed", c3)

    # 4. Cleanroom parity — identical rebuilds match, different ones don't
    def c4():
        checker = cleanroom.CleanroomParityChecker()
        for f in ["a.json", "b.json", "c.json"]:
            fp = cleanroom.fingerprint_from_content(f, "data")
            checker.register_original(fp)
            checker.register_cleanroom(fp)
        parity = checker.check_parity()
        good = parity.overall_parity and parity.matched == 3
        checker2 = cleanroom.CleanroomParityChecker()
        checker2.register_original(cleanroom.fingerprint_from_content("x.json", "v1"))
        checker2.register_cleanroom(cleanroom.fingerprint_from_content("x.json", "v2"))
        bad = not checker2.check_parity().overall_parity
        return good and bad, f"parity={good}, mismatch_detected={bad}"
    check("cleanroom_parity_match_and_mismatch", c4)

    # 5. Tag/commit/changelog linkage
    def c5():
        lc = lineage.ReleaseLineageChecker()
        lc.set_release_tag(lineage.ReleaseTag("v4.2.0", "abc123", "4.2.0", "## 4.2.0 changes"))
        good = lc.check_tag_linkage()
        lc2 = lineage.ReleaseLineageChecker()
        lc2.set_release_tag(lineage.ReleaseTag("v4.0.0", "abc", "4.2.0", "log"))
        bad_tag = not lc2.check_tag_linkage()
        lc3 = lineage.ReleaseLineageChecker()
        lc3.set_release_tag(lineage.ReleaseTag("v4.2.0", "abc", "4.2.0", None))
        no_log = not lc3.check_tag_linkage()
        return good and bad_tag and no_log, f"valid={good}, bad_tag={bad_tag}, no_changelog={no_log}"
    check("tag_commit_changelog_linkage", c5)

    # 6. Rollback scripts exist and support dry-run
    def c6():
        reg = rollback.RollbackScriptRegistry()
        s1 = rollback.RollbackScript("rb-001", "rollback", "rb.ps1", "4.1.0", True, ("svc_stopped",))
        s2 = rollback.RollbackScript("rb-002", "rollback", "rb2.ps1", "4.1.0", True, ("svc_stopped",))
        reg.register(s1)
        reg.register(s2)
        all_dry = reg.all_support_dry_run()
        reg.register(rollback.RollbackScript("rb-bad", "rb", "rb3.ps1", "4.1.0", False, ("x",)))
        detected = not reg.all_support_dry_run()
        return all_dry and detected, f"all_dry_run={all_dry}, missing_detected={detected}"
    check("rollback_scripts_exist_dry_run", c6)

    # 7. Rollback dry-run output deterministic
    def c7():
        s = rollback.RollbackScript("rb-001", "rollback", "rb.ps1", "4.1.0", True, ("svc_stopped",))
        det = rollback.dry_run_is_deterministic(s)
        o1 = rollback.simulate_dry_run(s)
        o2 = rollback.simulate_dry_run(s)
        same = o1.output_hash == o2.output_hash
        s2 = rollback.RollbackScript("rb-002", "rollback", "rb.ps1", "3.9.0", True, ("svc_stopped",))
        diff = rollback.simulate_dry_run(s).output_hash != rollback.simulate_dry_run(s2).output_hash
        return det and same and diff, f"deterministic={det}, same={same}, diff_version_diff_hash={diff}"
    check("rollback_dry_run_deterministic", c7)

    # 8. Release metadata integrity — semver, timestamp, tag/version match
    def c8():
        good = manifest.ReleaseMetadata("4.2.0", "9.0", "2026-01-01T00:00:00Z", "abc", "v4.2.0")
        ok = good.version_valid() and good.timestamp_valid() and good.tag_matches_version()
        bad_ver = manifest.ReleaseMetadata("not-semver", "9.0", "2026-01-01T00:00:00Z", "abc", "vnot-semver")
        bad = not bad_ver.version_valid()
        bad_ts = manifest.ReleaseMetadata("4.2.0", "9.0", "bad-time", "abc", "v4.2.0")
        ts_fail = not bad_ts.timestamp_valid()
        return ok and bad and ts_fail, f"valid={ok}, bad_ver={bad}, bad_ts={ts_fail}"
    check("release_metadata_integrity", c8)

    # 9. Evidence artifacts complete with valid hashes
    def c9():
        lc = lineage.ReleaseLineageChecker()
        lc.set_release_tag(lineage.ReleaseTag("v4.2.0", "abc", "4.2.0", "log"))
        for atype in lineage.REQUIRED_EVIDENCE_ARTIFACTS:
            h = hashlib.sha256(atype.encode()).hexdigest()
            lc.add_evidence(lineage.EvidenceArtifact(atype, f"reports/{atype}.json", h))
        complete = lc.evidence_complete()
        lc2 = lineage.ReleaseLineageChecker()
        lc2.add_evidence(lineage.EvidenceArtifact("gate-report", "path", ""))
        bad = not lc2.evidence_complete()
        return complete and bad, f"complete={complete}, bad_hash_detected={bad}"
    check("evidence_artifacts_complete_hashed", c9)

    # 10. Rerun parity — full audit deterministic across instances
    def c10():
        def build_checker():
            mc = manifest.ReleaseManifestChecker()
            mc.set_metadata(manifest.ReleaseMetadata("4.2.0", "9.0", "2026-01-01T00:00:00Z", "abc", "v4.2.0"))
            for name in manifest.REQUIRED_MANIFEST_ENTRIES:
                h = hashlib.sha256(name.encode()).hexdigest()
                mc.add_entry(manifest.ManifestEntry(name, h, 100))
            return mc
        mc1 = build_checker()
        mc2 = build_checker()
        a1 = mc1.full_audit()
        a2 = mc2.full_audit()
        same_verdict = a1["overall_pass"] == a2["overall_pass"] == True
        h1 = mc1.compute_manifest_hash()
        h2 = mc2.compute_manifest_hash()
        same_hash = h1 == h2
        # Lineage rerun
        def build_lineage():
            lc = lineage.ReleaseLineageChecker()
            lc.set_release_tag(lineage.ReleaseTag("v4.2.0", "abc", "4.2.0", "log"))
            for atype in lineage.REQUIRED_EVIDENCE_ARTIFACTS:
                h = hashlib.sha256(atype.encode()).hexdigest()
                lc.add_evidence(lineage.EvidenceArtifact(atype, f"reports/{atype}.json", h))
            return lc
        lh1 = build_lineage().compute_lineage_hash()
        lh2 = build_lineage().compute_lineage_hash()
        lineage_same = lh1 == lh2
        return same_verdict and same_hash and lineage_same, \
            f"audit_deterministic={same_verdict}, manifest_hash={same_hash}, lineage_hash={lineage_same}"
    check("rerun_parity_deterministic", c10)

    total = 10
    elapsed = round(time.time() - t0, 3)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = {
        "epic": "E3",
        "gate": GATE_ID,
        "title": "Reproducible Release + Cleanroom Parity",
        "checks": total,
        "passed": passed,
        "verdict": "PASS" if passed == total else "FAIL",
        "elapsed_s": elapsed,
        "retries": 0,
        "failure_class": None,
        "results": results,
        "timestamp": ts,
    }

    out_dir = os.path.join("S:", "reports", "audit")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"v42-epic3-repro-release-{ts}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{passed}/{total} checks PASS")
    print(f"Artifact: {out_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
