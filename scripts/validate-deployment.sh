#!/bin/bash

# RLaaS Deployment Validation Script
# This script validates that RLaaS is properly deployed and functioning

set -e

# Configuration
BASE_URL="${RLAAS_URL:-http://localhost:8000}"
TIMEOUT=30
RETRY_COUNT=5

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for service to be ready
wait_for_service() {
    log_info "Waiting for RLaaS service to be ready..."
    
    for i in $(seq 1 $RETRY_COUNT); do
        if curl -f -s "$BASE_URL/health" > /dev/null; then
            log_info "Service is ready!"
            return 0
        fi
        
        log_warn "Attempt $i/$RETRY_COUNT failed, retrying in 5 seconds..."
        sleep 5
    done
    
    log_error "Service failed to become ready after $RETRY_COUNT attempts"
    return 1
}

# Test health endpoint
test_health() {
    log_info "Testing health endpoint..."
    
    response=$(curl -s -w "%{http_code}" "$BASE_URL/health")
    http_code="${response: -3}"
    body="${response%???}"
    
    if [ "$http_code" -eq 200 ]; then
        log_info "Health check passed (HTTP $http_code)"
        
        # Validate response structure
        if echo "$body" | jq -e '.status' > /dev/null 2>&1; then
            status=$(echo "$body" | jq -r '.status')
            log_info "Service status: $status"
            
            if [ "$status" = "healthy" ]; then
                log_info "Service is healthy"
                return 0
            else
                log_warn "Service status is not healthy: $status"
                return 1
            fi
        else
            log_error "Invalid health response format"
            return 1
        fi
    else
        log_error "Health check failed (HTTP $http_code)"
        return 1
    fi
}

# Test rate limiting functionality
test_rate_limiting() {
    log_info "Testing rate limiting functionality..."
    
    # Test allowed request
    payload='{"client_id":"test-client","endpoint":"/api/test","http_method":"GET"}'
    
    response=$(curl -s -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$BASE_URL/v1/rate-limit/check")
    
    http_code="${response: -3}"
    body="${response%???}"
    
    if [ "$http_code" -eq 200 ]; then
        log_info "Rate limit check passed (HTTP $http_code)"
        
        # Validate response structure
        if echo "$body" | jq -e '.allowed' > /dev/null 2>&1; then
            allowed=$(echo "$body" | jq -r '.allowed')
            log_info "Request allowed: $allowed"
            return 0
        else
            log_error "Invalid rate limit response format"
            return 1
        fi
    else
        log_error "Rate limit check failed (HTTP $http_code)"
        echo "Response: $body"
        return 1
    fi
}

# Test metrics endpoint
test_metrics() {
    log_info "Testing metrics endpoint..."
    
    response=$(curl -s -w "%{http_code}" "$BASE_URL/metrics")
    http_code="${response: -3}"
    body="${response%???}"
    
    if [ "$http_code" -eq 200 ]; then
        log_info "Metrics endpoint accessible (HTTP $http_code)"
        
        # Check for expected metrics
        if echo "$body" | grep -q "rlaas_requests_total"; then
            log_info "Found expected metrics"
            return 0
        else
            log_warn "Expected metrics not found"
            return 1
        fi
    else
        log_error "Metrics endpoint failed (HTTP $http_code)"
        return 1
    fi
}

# Test rule management
test_rule_management() {
    log_info "Testing rule management..."
    
    # Create a test rule
    rule_payload='{
        "client_id": "test-client-rule",
        "endpoint": "/api/test",
        "http_method": "GET",
        "limit": 100,
        "window_seconds": 3600,
        "burst": 120
    }'
    
    response=$(curl -s -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "$rule_payload" \
        "$BASE_URL/v1/rate-limit/rules")
    
    http_code="${response: -3}"
    body="${response%???}"
    
    if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 201 ]; then
        log_info "Rule creation passed (HTTP $http_code)"
        return 0
    else
        log_error "Rule creation failed (HTTP $http_code)"
        echo "Response: $body"
        return 1
    fi
}

# Test error handling
test_error_handling() {
    log_info "Testing error handling..."
    
    # Send invalid request
    response=$(curl -s -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d '{"invalid": "request"}' \
        "$BASE_URL/v1/rate-limit/check")
    
    http_code="${response: -3}"
    
    if [ "$http_code" -eq 400 ] || [ "$http_code" -eq 422 ]; then
        log_info "Error handling works correctly (HTTP $http_code)"
        return 0
    else
        log_error "Unexpected response to invalid request (HTTP $http_code)"
        return 1
    fi
}

# Performance test
test_performance() {
    log_info "Running basic performance test..."
    
    # Simple load test with curl
    start_time=$(date +%s.%N)
    
    for i in {1..10}; do
        curl -s -f "$BASE_URL/health" > /dev/null || {
            log_error "Performance test failed on request $i"
            return 1
        }
    done
    
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc)
    avg_time=$(echo "scale=3; $duration / 10" | bc)
    
    log_info "Performance test completed: 10 requests in ${duration}s (avg: ${avg_time}s per request)"
    
    # Check if average response time is reasonable (< 1 second)
    if (( $(echo "$avg_time < 1.0" | bc -l) )); then
        log_info "Performance is acceptable"
        return 0
    else
        log_warn "Performance may be degraded (avg response time: ${avg_time}s)"
        return 1
    fi
}

# Main validation function
main() {
    log_info "Starting RLaaS deployment validation..."
    log_info "Target URL: $BASE_URL"
    
    # Track test results
    passed=0
    failed=0
    
    # Run tests
    tests=(
        "wait_for_service"
        "test_health"
        "test_rate_limiting"
        "test_metrics"
        "test_rule_management"
        "test_error_handling"
        "test_performance"
    )
    
    for test in "${tests[@]}"; do
        log_info "Running $test..."
        if $test; then
            log_info "✓ $test passed"
            ((passed++))
        else
            log_error "✗ $test failed"
            ((failed++))
        fi
        echo ""
    done
    
    # Summary
    total=$((passed + failed))
    log_info "Validation Summary:"
    log_info "  Total tests: $total"
    log_info "  Passed: $passed"
    log_info "  Failed: $failed"
    
    if [ $failed -eq 0 ]; then
        log_info "🎉 All validation tests passed! RLaaS is ready for use."
        exit 0
    else
        log_error "❌ $failed test(s) failed. Please review the deployment."
        exit 1
    fi
}

# Check dependencies
check_dependencies() {
    for cmd in curl jq bc; do
        if ! command -v $cmd &> /dev/null; then
            log_error "$cmd is required but not installed"
            exit 1
        fi
    done
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --url)
            BASE_URL="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--url URL] [--timeout SECONDS]"
            echo "  --url URL        Base URL for RLaaS service (default: http://localhost:8000)"
            echo "  --timeout SEC    Timeout for requests (default: 30)"
            echo "  --help           Show this help message"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run validation
check_dependencies
main