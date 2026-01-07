#!/bin/bash

# Performance Monitoring Script
# Tracks key metrics for deployed application

set -e

URL=${1:-"http://localhost"}
DURATION=${2:-60}  # seconds
INTERVAL=5  # seconds between checks

echo "Monitoring $URL for ${DURATION}s..."
echo ""

# Arrays to store metrics
declare -a response_times
declare -a status_codes

start_time=$(date +%s)
end_time=$((start_time + DURATION))

while [ $(date +%s) -lt $end_time ]; do
    # Measure response time and status
    response_time=$(curl -o /dev/null -s -w '%{time_total}' "$URL" 2>/dev/null || echo "999")
    status_code=$(curl -o /dev/null -s -w '%{http_code}' "$URL" 2>/dev/null || echo "000")
    
    response_times+=("$response_time")
    status_codes+=("$status_code")
    
    # Real-time output
    response_ms=$(echo "$response_time * 1000" | bc 2>/dev/null || echo "N/A")
    echo "[$(date +%H:%M:%S)] Status: $status_code | Response: ${response_ms}ms"
    
    sleep $INTERVAL
done

echo ""
echo "========== MONITORING SUMMARY =========="

# Calculate statistics
total_requests=${#response_times[@]}
successful_requests=0
failed_requests=0

for status in "${status_codes[@]}"; do
    if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
        ((successful_requests++))
    else
        ((failed_requests++))
    fi
done

# Calculate average response time
if command -v bc &> /dev/null; then
    sum=0
    for time in "${response_times[@]}"; do
        sum=$(echo "$sum + $time" | bc)
    done
    avg_response=$(echo "scale=3; $sum / $total_requests" | bc)
    avg_response_ms=$(echo "$avg_response * 1000" | bc)
    
    # Find min and max
    min_time=${response_times[0]}
    max_time=${response_times[0]}
    for time in "${response_times[@]}"; do
        if (( $(echo "$time < $min_time" | bc -l) )); then
            min_time=$time
        fi
        if (( $(echo "$time > $max_time" | bc -l) )); then
            max_time=$time
        fi
    done
    min_time_ms=$(echo "$min_time * 1000" | bc)
    max_time_ms=$(echo "$max_time * 1000" | bc)
fi

uptime_percentage=$(echo "scale=2; ($successful_requests / $total_requests) * 100" | bc 2>/dev/null || echo "N/A")

echo "Total Requests: $total_requests"
echo "Successful: $successful_requests (${uptime_percentage}%)"
echo "Failed: $failed_requests"
echo "Average Response Time: ${avg_response_ms}ms"
echo "Min Response Time: ${min_time_ms}ms"
echo "Max Response Time: ${max_time_ms}ms"
echo "========================================"

if [ $failed_requests -gt 0 ]; then
    echo "⚠️  Warning: Some requests failed!"
    exit 1
else
    echo "✅ All requests successful!"
    exit 0
fi
