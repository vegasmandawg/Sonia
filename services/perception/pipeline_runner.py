"""
Perception Pipeline Runner -- v2.7-m2

Background task that monitors vision-capture frame events and
auto-triggers perception analysis when conditions are met.

Trigger conditions:
  - Frame available + scene staleness > threshold
  - Explicit perception.requested event
  - Scheduled interval (configurable, default 10s when active)

Anti-flood:
  - Minimum interval between inferences (cooldown)
  - Skip when perception is already processing
  - Respect privacy gate (no inference when disabled)

Integrates with EventBus for event-driven triggers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("perception.pipeline_runner")


@dataclass
class RunnerConfig:
    """Configuration for the perception pipeline runner."""
    # Minimum seconds between inferences
    cooldown_s: float = 5.0
    # Staleness threshold: re-analyze after this many seconds
    staleness_s: float = 10.0
    # Scheduled analysis interval (0 = disabled)
    scheduled_interval_s: float = 0.0
    # Max inference budget in ms
    max_inference_ms: float = 2000.0
    # Number of frames to request per analysis
    frame_count: int = 1


@dataclass
class RunnerStats:
    """Pipeline runner statistics."""
    total_triggers: int = 0
    total_runs: int = 0
    total_skipped_cooldown: int = 0
    total_skipped_busy: int = 0
    total_skipped_privacy: int = 0
    total_errors: int = 0
    last_run_at: float = 0.0
    last_scene_id: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_triggers": self.total_triggers,
            "total_runs": self.total_runs,
            "total_skipped_cooldown": self.total_skipped_cooldown,
            "total_skipped_busy": self.total_skipped_busy,
            "total_skipped_privacy": self.total_skipped_privacy,
            "total_errors": self.total_errors,
            "last_run_at": self.last_run_at,
            "last_scene_id": self.last_scene_id,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }


class PerceptionPipelineRunner:
    """
    Background runner that auto-triggers perception analysis.

    Usage:
        runner = PerceptionPipelineRunner(
            analyze_fn=perception_analyze,
            privacy_check_fn=check_vision_privacy,
        )
        await runner.start()
        # ... runner processes events via on_frame_event / on_perception_request
        await runner.stop()
    """

    def __init__(
        self,
        analyze_fn,
        privacy_check_fn,
        config: Optional[RunnerConfig] = None,
    ):
        """
        Args:
            analyze_fn: Async callable(trigger, context, frame_count, correlation_id) -> SceneAnalysis
            privacy_check_fn: Async callable() -> dict with "privacy" and "capture_allowed"
            config: Runner configuration
        """
        self.analyze_fn = analyze_fn
        self.privacy_check_fn = privacy_check_fn
        self.config = config or RunnerConfig()
        self.stats = RunnerStats()

        self._running = False
        self._scheduled_task: Optional[asyncio.Task] = None
        self._is_processing = False
        self._last_inference_at: float = 0.0

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the pipeline runner."""
        if self._running:
            return
        self._running = True
        self.stats.started_at = time.time()
        logger.info("Pipeline runner started (cooldown=%.1fs)", self.config.cooldown_s)

        # Start scheduled analysis if configured
        if self.config.scheduled_interval_s > 0:
            self._scheduled_task = asyncio.create_task(self._scheduled_loop())

    async def stop(self) -> None:
        """Stop the pipeline runner."""
        self._running = False
        if self._scheduled_task and not self._scheduled_task.done():
            self._scheduled_task.cancel()
            try:
                await self._scheduled_task
            except asyncio.CancelledError:
                pass
        logger.info("Pipeline runner stopped (total_runs=%d)", self.stats.total_runs)

    async def on_frame_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle vision.frame.available event from the event bus.
        Returns result dict.
        """
        self.stats.total_triggers += 1
        return await self._try_analyze(
            trigger="motion",
            context=event.get("payload", {}).get("context", ""),
            correlation_id=event.get("correlation_id", ""),
        )

    async def on_perception_request(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle perception.requested event from the event bus.
        Returns result dict.
        """
        self.stats.total_triggers += 1
        payload = event.get("payload", {})
        return await self._try_analyze(
            trigger=payload.get("trigger", "user_command"),
            context=payload.get("context", ""),
            frame_count=payload.get("frame_count", self.config.frame_count),
            correlation_id=event.get("correlation_id", ""),
        )

    async def _try_analyze(
        self,
        trigger: str = "motion",
        context: str = "",
        frame_count: int = 0,
        correlation_id: str = "",
    ) -> Dict[str, Any]:
        """Attempt to run analysis with guard checks."""
        if not self._running:
            return {"ok": False, "reason": "runner_stopped"}

        # Cooldown check
        now = time.monotonic()
        if now - self._last_inference_at < self.config.cooldown_s:
            self.stats.total_skipped_cooldown += 1
            return {"ok": False, "reason": "cooldown"}

        # Busy check
        if self._is_processing:
            self.stats.total_skipped_busy += 1
            return {"ok": False, "reason": "busy"}

        # Privacy check
        try:
            privacy = await self.privacy_check_fn()
            if privacy.get("privacy") == "disabled" or not privacy.get("capture_allowed", False):
                self.stats.total_skipped_privacy += 1
                return {"ok": False, "reason": "privacy_disabled"}
        except Exception as e:
            self.stats.total_skipped_privacy += 1
            return {"ok": False, "reason": f"privacy_check_failed: {e}"}

        # Run analysis
        self._is_processing = True
        self._last_inference_at = now
        try:
            if frame_count <= 0:
                frame_count = self.config.frame_count

            scene = await self.analyze_fn(
                trigger=trigger,
                context=context,
                frame_count=frame_count,
                correlation_id=correlation_id,
            )

            self.stats.total_runs += 1
            self.stats.last_run_at = time.time()
            if hasattr(scene, "scene_id"):
                self.stats.last_scene_id = scene.scene_id
            elif isinstance(scene, dict):
                self.stats.last_scene_id = scene.get("scene_id", "")

            return {"ok": True, "scene_id": self.stats.last_scene_id}

        except Exception as e:
            self.stats.total_errors += 1
            logger.warning("Analysis failed: %s", e)
            return {"ok": False, "reason": str(e)}

        finally:
            self._is_processing = False

    async def _scheduled_loop(self) -> None:
        """Background loop for scheduled analysis."""
        while self._running:
            try:
                await asyncio.sleep(self.config.scheduled_interval_s)
                if not self._running:
                    break
                self.stats.total_triggers += 1
                await self._try_analyze(
                    trigger="scheduled",
                    context="scheduled_scan",
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Scheduled analysis error: %s", e)
