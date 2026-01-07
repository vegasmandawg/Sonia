#!/bin/bash

# Load Test Script
# Tests application under load

set -e

URL=${1:-"http://localhost"}
CONCURRENT_USERS=${2:-10}
REQUESTS_PER_USER=${3:-100}

if ! command -v ab &> /dev/null; then
    echo "Error: Apache Bench (ab) not installed"
    echo "Install with: sudo apt-get install apache2-utils (Ubuntu)"
    echo "Or: brew install ab (macOS)"
    exit 1
fi

TOTAL_REQUESTS=$((CONCURRENT_USERS * REQUESTS_PER_USER))

echo "========================================"
echo "        LOAD TEST CONFIGURATION        "
echo "========================================"
echo "URL: $URL"
echo "Concurrent Users: $CONCURRENT_USERS"
echo "Requests per User: $REQUESTS_PER_USER"
echo "Total Requests: $TOTAL_REQUESTS"
echo "========================================"
echo ""

read -p "Start load test? (y/n): " confirm
if [ "$confirm" != "y" ]; then
    echo "Load test cancelled"
    exit 0
fi

echo ""
echo "Running load test..."
echo ""

ab -n "$TOTAL_REQUESTS" -c "$CONCURRENT_USERS" -g results.tsv "$URL/" > load-test-results.txt

echo ""
echo "========================================"
echo "        LOAD TEST RESULTS              "
echo "========================================"
cat load-test-results.txt

echo ""
echo "Full results saved to: load-test-results.txt"
echo "TSV data saved to: results.tsv"
