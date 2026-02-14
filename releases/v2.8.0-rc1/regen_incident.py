"""Regenerate incident snapshot for GA bundle."""
import sys, json
sys.path.insert(0, r"S:\services\api-gateway")
from operator_session import OperatorSession, SubsystemHealth

op = OperatorSession(session_id="incident_sample")
op.update_subsystem("model", SubsystemHealth.HEALTHY, latency_ms=42)
op.update_subsystem("memory", SubsystemHealth.DEGRADED, latency_ms=890, detail="high latency during soak")
op.update_subsystem("perception", SubsystemHealth.HEALTHY, latency_ms=15)
op.update_subsystem("action", SubsystemHealth.HEALTHY, latency_ms=8)
op.update_subsystem("gateway", SubsystemHealth.HEALTHY, latency_ms=3)

# Simulate a few turn cycles
for i in range(3):
    op.begin_listening()
    op.begin_processing()
    op.begin_responding()
    op.end_turn(ok=True)

# Simulate a cancel
op.begin_listening()
op.cancel_turn(reason="user_interrupt")

snap = op.export_incident_snapshot()

for path in [r"S:\releases\v2.8.0\incidents\sample-incident-snapshot.json",
             r"S:\releases\v2.8.0-rc1\incidents\sample-incident-snapshot.json"]:
    with open(path, "w") as f:
        json.dump(snap, f, indent=2)
    print(f"Written: {path} ({len(json.dumps(snap))} bytes)")
