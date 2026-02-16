"""
Contract Consistency & Trace Propagation (Section L: Contracts)
================================================================
Ensures API contract fields are consistent and trace/correlation
IDs propagate correctly across service boundaries.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set


CORRELATION_ID_PATTERN = re.compile(r"^(req|corr)_[a-zA-Z0-9_-]{4,64}$")


@dataclass
class ContractField:
    name: str
    field_type: str  # "string", "int", "bool", "object", "array"
    required: bool = True
    description: str = ""


@dataclass
class ServiceContract:
    service: str
    version: str
    fields: List[ContractField] = field(default_factory=list)

    def get_required_fields(self) -> List[str]:
        return [f.name for f in self.fields if f.required]


class ContractConsistencyChecker:
    """Validates contract consistency across services."""

    def __init__(self):
        self._contracts: Dict[str, ServiceContract] = {}

    def register(self, contract: ServiceContract) -> None:
        self._contracts[contract.service] = contract

    def check_required_fields(self, service: str, payload: Dict) -> Dict[str, Any]:
        contract = self._contracts.get(service)
        if contract is None:
            return {"valid": False, "reason": "no contract registered"}
        required = contract.get_required_fields()
        missing = [f for f in required if f not in payload]
        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "service": service,
        }

    def check_cross_service_consistency(self, shared_fields: List[str]) -> Dict[str, Any]:
        """Check that shared fields appear in all contracts that reference them."""
        inconsistencies = []
        for fname in shared_fields:
            present_in = []
            missing_from = []
            for svc, contract in self._contracts.items():
                field_names = [f.name for f in contract.fields]
                if fname in field_names:
                    present_in.append(svc)
                else:
                    missing_from.append(svc)
            if missing_from:
                inconsistencies.append({
                    "field": fname,
                    "present_in": present_in,
                    "missing_from": missing_from,
                })
        return {
            "consistent": len(inconsistencies) == 0,
            "inconsistencies": inconsistencies,
        }


class TracePropagationChecker:
    """Validates correlation ID propagation across trace stages."""

    @staticmethod
    def is_valid_correlation_id(cid: str) -> bool:
        return bool(CORRELATION_ID_PATTERN.match(cid))

    @staticmethod
    def check_propagation(stages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Check that correlation_id is present and consistent across stages."""
        if not stages:
            return {"valid": False, "reason": "no stages provided"}
        ids: Set[str] = set()
        missing_stages = []
        invalid_ids = []
        for i, stage in enumerate(stages):
            cid = stage.get("correlation_id")
            if cid is None:
                missing_stages.append(i)
            elif not CORRELATION_ID_PATTERN.match(cid):
                invalid_ids.append((i, cid))
            else:
                ids.add(cid)
        consistent = len(ids) <= 1  # all same ID
        return {
            "valid": len(missing_stages) == 0 and len(invalid_ids) == 0 and consistent,
            "consistent": consistent,
            "unique_ids": list(ids),
            "missing_stages": missing_stages,
            "invalid_ids": invalid_ids,
        }
