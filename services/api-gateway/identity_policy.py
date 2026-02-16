"""Identity and Persona Policy — v4.2 E1.

Enforces identity namespace isolation: each persona has a unique namespace,
cross-persona access is denied by default, and all identity decisions
are auditable with deterministic fingerprints.
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class PersonaIdentity:
    """Immutable persona identity with namespace binding."""
    persona_id: str
    namespace: str
    display_name: str
    allowed_scopes: FrozenSet[str] = frozenset()

    def __post_init__(self):
        if not self.persona_id:
            raise ValueError("persona_id must be non-empty")
        if not self.namespace:
            raise ValueError("namespace must be non-empty")
        if not self.display_name:
            raise ValueError("display_name must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "persona_id": self.persona_id,
            "namespace": self.namespace,
            "display_name": self.display_name,
            "allowed_scopes": sorted(self.allowed_scopes),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class PersonaSiloPolicy:
    """Enforces persona namespace isolation.

    Each persona operates in its own namespace silo. Cross-persona
    access requires an explicit grant which is logged and auditable.
    """

    def __init__(self):
        self._personas: Dict[str, PersonaIdentity] = {}
        self._grants: Dict[str, Set[str]] = {}  # persona_id -> set of granted persona_ids
        self._audit_log: List[dict] = []

    def register_persona(self, persona: PersonaIdentity) -> None:
        if persona.persona_id in self._personas:
            existing = self._personas[persona.persona_id]
            if existing.namespace != persona.namespace:
                raise ValueError(
                    f"Persona {persona.persona_id} already registered with "
                    f"namespace {existing.namespace}, cannot re-register with {persona.namespace}"
                )
            return  # idempotent
        self._personas[persona.persona_id] = persona
        self._audit_log.append({
            "action": "register_persona",
            "persona_id": persona.persona_id,
            "namespace": persona.namespace,
        })

    def check_access(self, requester_id: str, target_id: str) -> bool:
        """Check if requester can access target persona's namespace.

        Same-persona access is always allowed.
        Cross-persona access requires an explicit grant.
        """
        if requester_id == target_id:
            return True
        if requester_id not in self._personas:
            self._audit_log.append({
                "action": "access_denied",
                "reason": "requester_not_registered",
                "requester": requester_id,
                "target": target_id,
            })
            return False
        if target_id not in self._personas:
            self._audit_log.append({
                "action": "access_denied",
                "reason": "target_not_registered",
                "requester": requester_id,
                "target": target_id,
            })
            return False
        grants = self._grants.get(requester_id, set())
        allowed = target_id in grants
        if not allowed:
            self._audit_log.append({
                "action": "access_denied",
                "reason": "no_cross_persona_grant",
                "requester": requester_id,
                "target": target_id,
            })
        return allowed

    def grant_cross_access(self, grantor_id: str, grantee_id: str) -> None:
        """Grant grantee access to grantor's namespace."""
        if grantor_id not in self._personas:
            raise ValueError(f"Grantor {grantor_id} not registered")
        if grantee_id not in self._personas:
            raise ValueError(f"Grantee {grantee_id} not registered")
        if grantor_id not in self._grants:
            self._grants[grantor_id] = set()
        # Grant is: grantee can access grantor
        if grantee_id not in self._grants:
            self._grants[grantee_id] = set()
        self._grants[grantee_id].add(grantor_id)
        self._audit_log.append({
            "action": "grant_cross_access",
            "grantor": grantor_id,
            "grantee": grantee_id,
        })

    def revoke_cross_access(self, grantor_id: str, grantee_id: str) -> None:
        """Revoke grantee's access to grantor's namespace."""
        grants = self._grants.get(grantee_id, set())
        grants.discard(grantor_id)
        self._audit_log.append({
            "action": "revoke_cross_access",
            "grantor": grantor_id,
            "grantee": grantee_id,
        })

    @property
    def audit_log(self) -> List[dict]:
        return list(self._audit_log)

    @property
    def registered_count(self) -> int:
        return len(self._personas)

    def get_persona(self, persona_id: str) -> Optional[PersonaIdentity]:
        return self._personas.get(persona_id)
