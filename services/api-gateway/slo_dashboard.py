"""
SLO Dashboard & Performance Assertions (Section K: Performance)
================================================================
Steady-state performance assertions with budget evidence.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional
import json
import time


class SLOStatus(Enum):
    MET = "MET"
    BREACHED = "BREACHED"
    UNKNOWN = "UNKNOWN"


@dataclass
class SLODefinition:
    name: str
    metric: str
    threshold: float
    unit: str = "ms"
    description: str = ""


@dataclass
class SLOResult:
    definition: SLODefinition
    actual: float
    status: SLOStatus

    @property
    def margin(self) -> float:
        return self.definition.threshold - self.actual


class SLODashboard:
    """Tracks SLO definitions and evaluates against actuals."""

    def __init__(self):
        self._slos: Dict[str, SLODefinition] = {}
        self._results: List[SLOResult] = []

    def define_slo(self, name: str, metric: str, threshold: float,
                   unit: str = "ms", description: str = "") -> SLODefinition:
        slo = SLODefinition(name=name, metric=metric, threshold=threshold,
                            unit=unit, description=description)
        self._slos[name] = slo
        return slo

    def evaluate(self, name: str, actual: float) -> SLOResult:
        slo = self._slos.get(name)
        if slo is None:
            raise KeyError(f"SLO '{name}' not defined")
        status = SLOStatus.MET if actual <= slo.threshold else SLOStatus.BREACHED
        result = SLOResult(definition=slo, actual=actual, status=status)
        self._results.append(result)
        return result

    def evaluate_all(self, actuals: Dict[str, float]) -> Dict[str, Any]:
        results = {}
        for name, actual in actuals.items():
            if name in self._slos:
                r = self.evaluate(name, actual)
                results[name] = {
                    "status": r.status.value,
                    "actual": r.actual,
                    "threshold": r.definition.threshold,
                    "margin": r.margin,
                }
        met = sum(1 for v in results.values() if v["status"] == "MET")
        breached = sum(1 for v in results.values() if v["status"] == "BREACHED")
        return {
            "total": len(results),
            "met": met,
            "breached": breached,
            "all_met": breached == 0,
            "results": results,
        }

    def get_budget_report(self) -> Dict[str, Any]:
        """Generate a budget report for all evaluated SLOs."""
        if not self._results:
            return {"total": 0, "results": []}
        entries = []
        for r in self._results:
            entries.append({
                "name": r.definition.name,
                "metric": r.definition.metric,
                "threshold": r.definition.threshold,
                "actual": r.actual,
                "status": r.status.value,
                "margin": r.margin,
                "unit": r.definition.unit,
            })
        return {"total": len(entries), "results": entries}

    def list_slos(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "metric": s.metric, "threshold": s.threshold, "unit": s.unit}
            for s in self._slos.values()
        ]
