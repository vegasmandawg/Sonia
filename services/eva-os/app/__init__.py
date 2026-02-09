"""
EVA-OS App -- Orchestrator Safety Integration

Wraps the EVAOSOrchestrator with the OpenClaw ActionGuard so that
every tool call passes through the mandatory safety layer before
dispatch.

Import SafeOrchestrator directly from app.orchestrator to avoid
circular import issues with cross-service app package resolution.
"""
