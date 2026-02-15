#!/usr/bin/env python3
"""
Rate limiter enforcement integration test.

Tests that api-gateway rate limiter middleware is actually enforcing limits.
Requires api-gateway to be running on localhost:7000.
"""

import sys
from pathlib import Path

# Add api-gateway to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'services' / 'api-gateway'))

import time
import httpx
import pytest


BASE_URL = 'http://localhost:7000'
TIMEOUT = 10.0


@pytest.fixture(scope='module')
def client():
    """Create httpx client for testing."""
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


def test_single_request_succeeds(client):
    """Test that a single request succeeds (200 OK)."""
    response = client.get('/healthz')
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    body = response.json()
    assert body.get('ok') is True or body.get('status') == 'healthy', f"Unexpected body: {body}"


def test_rapid_burst_triggers_rate_limit(client):
    """Test that rapid burst triggers 429 Too Many Requests."""
    # Send 100 requests as fast as possible
    rate_limited = False
    responses = []

    start_time = time.time()
    for i in range(100):
        try:
            response = client.get('/healthz')
            responses.append(response)
            if response.status_code == 429:
                rate_limited = True
                break
        except Exception as e:
            pytest.fail(f"Request {i} failed with error: {e}")

    elapsed = time.time() - start_time

    # Should trigger rate limit within 1 second
    assert elapsed < 1.0, f"Burst took too long: {elapsed:.2f}s"
    assert rate_limited, "Rate limiter did not trigger 429 during rapid burst"

    # Find first 429 response
    rate_limit_response = next((r for r in responses if r.status_code == 429), None)
    assert rate_limit_response is not None, "No 429 response found in burst"


def test_rate_limit_response_includes_retry_after(client):
    """Test that 429 response includes Retry-After header."""
    # Trigger rate limit with burst
    rate_limit_response = None
    for _ in range(100):
        response = client.get('/healthz')
        if response.status_code == 429:
            rate_limit_response = response
            break

    assert rate_limit_response is not None, "Could not trigger rate limit"

    # Check for Retry-After header
    retry_after = rate_limit_response.headers.get('Retry-After')
    assert retry_after is not None, "Missing Retry-After header in 429 response"

    # Retry-After should be numeric (seconds) or HTTP-date
    try:
        retry_seconds = int(retry_after)
        assert retry_seconds > 0, f"Invalid Retry-After value: {retry_after}"
    except ValueError:
        # Could be HTTP-date format, just check it's not empty
        assert len(retry_after) > 0, "Empty Retry-After header"


def test_requests_succeed_after_waiting(client):
    """Test that requests succeed again after waiting for rate limit reset."""
    # First, trigger rate limit
    rate_limited = False
    for _ in range(100):
        response = client.get('/healthz')
        if response.status_code == 429:
            rate_limited = True
            retry_after = response.headers.get('Retry-After', '1')
            try:
                wait_time = int(retry_after)
            except ValueError:
                wait_time = 1
            break

    if not rate_limited:
        # Try one more burst to ensure we hit the limit
        for _ in range(100):
            response = client.get('/healthz')
            if response.status_code == 429:
                rate_limited = True
                retry_after = response.headers.get('Retry-After', '1')
                try:
                    wait_time = int(retry_after)
                except ValueError:
                    wait_time = 1
                break

    assert rate_limited, "Could not trigger rate limit for waiting test"

    # Wait for rate limit to reset (add buffer)
    time.sleep(wait_time + 0.5)

    # Now requests should succeed again
    response = client.get('/healthz')
    assert response.status_code == 200, f"Expected 200 after waiting, got {response.status_code}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
