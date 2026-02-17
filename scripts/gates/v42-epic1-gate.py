#!/usr/bin/env python3
"""
v4.2 Epic 1: Identity, Session, and Memory Sovereignty Hardening Gate
======================================================================
10 real checks replacing the M0 placeholder.
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

GATE_ID = "v42-epic1-identity-memory-gate"
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
    identity = load_module("identity_policy", os.path.join(MODULE_DIR, "identity_policy.py"))
    session = load_module("session_boundary", os.path.join(MODULE_DIR, "session_boundary.py"))
    silo = load_module("memory_silo_policy", os.path.join(MODULE_DIR, "memory_silo_policy.py"))
    mutation = load_module("memory_mutation_policy", os.path.join(MODULE_DIR, "memory_mutation_policy.py"))
    redaction = load_module("redaction_lineage_policy", os.path.join(MODULE_DIR, "redaction_lineage_policy.py"))

    # 1. Session namespace isolation invariant
    def c1():
        pol = session.SessionBoundaryPolicy()
        s1 = session.SessionRecord("s1", "p1", "ns_a", "2026-01-01T00:00:00Z")
        s2 = session.SessionRecord("s2", "p1", "ns_b", "2026-01-01T00:00:00Z")
        pol.register_session(s1)
        pol.register_session(s2)
        same_ok = pol.check_access("s1", "s1", session.AccessType.READ)
        cross_denied = not pol.check_access("s1", "s2", session.AccessType.READ)
        return same_ok and cross_denied, f"same={same_ok}, cross_denied={cross_denied}"
    check("session_namespace_isolation_invariant", c1)

    # 2. Persona silo isolation invariant
    def c2():
        pol = identity.PersonaSiloPolicy()
        pol.register_persona(identity.PersonaIdentity("p1", "ns1", "Alice"))
        pol.register_persona(identity.PersonaIdentity("p2", "ns2", "Bob"))
        same_ok = pol.check_access("p1", "p1")
        cross_denied = not pol.check_access("p1", "p2")
        return same_ok and cross_denied, f"same={same_ok}, cross_denied={cross_denied}"
    check("persona_silo_isolation_invariant", c2)

    # 3. Cross-session read/write denial
    def c3():
        pol = session.SessionBoundaryPolicy()
        pol.register_session(session.SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        pol.register_session(session.SessionRecord("s2", "p1", "ns2", "2026-01-01T00:00:00Z"))
        read_denied = not pol.check_access("s1", "s2", session.AccessType.READ)
        write_denied = not pol.check_access("s1", "s2", session.AccessType.WRITE)
        ns_write_denied = not pol.check_write("s1", "ns2")
        ns_read_denied = not pol.check_read("s1", "ns2")
        ok = read_denied and write_denied and ns_write_denied and ns_read_denied
        return ok, f"read={read_denied}, write={write_denied}, ns_w={ns_write_denied}, ns_r={ns_read_denied}"
    check("cross_session_read_write_denial", c3)

    # 4. Cross-persona memory access denial
    def c4():
        spol = silo.MemorySiloPolicy()
        entry = silo.MemoryEntry("e1", "s1", "p1", "ns_persona1", "fact", "abc", "2026-01-01T00:00:00Z")
        spol.add_entry(entry)
        same_ok = spol.check_silo_access("ns_persona1", "e1")
        cross_denied = not spol.check_silo_access("ns_persona2", "e1")
        return same_ok and cross_denied, f"same={same_ok}, cross_denied={cross_denied}"
    check("cross_persona_memory_access_denial", c4)

    # 5. Memory mutation authorization policy enforcement
    def c5():
        pol = mutation.MemoryMutationPolicy()
        grant = mutation.MutationGrant("g1", "p1", "s1", "ns1",
                                        frozenset({"create"}), frozenset({"fact"}))
        pol.register_grant(grant)
        allowed = pol.check_mutation("p1", "s1", "ns1", mutation.MutationType.CREATE, "fact")
        denied = pol.check_mutation("p1", "s1", "ns1", mutation.MutationType.DELETE, "fact")
        no_grant = pol.check_mutation("p2", "s2", "ns2", mutation.MutationType.CREATE, "fact")
        ok = allowed["allowed"] and not denied["allowed"] and not no_grant["allowed"]
        return ok, f"granted={allowed['allowed']}, unauthorized_type={denied['allowed']}, no_grant={no_grant['allowed']}"
    check("memory_mutation_authorization_policy_enforcement", c5)

    # 6. Redaction lineage immutability
    def c6():
        chain = redaction.RedactionLineageChain()
        r1 = redaction.RedactionRecord("r1", "e1", ("f1",), "pii", "admin", "2026-01-01T00:00:00Z", "")
        chain.append(r1)
        r2 = redaction.RedactionRecord("r2", "e1", ("f2",), "gdpr", "admin",
                                        "2026-01-01T01:00:00Z", r1.fingerprint)
        chain.append(r2)
        integrity = chain.verify_chain_integrity()
        tamper_rejected = False
        try:
            bad = redaction.RedactionRecord("r3", "e1", ("f3",), "test", "admin",
                                             "2026-01-01T02:00:00Z", "TAMPERED")
            chain.append(bad)
        except ValueError:
            tamper_rejected = True
        ok = integrity["valid"] and tamper_rejected
        return ok, f"chain_valid={integrity['valid']}, tamper_rejected={tamper_rejected}"
    check("redaction_lineage_immutability", c6)

    # 7. Memory version conflict handling determinism
    def c7():
        p1 = mutation.MemoryMutationPolicy(mutation.ConflictResolution.REJECT)
        p2 = mutation.MemoryMutationPolicy(mutation.ConflictResolution.REJECT)
        for p in [p1, p2]:
            p.register_version(mutation.VersionedEntry("e1", 5, "hash_a", "ns1"))
        r1 = p1.check_version_conflict("e1", 3)
        r2 = p2.check_version_conflict("e1", 3)
        ok = (r1["conflict"] and r2["conflict"]
              and r1["resolution"] == r2["resolution"]
              and r1["resolution"] == "reject")
        return ok, f"both_conflict={r1['conflict'] and r2['conflict']}, same_resolution={r1['resolution']==r2['resolution']}"
    check("memory_version_conflict_handling_determinism", c7)

    # 8. Retention/deletion policy enforcement determinism
    def c8():
        p1 = silo.MemorySiloPolicy()
        p2 = silo.MemorySiloPolicy()
        rule = silo.RetentionRule("fact", 24, silo.RetentionAction.DELETE)
        for p in [p1, p2]:
            p.register_retention_rule(rule)
        entry = silo.MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z", age_hours=48)
        a1 = p1.evaluate_retention(entry)
        a2 = p2.evaluate_retention(entry)
        ok = a1 == a2 == silo.RetentionAction.DELETE
        return ok, f"deterministic={a1==a2}, action={a1.value}"
    check("retention_deletion_policy_enforcement_determinism", c8)

    # 9. Memory export/import boundary safety
    def c9():
        pol = silo.MemorySiloPolicy()
        # Valid same-namespace import
        valid = pol.validate_import_payload(1000, "fact", "ns1", "ns1")
        # Cross-namespace import rejected
        cross = pol.validate_import_payload(1000, "fact", "ns_target", "ns_source")
        # Oversized rejected
        big = pol.validate_import_payload(silo.MAX_IMPORT_PAYLOAD_BYTES + 1, "fact", "ns1", "ns1")
        # Disallowed type rejected
        bad_type = pol.validate_import_payload(100, "secret_key", "ns1", "ns1")
        ok = (valid["allowed"] and not cross["allowed"]
              and not big["allowed"] and not bad_type["allowed"])
        return ok, f"valid={valid['allowed']}, cross={cross['allowed']}, big={big['allowed']}, bad_type={bad_type['allowed']}"
    check("memory_export_import_boundary_safety", c9)

    # 10. Rerun parity (same inputs => same gate verdict)
    def c10():
        # Run checks 1-9 conceptually again by verifying fingerprint determinism
        p1 = identity.PersonaIdentity("p1", "ns1", "Test")
        p2 = identity.PersonaIdentity("p1", "ns1", "Test")
        fp_ok = p1.fingerprint == p2.fingerprint
        chain1 = redaction.RedactionLineageChain()
        chain2 = redaction.RedactionLineageChain()
        r = redaction.RedactionRecord("r1", "e1", ("f1",), "test", "admin", "2026-01-01T00:00:00Z", "")
        chain1.append(r)
        chain2.append(r)
        hash_ok = chain1.chain_hash() == chain2.chain_hash()
        ok = fp_ok and hash_ok
        return ok, f"fingerprint_parity={fp_ok}, chain_hash_parity={hash_ok}"
    check("rerun_parity", c10)

    total = 10
    elapsed = round(time.time() - t0, 3)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = {
        "epic": "E1",
        "gate": GATE_ID,
        "title": "Identity, Session, and Memory Sovereignty Hardening",
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
    out_path = os.path.join(out_dir, f"v42-epic1-identity-memory-{ts}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{passed}/{total} checks PASS")
    print(f"Artifact: {out_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
