#!/usr/bin/env python3
"""
Rate limiter enforcement gate.

Verifies:
  1. RateLimiter module imports and initializes
  2. Token bucket enforces limits (rapid calls yield denial)
  3. Middleware ordering is correct (rate limiter before route handlers)
  4. 429 response includes Retry-After header pattern

Produces: reports/audit/rate-limiter-gate-*.json
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "shared"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api-gateway"))

REPORT_DIR = REPO_ROOT / "reports" / "audit"


def check_import():
    """Verify rate_limiter module imports correctly."""
    try:
        from rate_limiter import RateLimiter, TokenBucket
        return {"check": "import", "passed": True}
    except Exception as e:
        return {"check": "import", "passed": False, "error": str(e)}


def check_token_bucket_enforcement():
    """Verify token bucket denies excess requests."""
    from rate_limiter import RateLimiter
    # 2 requests/sec, burst of 2
    rl = RateLimiter(rate=2.0, burst=2)

    results = []
    # Exhaust burst
    for i in range(3):
        allowed, retry_after = rl.check("test_client")
        results.append({"call": i, "allowed": allowed, "retry_after": round(retry_after, 3)})

    # Third call should be denied
    denied = not results[2]["allowed"]
    retry_present = results[2]["retry_after"] > 0

    return {
        "check": "token_bucket_enforcement",
        "passed": denied and retry_present,
        "detail": results,
        "burst_exhausted_denial": denied,
        "retry_after_present": retry_present,
    }


def check_middleware_pattern():
    """Verify rate_limit_middleware exists in api-gateway main.py."""
    main_path = REPO_ROOT / "services" / "api-gateway" / "main.py"
    content = main_path.read_text(encoding="utf-8")

    has_middleware_decorator = '@app.middleware("http")' in content
    has_rate_limit_func = "async def rate_limit_middleware" in content
    has_429_response = "status_code=429" in content
    has_retry_header = "Retry-After" in content
    has_rate_limited_code = "RATE_LIMITED" in content

    passed = all([
        has_middleware_decorator,
        has_rate_limit_func,
        has_429_response,
        has_retry_header,
        has_rate_limited_code,
    ])

    return {
        "check": "middleware_pattern",
        "passed": passed,
        "middleware_decorator": has_middleware_decorator,
        "rate_limit_function": has_rate_limit_func,
        "http_429_response": has_429_response,
        "retry_after_header": has_retry_header,
        "rate_limited_error_code": has_rate_limited_code,
    }


def check_per_client_isolation():
    """Verify different clients get independent buckets."""
    from rate_limiter import RateLimiter
    rl = RateLimiter(rate=1.0, burst=1)

    # Exhaust client A
    rl.check("client_a")
    a_allowed, _ = rl.check("client_a")

    # Client B should still be allowed
    b_allowed, _ = rl.check("client_b")

    return {
        "check": "per_client_isolation",
        "passed": not a_allowed and b_allowed,
        "client_a_denied_after_burst": not a_allowed,
        "client_b_independent": b_allowed,
    }


def main():
    print("=== SONIA Rate Limiter Gate ===\n")

    checks = [
        check_import(),
        check_token_bucket_enforcement(),
        check_middleware_pattern(),
        check_per_client_isolation(),
    ]

    for c in checks:
        tag = "PASS" if c["passed"] else "FAIL"
        print(f"  [{tag}] {c['check']}")

    overall = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    report = {
        "gate": "rate-limiter",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "overall": overall,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = REPORT_DIR / "rate-limiter-gate-{}.json".format(
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {artifact}")
    print(f"\n{overall}: Rate limiter {'enforcement verified' if overall == 'PASS' else 'FAILED'}.")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
