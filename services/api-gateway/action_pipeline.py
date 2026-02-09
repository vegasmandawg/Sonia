"""
Stage 5 — Action Pipeline
Planner → Validator → Executor → Verifier pipeline for desktop actions.
Maintains an in-memory action store keyed by action_id.
"""

import asyncio
import time
import uuid
import hashlib
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from schemas.action import (
    ActionIntent, ActionRecord, ActionState, ActionTelemetry,
    ValidationResult, ExecutionResult, RiskLevel,
    ActionPlanRequest, ActionPlanResponse,
)
from capability_registry import get_capability_registry, Capability
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from circuit_breaker import CircuitBreaker, CircuitOpenError, get_breaker_registry, BreakerRegistry
from dead_letter import DeadLetterQueue, get_dead_letter_queue
from action_audit import get_audit_logger, AuditLogger
from jsonl_logger import JsonlLogger


# ── Constants ────────────────────────────────────────────────────────────────

MAX_ACTIONS_IN_MEMORY = 5000
MAX_PENDING_PER_SESSION = 50
IDEMPOTENCY_WINDOW_SECONDS = 300  # 5 minutes


# ── Action Store ─────────────────────────────────────────────────────────────

class ActionStore:
    """
    In-memory store for action records.
    Thread-safe via asyncio lock.  Bounded by MAX_ACTIONS_IN_MEMORY.
    """

    def __init__(self):
        self._records: Dict[str, ActionRecord] = {}
        self._idempotency_map: Dict[str, str] = {}  # key -> action_id
        self._lock = asyncio.Lock()

    async def put(self, record: ActionRecord):
        async with self._lock:
            self._records[record.action_id] = record
            if record.idempotency_key:
                self._idempotency_map[record.idempotency_key] = record.action_id
            # Evict oldest if over limit
            if len(self._records) > MAX_ACTIONS_IN_MEMORY:
                oldest_key = min(self._records, key=lambda k: self._records[k].created_at)
                old = self._records.pop(oldest_key, None)
                if old and old.idempotency_key:
                    self._idempotency_map.pop(old.idempotency_key, None)

    async def get(self, action_id: str) -> Optional[ActionRecord]:
        return self._records.get(action_id)

    async def get_by_idempotency_key(self, key: str) -> Optional[ActionRecord]:
        aid = self._idempotency_map.get(key)
        if aid:
            return self._records.get(aid)
        return None

    async def update_state(self, action_id: str, state: ActionState, **kwargs):
        async with self._lock:
            rec = self._records.get(action_id)
            if rec:
                rec.state = state
                rec.updated_at = datetime.utcnow()
                for k, v in kwargs.items():
                    if hasattr(rec, k):
                        setattr(rec, k, v)

    async def list_actions(
        self,
        state: Optional[ActionState] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ActionRecord]:
        records = list(self._records.values())
        if state:
            records = [r for r in records if r.state == state]
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[offset: offset + limit]

    async def count(self, state: Optional[ActionState] = None) -> int:
        if state:
            return sum(1 for r in self._records.values() if r.state == state)
        return len(self._records)


# ── Telemetry logger ─────────────────────────────────────────────────────────

_action_logger: Optional[JsonlLogger] = None


def _get_action_logger() -> JsonlLogger:
    global _action_logger
    if _action_logger is None:
        _action_logger = JsonlLogger("actions")
    return _action_logger


def _log_action_event(action_id: str, event: str, **extra):
    logger = _get_action_logger()
    logger.log({
        "action_id": action_id,
        "event": event,
        **extra,
    })


# ── Pipeline ─────────────────────────────────────────────────────────────────

class ActionPipeline:
    """
    The core Stage 5 pipeline.

    Lifecycle:
        plan()     → creates ActionRecord in 'planned' state
        validate() → runs pre-flight checks → 'validated' | stays 'planned'
        execute()  → calls openclaw executor → 'succeeded' | 'failed' | 'timeout'
        verify()   → optional post-execution check → 'succeeded' (placeholder)

    The public entry-point `run()` orchestrates the full chain.
    """

    def __init__(self, openclaw_client: OpenclawClient,
                 breaker_registry: Optional[BreakerRegistry] = None,
                 dead_letter_queue: Optional[DeadLetterQueue] = None):
        self.store = ActionStore()
        self.registry = get_capability_registry()
        self.openclaw = openclaw_client
        self.breakers = breaker_registry or get_breaker_registry()
        self.dlq = dead_letter_queue or get_dead_letter_queue()
        self.audit = get_audit_logger()
        # Ensure an "openclaw" breaker exists
        self.breakers.get_or_create("openclaw")

    # ── Plan ─────────────────────────────────────────────────────────────

    async def plan(self, req: ActionPlanRequest, correlation_id: str) -> ActionRecord:
        """
        Phase 1: Create an ActionRecord from a plan request.
        Checks idempotency key; assigns risk level from capability registry.
        """
        t0 = time.time()

        # Idempotency guard
        if req.idempotency_key:
            existing = await self.store.get_by_idempotency_key(req.idempotency_key)
            if existing:
                _log_action_event(existing.action_id, "idempotency_hit",
                                  key=req.idempotency_key)
                return existing

        # Look up capability
        cap = self.registry.get(req.intent)
        risk = cap.risk_level if cap else "high"
        needs_confirm = cap.requires_confirmation if cap else True

        record = ActionRecord(
            action_id=f"act_{uuid.uuid4().hex[:16]}",
            intent=req.intent,
            params=req.params,
            state="planned",
            risk_level=risk,
            requires_confirmation=needs_confirm,
            dry_run=req.dry_run,
            idempotency_key=req.idempotency_key,
            correlation_id=correlation_id,
            session_id=req.session_id,
            max_retries=req.max_retries,
            timeout_ms=req.timeout_ms,
            telemetry=ActionTelemetry(plan_ms=round((time.time() - t0) * 1000, 2)),
        )

        await self.store.put(record)
        _log_action_event(record.action_id, "planned",
                          intent=req.intent, risk=risk, dry_run=req.dry_run,
                          correlation_id=correlation_id)
        return record

    # ── Validate ─────────────────────────────────────────────────────────

    async def validate(self, action_id: str) -> ValidationResult:
        """
        Phase 2: Run pre-flight checks.
        - capability exists?
        - capability implemented?
        - required params present?
        - timeout within bounds?
        - risk classification consistent?
        """
        t0 = time.time()
        record = await self.store.get(action_id)
        if not record:
            return ValidationResult(valid=False,
                                    rejection_reason="Action not found")

        checks: List[Dict[str, Any]] = []
        cap = self.registry.get(record.intent)

        # Check 1: capability exists
        if not cap:
            checks.append({"check": "capability_exists", "pass": False,
                           "detail": f"Unknown intent: {record.intent}"})
            result = ValidationResult(
                valid=False,
                checks=checks,
                risk_level=record.risk_level,
                requires_confirmation=record.requires_confirmation,
                rejection_reason=f"Unknown intent: {record.intent}",
            )
            elapsed = round((time.time() - t0) * 1000, 2)
            record.telemetry.validate_ms = elapsed
            record.validation = result
            await self.store.update_state(action_id, "planned", validation=result,
                                          telemetry=record.telemetry)
            _log_action_event(action_id, "validation_failed",
                              reason="unknown_intent")
            return result

        checks.append({"check": "capability_exists", "pass": True})

        # Check 2: implemented
        if not cap.implemented:
            checks.append({"check": "capability_implemented", "pass": False,
                           "detail": f"Intent '{record.intent}' is not yet implemented"})
            result = ValidationResult(
                valid=False,
                checks=checks,
                risk_level=cap.risk_level,
                requires_confirmation=cap.requires_confirmation,
                rejection_reason=f"Not implemented: {record.intent}",
            )
            elapsed = round((time.time() - t0) * 1000, 2)
            record.telemetry.validate_ms = elapsed
            record.validation = result
            await self.store.update_state(action_id, "planned", validation=result,
                                          telemetry=record.telemetry)
            _log_action_event(action_id, "validation_failed",
                              reason="not_implemented")
            return result

        checks.append({"check": "capability_implemented", "pass": True})

        # Check 3: required params
        param_errors = self.registry.validate_params(record.intent, record.params)
        if param_errors:
            checks.append({"check": "required_params", "pass": False,
                           "detail": param_errors})
            result = ValidationResult(
                valid=False,
                checks=checks,
                risk_level=cap.risk_level,
                requires_confirmation=cap.requires_confirmation,
                rejection_reason="; ".join(param_errors),
            )
            elapsed = round((time.time() - t0) * 1000, 2)
            record.telemetry.validate_ms = elapsed
            record.validation = result
            await self.store.update_state(action_id, "planned", validation=result,
                                          telemetry=record.telemetry)
            _log_action_event(action_id, "validation_failed",
                              reason="missing_params", errors=param_errors)
            return result

        checks.append({"check": "required_params", "pass": True})

        # Check 4: timeout bounds
        effective_max = min(cap.max_timeout_ms, 120000)
        if record.timeout_ms > effective_max:
            checks.append({"check": "timeout_bounds", "pass": False,
                           "detail": f"Timeout {record.timeout_ms}ms exceeds max {effective_max}ms"})
        else:
            checks.append({"check": "timeout_bounds", "pass": True})

        # Check 5: risk classification
        checks.append({"check": "risk_classification", "pass": True,
                        "detail": f"Assessed: {cap.risk_level}"})

        all_pass = all(c["pass"] for c in checks)
        result = ValidationResult(
            valid=all_pass,
            checks=checks,
            risk_level=cap.risk_level,
            requires_confirmation=cap.requires_confirmation,
            rejection_reason=None if all_pass else "Pre-flight check failed",
        )

        elapsed = round((time.time() - t0) * 1000, 2)
        record.telemetry.validate_ms = elapsed
        record.validation = result
        new_state: ActionState = "validated" if all_pass else "planned"
        # Update risk from capability truth
        await self.store.update_state(action_id, new_state,
                                      validation=result,
                                      risk_level=cap.risk_level,
                                      requires_confirmation=cap.requires_confirmation,
                                      telemetry=record.telemetry)

        _log_action_event(action_id, "validated" if all_pass else "validation_failed",
                          checks_passed=sum(1 for c in checks if c["pass"]),
                          checks_total=len(checks))
        return result

    # ── Execute ──────────────────────────────────────────────────────────

    async def execute(self, action_id: str) -> ExecutionResult:
        """
        Phase 3: Execute the validated action via OpenClaw.
        Handles retries up to max_retries.
        """
        record = await self.store.get(action_id)
        if not record:
            return ExecutionResult(success=False, error_code="NOT_FOUND",
                                   error_message="Action not found")

        if record.state not in ("validated", "approved"):
            return ExecutionResult(
                success=False,
                error_code="INVALID_STATE",
                error_message=f"Cannot execute action in state '{record.state}'",
            )

        # If confirmation required and not yet approved, block
        if record.requires_confirmation and record.state != "approved":
            await self.store.update_state(action_id, "pending_approval")
            _log_action_event(action_id, "pending_approval")
            return ExecutionResult(
                success=False,
                error_code="AWAITING_APPROVAL",
                error_message="Action requires operator confirmation",
            )

        await self.store.update_state(action_id, "executing")
        _log_action_event(action_id, "executing", intent=record.intent)

        # Check circuit breaker before proceeding
        breaker = self.breakers.get("openclaw")
        if breaker and breaker.state.value == "open":
            # Short-circuit: breaker is open, go directly to dead letter
            elapsed = 0.0
            result = ExecutionResult(
                success=False,
                error_code="CIRCUIT_OPEN",
                error_message=f"Circuit breaker 'openclaw' is OPEN — dependency unavailable",
                retries_used=0,
                duration_ms=elapsed,
            )
            record.telemetry.execute_ms = elapsed
            await self.store.update_state(
                action_id, "failed",
                execution=result, telemetry=record.telemetry,
                completed_at=datetime.utcnow(),
            )
            # Enqueue to dead letter
            await self.dlq.enqueue(
                action_id=record.action_id,
                intent=record.intent,
                params=record.params,
                error_code="CIRCUIT_OPEN",
                error_message="Circuit breaker open — execution skipped",
                correlation_id=record.correlation_id,
                session_id=record.session_id,
                retries_exhausted=0,
            )
            _log_action_event(action_id, "failed",
                              reason="circuit_open", duration_ms=elapsed)
            return result

        t0 = time.time()
        last_error = None
        retries = 0

        for attempt in range(record.max_retries + 1):
            try:
                # Execute through circuit breaker
                async def _openclaw_call():
                    return await self.openclaw.execute(
                        tool_name=record.intent,
                        args=record.params,
                        timeout_ms=record.timeout_ms,
                        correlation_id=record.correlation_id,
                    )

                if breaker:
                    openclaw_result = await breaker.call(_openclaw_call)
                else:
                    openclaw_result = await _openclaw_call()

                elapsed = round((time.time() - t0) * 1000, 2)
                status = openclaw_result.get("status", "error")

                if status == "executed":
                    result = ExecutionResult(
                        success=True,
                        output=openclaw_result.get("result", {}),
                        side_effects=openclaw_result.get("side_effects", []),
                        retries_used=retries,
                        duration_ms=elapsed,
                    )
                    record.telemetry.execute_ms = elapsed
                    await self.store.update_state(
                        action_id, "succeeded",
                        execution=result, telemetry=record.telemetry,
                        completed_at=datetime.utcnow(), retry_count=retries,
                    )
                    _log_action_event(action_id, "succeeded",
                                      duration_ms=elapsed, retries=retries)
                    return result

                elif status == "policy_denied":
                    result = ExecutionResult(
                        success=False,
                        error_code="POLICY_DENIED",
                        error_message=openclaw_result.get("message", "Policy denied"),
                        retries_used=retries,
                        duration_ms=elapsed,
                    )
                    record.telemetry.execute_ms = elapsed
                    await self.store.update_state(
                        action_id, "failed",
                        execution=result, telemetry=record.telemetry,
                        completed_at=datetime.utcnow(),
                    )
                    _log_action_event(action_id, "failed",
                                      reason="policy_denied", duration_ms=elapsed)
                    return result

                elif status == "timeout":
                    last_error = "Execution timed out"
                    retries += 1
                    if attempt < record.max_retries:
                        await asyncio.sleep(min(1.5 ** attempt, 5))
                        continue
                    # Final timeout
                    result = ExecutionResult(
                        success=False,
                        error_code="TIMEOUT",
                        error_message="Execution timed out after retries",
                        retries_used=retries,
                        duration_ms=round((time.time() - t0) * 1000, 2),
                    )
                    record.telemetry.execute_ms = result.duration_ms
                    await self.store.update_state(
                        action_id, "timeout",
                        execution=result, telemetry=record.telemetry,
                        completed_at=datetime.utcnow(), retry_count=retries,
                    )
                    _log_action_event(action_id, "timeout", retries=retries)
                    return result

                else:
                    # Generic error from openclaw
                    last_error = openclaw_result.get("error", "Unknown error")
                    retries += 1
                    if attempt < record.max_retries:
                        await asyncio.sleep(min(1.5 ** attempt, 5))
                        continue

            except CircuitOpenError as e:
                last_error = str(e)
                # Don't retry if breaker opened mid-flight
                break

            except OpenclawClientError as e:
                last_error = f"{e.code}: {e.message}"
                retries += 1
                if attempt < record.max_retries:
                    await asyncio.sleep(min(1.5 ** attempt, 5))
                    continue

            except Exception as e:
                last_error = str(e)
                retries += 1
                if attempt < record.max_retries:
                    await asyncio.sleep(min(1.5 ** attempt, 5))
                    continue

        # Exhausted retries
        elapsed = round((time.time() - t0) * 1000, 2)
        error_code = "CIRCUIT_OPEN" if "Circuit breaker" in (last_error or "") else "EXECUTION_FAILED"
        result = ExecutionResult(
            success=False,
            error_code=error_code,
            error_message=last_error or "Execution failed after retries",
            retries_used=retries,
            duration_ms=elapsed,
        )
        record.telemetry.execute_ms = elapsed
        await self.store.update_state(
            action_id, "failed",
            execution=result, telemetry=record.telemetry,
            completed_at=datetime.utcnow(), retry_count=retries,
        )

        # Enqueue to dead letter queue on exhausted retries
        await self.dlq.enqueue(
            action_id=record.action_id,
            intent=record.intent,
            params=record.params,
            error_code=error_code,
            error_message=last_error or "Execution failed after retries",
            correlation_id=record.correlation_id,
            session_id=record.session_id,
            retries_exhausted=retries,
        )

        _log_action_event(action_id, "failed",
                          reason=last_error, retries=retries, duration_ms=elapsed,
                          dead_lettered=True)
        return result

    # ── Verify (placeholder — full impl in M3) ──────────────────────────

    async def verify(self, action_id: str) -> bool:
        """
        Phase 4: Post-execution verification.
        Placeholder — returns True for executed actions.
        Full verification adapters land in M3.
        """
        record = await self.store.get(action_id)
        if not record:
            return False
        if record.state == "succeeded":
            t0 = time.time()
            # Placeholder: no actual verification yet
            elapsed = round((time.time() - t0) * 1000, 2)
            record.telemetry.verify_ms = elapsed
            await self.store.update_state(action_id, "succeeded",
                                          telemetry=record.telemetry)
            _log_action_event(action_id, "verified")
            return True
        return False

    # ── Full run ─────────────────────────────────────────────────────────

    async def run(self, req: ActionPlanRequest, correlation_id: str) -> ActionPlanResponse:
        """
        Full pipeline: plan → validate → (execute if not dry_run and not guarded) → verify.
        Returns a structured response suitable for the API layer.
        """
        t_start = time.time()

        # Phase 1: Plan
        record = await self.plan(req, correlation_id)

        # Create audit trail
        trail = self.audit.create_trail(record.action_id, record.intent, correlation_id)
        trail.record("plan", "completed", duration_ms=record.telemetry.plan_ms,
                      risk_level=record.risk_level, dry_run=record.dry_run)

        # Phase 2: Validate
        validation = await self.validate(record.action_id)

        # Refresh record after validation
        record = await self.store.get(record.action_id)
        trail.record("validate", "passed" if validation.valid else "failed",
                      duration_ms=record.telemetry.validate_ms,
                      checks_total=len(validation.checks) if validation.checks else 0)

        # Early exit: validation failed
        if not validation.valid:
            record.telemetry.total_ms = round((time.time() - t_start) * 1000, 2)
            await self.store.update_state(record.action_id, record.state,
                                          telemetry=record.telemetry)
            trail.record("lifecycle", "validation_failed",
                          detail=validation.rejection_reason)
            self.audit.flush_trail(record.action_id)
            return ActionPlanResponse(
                ok=False,
                action_id=record.action_id,
                state=record.state,
                intent=record.intent,
                risk_level=record.risk_level,
                requires_confirmation=record.requires_confirmation,
                validation=validation,
                telemetry=record.telemetry,
                error={"code": "VALIDATION_FAILED",
                       "message": validation.rejection_reason},
                correlation_id=correlation_id,
            )

        # Early exit: dry run
        if record.dry_run:
            record.telemetry.total_ms = round((time.time() - t_start) * 1000, 2)
            await self.store.update_state(record.action_id, "validated",
                                          telemetry=record.telemetry)
            trail.record("lifecycle", "dry_run_complete")
            self.audit.flush_trail(record.action_id)
            return ActionPlanResponse(
                ok=True,
                action_id=record.action_id,
                state="validated",
                intent=record.intent,
                risk_level=record.risk_level,
                requires_confirmation=record.requires_confirmation,
                validation=validation,
                telemetry=record.telemetry,
                correlation_id=correlation_id,
            )

        # Early exit: requires confirmation (gate to operator approval)
        if record.requires_confirmation:
            await self.store.update_state(record.action_id, "pending_approval")
            record = await self.store.get(record.action_id)
            record.telemetry.total_ms = round((time.time() - t_start) * 1000, 2)
            await self.store.update_state(record.action_id, "pending_approval",
                                          telemetry=record.telemetry)
            trail.record("approval", "pending",
                          detail=f"Awaiting operator approval (risk={record.risk_level})")
            self.audit.flush_trail(record.action_id)
            return ActionPlanResponse(
                ok=True,
                action_id=record.action_id,
                state="pending_approval",
                intent=record.intent,
                risk_level=record.risk_level,
                requires_confirmation=True,
                validation=validation,
                telemetry=record.telemetry,
                correlation_id=correlation_id,
            )

        # Phase 3: Execute (safe actions proceed immediately)
        execution = await self.execute(record.action_id)
        record = await self.store.get(record.action_id)
        trail.record("execute", "succeeded" if execution.success else "failed",
                      duration_ms=record.telemetry.execute_ms,
                      retries_used=execution.retries_used if execution else 0,
                      error_code=execution.error_code if not execution.success else None)

        # Phase 4: Verify (if succeeded)
        if execution.success:
            await self.verify(record.action_id)
            record = await self.store.get(record.action_id)
            trail.record("verify", "passed", duration_ms=record.telemetry.verify_ms)

        record.telemetry.total_ms = round((time.time() - t_start) * 1000, 2)
        await self.store.update_state(record.action_id, record.state,
                                      telemetry=record.telemetry)

        trail.record("lifecycle", "complete",
                      final_state=record.state,
                      total_ms=record.telemetry.total_ms)
        self.audit.flush_trail(record.action_id)

        return ActionPlanResponse(
            ok=execution.success,
            action_id=record.action_id,
            state=record.state,
            intent=record.intent,
            risk_level=record.risk_level,
            requires_confirmation=record.requires_confirmation,
            validation=validation,
            execution=execution,
            telemetry=record.telemetry,
            error={"code": execution.error_code,
                   "message": execution.error_message} if not execution.success else None,
            correlation_id=correlation_id,
        )

    # ── Approval flow ────────────────────────────────────────────────────

    async def approve(self, action_id: str) -> ActionPlanResponse:
        """Approve a pending action and execute it."""
        record = await self.store.get(action_id)
        if not record:
            return ActionPlanResponse(
                ok=False, action_id=action_id, state="failed",
                intent="unknown",
                error={"code": "NOT_FOUND", "message": "Action not found"},
            )
        if record.state != "pending_approval":
            return ActionPlanResponse(
                ok=False, action_id=action_id, state=record.state,
                intent=record.intent,
                error={"code": "INVALID_STATE",
                       "message": f"Cannot approve action in state '{record.state}'"},
            )

        await self.store.update_state(action_id, "approved")
        _log_action_event(action_id, "approved")

        t0 = time.time()
        execution = await self.execute(action_id)
        record = await self.store.get(action_id)

        if execution.success:
            await self.verify(action_id)
            record = await self.store.get(action_id)

        record.telemetry.approval_wait_ms = round((time.time() - t0) * 1000, 2)
        record.telemetry.total_ms = round(
            record.telemetry.plan_ms +
            record.telemetry.validate_ms +
            record.telemetry.approval_wait_ms +
            record.telemetry.execute_ms +
            record.telemetry.verify_ms, 2
        )
        await self.store.update_state(action_id, record.state,
                                      telemetry=record.telemetry)

        return ActionPlanResponse(
            ok=execution.success,
            action_id=record.action_id,
            state=record.state,
            intent=record.intent,
            risk_level=record.risk_level,
            requires_confirmation=record.requires_confirmation,
            validation=record.validation,
            execution=execution,
            telemetry=record.telemetry,
            error={"code": execution.error_code,
                   "message": execution.error_message} if not execution.success else None,
            correlation_id=record.correlation_id,
        )

    async def replay_dead_letter(self, letter_id: str) -> ActionPlanResponse:
        """Replay a dead-lettered action by re-running it through the pipeline."""
        dl = await self.dlq.get(letter_id)
        if not dl:
            return ActionPlanResponse(
                ok=False, action_id="", state="failed", intent="unknown",
                error={"code": "NOT_FOUND", "message": f"Dead letter {letter_id} not found"},
            )
        if dl.replayed:
            return ActionPlanResponse(
                ok=False, action_id=dl.replay_action_id or "", state="failed",
                intent=dl.intent,
                error={"code": "ALREADY_REPLAYED",
                       "message": f"Dead letter {letter_id} already replayed"},
            )

        # Re-run through the full pipeline
        req = ActionPlanRequest(
            intent=dl.intent,
            params=dl.params,
            session_id=dl.session_id,
        )
        correlation_id = dl.correlation_id or f"replay_{uuid.uuid4().hex[:8]}"
        result = await self.run(req, correlation_id)

        # Mark as replayed
        await self.dlq.mark_replayed(letter_id, result.action_id)

        _log_action_event(result.action_id, "replayed_from_dead_letter",
                          letter_id=letter_id, original_action_id=dl.action_id)
        return result

    async def deny(self, action_id: str) -> ActionPlanResponse:
        """Deny a pending action."""
        record = await self.store.get(action_id)
        if not record:
            return ActionPlanResponse(
                ok=False, action_id=action_id, state="failed",
                intent="unknown",
                error={"code": "NOT_FOUND", "message": "Action not found"},
            )
        if record.state != "pending_approval":
            return ActionPlanResponse(
                ok=False, action_id=action_id, state=record.state,
                intent=record.intent,
                error={"code": "INVALID_STATE",
                       "message": f"Cannot deny action in state '{record.state}'"},
            )

        await self.store.update_state(action_id, "denied",
                                      completed_at=datetime.utcnow())
        _log_action_event(action_id, "denied")

        record = await self.store.get(action_id)
        return ActionPlanResponse(
            ok=True,
            action_id=record.action_id,
            state="denied",
            intent=record.intent,
            risk_level=record.risk_level,
            requires_confirmation=record.requires_confirmation,
            validation=record.validation,
            telemetry=record.telemetry,
            correlation_id=record.correlation_id,
        )
