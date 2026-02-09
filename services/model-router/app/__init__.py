"""
Model Router App -- Routing Profile Infrastructure

Provides deterministic, auditable routing profiles for the model-router service.
"""

from app.profiles import (
    ProfileName,
    ReasonCode,
    RetryPolicy,
    RoutingProfile,
    ProfileRegistry,
    classify_request,
    default_profiles,
)

from app.routing_engine import (
    RouteDecision,
    RoutingEngine,
)

from app.health_registry import (
    BackendState,
    HealthRegistry,
)

from app.budget_guard import (
    BackendCapacity,
    BudgetGuard,
)
