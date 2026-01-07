#!/bin/bash

# Health Check Script for Sonia AI Companion
# Tests various aspects of the deployed application

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
URL=${1:-"http://localhost"}
MAX_RETRIES=3
RETRY_DELAY=5

# Test results
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

log_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED_TESTS++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED_TESTS++))
}

run_test() {
    ((TOTAL_TESTS++))
}

echo "╔═══════════════════════════════════════════════════════╗"
echo "║          Sonia AI - Health Check Report              ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "Target: $URL"
echo "Time: $(date)"
echo ""

# Test 1: Server Availability
run_test
log_test "Testing server availability..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -f -s -o /dev/null -w "%{http_code}" "$URL" | grep -q "200\|301\|302"; then
        log_pass "Server is reachable (HTTP $(curl -s -o /dev/null -w "%{http_code}" "$URL"))"
        break
    else
        if [ $i -eq $MAX_RETRIES ]; then
            log_fail "Server is not reachable"
        else
            echo "Retry $i/$MAX_RETRIES in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    fi
done

# Test 2: Response Time
run_test
log_test "Testing response time..."
RESPONSE_TIME=$(curl -o /dev/null -s -w '%{time_total}' "$URL")
RESPONSE_MS=$(echo "$RESPONSE_TIME * 1000" | bc)
if (( $(echo "$RESPONSE_TIME < 2" | bc -l) )); then
    log_pass "Response time is good (${RESPONSE_MS}ms)"
else
    log_fail "Response time is slow (${RESPONSE_MS}ms)"
fi

# Test 3: HTML Content
run_test
log_test "Testing HTML content..."
if curl -s "$URL" | grep -q "Sonia"; then
    log_pass "HTML content contains expected text"
else
    log_fail "HTML content does not contain expected text"
fi

# Test 4: JavaScript Bundle
run_test
log_test "Testing JavaScript bundle..."
if curl -s "$URL" | grep -q "<script"; then
    log_pass "JavaScript bundle is present"
else
    log_fail "JavaScript bundle is missing"
fi

# Test 5: HTTPS/SSL (if applicable)
if [[ $URL == https://* ]]; then
    run_test
    log_test "Testing SSL certificate..."
    if curl -s -o /dev/null -w "%{ssl_verify_result}" "$URL" | grep -q "0"; then
        log_pass "SSL certificate is valid"
    else
        log_fail "SSL certificate is invalid"
    fi
fi

# Test 6: Security Headers
run_test
log_test "Testing security headers..."
HEADERS=$(curl -s -I "$URL")
if echo "$HEADERS" | grep -qi "x-frame-options\|x-content-type-options"; then
    log_pass "Security headers are present"
else
    log_fail "Security headers are missing"
fi

# Test 7: Gzip Compression
run_test
log_test "Testing gzip compression..."
if curl -s -H "Accept-Encoding: gzip" -I "$URL" | grep -qi "content-encoding: gzip"; then
    log_pass "Gzip compression is enabled"
else
    log_fail "Gzip compression is not enabled"
fi

# Test 8: Cache Headers
run_test
log_test "Testing cache headers..."
if curl -s -I "$URL" | grep -qi "cache-control"; then
    log_pass "Cache headers are present"
else
    log_fail "Cache headers are missing"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════════"
echo "                     SUMMARY                            "
echo "═══════════════════════════════════════════════════════"
echo "Total Tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✓ All health checks passed!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some health checks failed!${NC}"
    exit 1
fi
