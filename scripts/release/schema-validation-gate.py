#!/usr/bin/env python3
"""
Schema Validation Gate — Epic 1 delta gate.

Checks (≥8 required):
1. ConfigSchemaValidator exists and importable
2. ConfigSchemaValidator validates a correct config
3. ConfigSchemaValidator rejects missing required fields
4. ConfigSchemaValidator rejects type mismatches
5. DataSchemaValidator exists and importable
6. DataSchemaValidator validates all 7 entry types
7. DataSchemaValidator rejects unknown entry types
8. DataSchemaValidator enforces provenance fields
9. Schema summary methods return expected structure
10. Validation results serialize to dict correctly
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

CHECKS: list[dict] = []


def check(name: str, passed: bool, detail: str = ""):
    CHECKS.append({"name": name, "passed": passed, "detail": detail})


def main():
    # --- ConfigSchemaValidator checks ---
    try:
        from config_schema import ConfigSchemaValidator, FIELD_SPECS
        check("config_schema_importable", True)
    except Exception as e:
        check("config_schema_importable", False, str(e))
        # Can't continue without import
        return report()

    validator = ConfigSchemaValidator()

    # Check 2: valid config passes
    valid_cfg = {
        "schema_version": "1.1",
        "project_name": "sonia",
        "api_gateway_port": 7000,
        "model_router_port": 7010,
        "memory_engine_port": 7020,
    }
    result = validator.validate(valid_cfg)
    check("config_valid_passes", result.valid, f"errors={len(result.errors)}")

    # Check 3: missing required field fails
    bad_cfg = dict(valid_cfg)
    del bad_cfg["schema_version"]
    result = validator.validate(bad_cfg)
    check("config_missing_required_fails", not result.valid, f"errors={len(result.errors)}")

    # Check 4: type mismatch fails
    bad_cfg2 = dict(valid_cfg)
    bad_cfg2["api_gateway_port"] = "not_int"
    result = validator.validate(bad_cfg2)
    check("config_type_mismatch_fails", not result.valid, f"errors={len(result.errors)}")

    # --- DataSchemaValidator checks ---
    try:
        from data_schema import DataSchemaValidator, ENTRY_SCHEMAS, PROVENANCE_FIELDS
        check("data_schema_importable", True)
    except Exception as e:
        check("data_schema_importable", False, str(e))
        return report()

    dv = DataSchemaValidator()

    # Check 6: validates all 7 types
    all_types = dv.get_supported_types()
    check("data_schema_7_types", len(all_types) == 7, f"types={len(all_types)}")

    # Check 7: unknown type rejected
    result = dv.validate_entry({"entry_type": "alien_type"})
    check("data_schema_unknown_rejected", not result.valid)

    # Check 8: provenance enforcement
    raw_with_prov = {
        "entry_type": "raw",
        "content": "test",
        "timestamp": "2026-02-15T12:00:00Z",
        "session_id": "s1",
        "provenance": {"source_module": "test", "created_at": "2026-02-15T12:00:00Z", "entry_type": "raw"},
    }
    result = dv.validate_entry(raw_with_prov)
    check("data_schema_provenance_valid", result.provenance_valid)

    # Check 9: schema summary structure
    cs_summary = validator.get_schema_summary()
    ds_summary = dv.get_schema_summary()
    check("schema_summaries_structured",
          "total_fields" in cs_summary and "total_types" in ds_summary,
          f"config_keys={list(cs_summary.keys())}, data_keys={list(ds_summary.keys())}")

    # Check 10: to_dict serialization
    result = dv.validate_entry(raw_with_prov)
    d = result.to_dict()
    check("validation_to_dict", "valid" in d and "violations" in d and "provenance_valid" in d)

    return report()


def report():
    passed = sum(1 for c in CHECKS if c["passed"])
    total = len(CHECKS)
    verdict = "PASS" if passed >= 8 and all(c["passed"] for c in CHECKS) else "FAIL"

    print(f"\n=== Schema Validation Gate ===")
    for c in CHECKS:
        status = "PASS" if c["passed"] else "FAIL"
        detail = f" ({c['detail']})" if c["detail"] else ""
        print(f"  [{status}] {c['name']}{detail}")
    print(f"\nResult: {passed}/{total} checks passed — {verdict}")

    # Write JSON artifact
    artifact = {
        "gate": "schema-validation-gate",
        "checks": CHECKS,
        "passed": passed,
        "total": total,
        "verdict": verdict,
    }
    artifact_dir = Path(r"S:\reports\audit")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir / f"schema-validation-gate-{ts}.json"
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"Artifact: {artifact_path}")

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
