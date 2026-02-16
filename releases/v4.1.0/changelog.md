# v4.1.0 Changelog

## Release: v4.1.0
**Date:** 2026-02-16
**Tag:** v4.1.0
**RC:** v4.1.0-rc1 at 3753211

## Summary
Governance provenance deepening, fault/recovery determinism under stress,
and reproducible release with cleanroom parity. No-regression release
building on v4.0.0 (500/500) with deeper determinism guarantees.

## Epics
### E1: Governance Provenance Deepening
- provenance_registry.py: PolicyProvenance, ProvenanceRegistry
- lineage_mapper.py: ControlLineage, LineageMapper
- evidence_integrity.py: EvidenceRecord, EvidenceIntegrityValidator
- provenance_reporter.py: ProvenanceReporter
- 36 unit tests

### E2: Fault/Recovery Determinism Under Stress
- chaos_policy.py: ChaosScenario, ChaosPolicyRegistry
- restore_policy.py: BackupRecord, RestorePreconditionValidator
- replay_policy.py: DLQEntry, ReplayPolicyEngine
- incident_lineage.py: IncidentNode, IncidentLineageChain
- determinism_report.py: DeterminismReporter
- 49 unit tests

### E3: Reproducible Release + Cleanroom Parity
- repro_build_policy.py: FrozenDependencySet
- cleanroom_parity.py: CleanroomParityChecker
- release_manifest_policy.py: ReleaseManifestChecker
- rollback_determinism.py: RollbackScriptRegistry
- release_lineage.py: ReleaseLineageChecker
- 46 unit tests

## Metrics
- Gates: 41/41 PROMOTE (36 Class A + 3 Class B + 1 Class C + 1 floor)
- Tests: 753 (622 inherited + 131 new)
- Dual-pass: 500/500 Standard, 500/500 Conservative (gap=0)
- Epic gates: E1 10/10, E2 10/10, E3 10/10 (30/30 total)

## Inherited Baseline
- v4.0.0: 37/37 gates, 622 tests, 500/500 dual-pass
- All v3.x and v2.x governance modules frozen and extended
