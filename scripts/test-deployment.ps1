# Test RLaaS Deployment
# This script tests the deployed RLaaS service

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Green
Write-Host "Testing RLaaS Deployment" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

$baseUrl = "http://localhost:8000"
$testsPassed = 0
$testsFailed = 0

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Url,
        [string]$Body = $null,
        [int]$ExpectedStatus = 200
    )
    
    Write-Host "Testing: $Name..." -NoNewline
    
    try {
        $params = @{
            Uri = $Url
            Method = $Method
            UseBasicParsing = $true
            TimeoutSec = 10
        }
        
        if ($Body) {
            $params.Body = $Body
            $params.ContentType = "application/json"
        }
        
        $response = Invoke-WebRequest @params -ErrorAction Stop
        
        if ($response.StatusCode -eq $ExpectedStatus) {
            Write-Host " ✓ PASSED" -ForegroundColor Green
            $script:testsPassed++
            return $true
        }
        else {
            Write-Host " ✗ FAILED (Status: $($response.StatusCode))" -ForegroundColor Red
            $script:testsFailed++
            return $false
        }
    }
    catch {
        Write-Host " ✗ FAILED ($($_.Exception.Message))" -ForegroundColor Red
        $script:testsFailed++
        return $false
    }
}

# Test 1: Health Check
Test-Endpoint -Name "Health Check" -Method "GET" -Url "$baseUrl/health"

# Test 2: Root Endpoint
Test-Endpoint -Name "Root Endpoint" -Method "GET" -Url "$baseUrl/"

# Test 3: Metrics Endpoint
Test-Endpoint -Name "Metrics Endpoint" -Method "GET" -Url "$baseUrl/metrics"

# Test 4: Metrics Summary
Test-Endpoint -Name "Metrics Summary" -Method "GET" -Url "$baseUrl/metrics/summary"

# Test 5: Stats Endpoint
Test-Endpoint -Name "Stats Endpoint" -Method "GET" -Url "$baseUrl/stats"

# Test 6: Create Rate Limit Rule
$ruleBody = @{
    client_id = "test_user_123"
    endpoint = "/api/test"
    http_method = "GET"
    limit = 100
    window_seconds = 60
    burst = 120
} | ConvertTo-Json

Test-Endpoint -Name "Create Rate Limit Rule" -Method "POST" -Url "$baseUrl/v1/rate-limit/rules" -Body $ruleBody -ExpectedStatus 201

# Test 7: Check Rate Limit (Should be ALLOWED)
$checkBody = @{
    client_id = "test_user_123"
    endpoint = "/api/test"
    http_method = "GET"
} | ConvertTo-Json

if (Test-Endpoint -Name "Rate Limit Check (ALLOWED)" -Method "POST" -Url "$baseUrl/v1/rate-limit/check" -Body $checkBody) {
    # Parse response to verify it's allowed
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/v1/rate-limit/check" -Method POST -Body $checkBody -ContentType "application/json"
        if ($response.allowed -eq $true) {
            Write-Host "  → Request was correctly ALLOWED" -ForegroundColor Cyan
        }
        else {
            Write-Host "  → Warning: Request was BLOCKED unexpectedly" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "  → Could not parse response" -ForegroundColor Yellow
    }
}

# Test 8: Get Rule
Test-Endpoint -Name "Get Rate Limit Rule" -Method "GET" -Url "$baseUrl/v1/rate-limit/rules/test_user_123?endpoint=/api/test&http_method=GET"

# Test 9: List Rules
Test-Endpoint -Name "List Rate Limit Rules" -Method "GET" -Url "$baseUrl/v1/rate-limit/rules"

# Test 10: Get Bucket Info
Test-Endpoint -Name "Get Bucket Info" -Method "GET" -Url "$baseUrl/bucket-info/test_user_123?endpoint=/api/test&http_method=GET"

# Test 11: Multiple Rate Limit Checks (Consume tokens)
Write-Host ""
Write-Host "Testing token consumption..." -ForegroundColor Yellow
$allowedCount = 0
$blockedCount = 0

for ($i = 1; $i -le 10; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/v1/rate-limit/check" -Method POST -Body $checkBody -ContentType "application/json" -ErrorAction Stop
        if ($response.allowed) {
            $allowedCount++
        }
        else {
            $blockedCount++
        }
    }
    catch {
        $blockedCount++
    }
}

Write-Host "  → Allowed: $allowedCount, Blocked: $blockedCount" -ForegroundColor Cyan

# Test 12: Delete Rule
Test-Endpoint -Name "Delete Rate Limit Rule" -Method "DELETE" -Url "$baseUrl/v1/rate-limit/rules/test_user_123?endpoint=/api/test&http_method=GET"

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Test Summary" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Tests Passed: $testsPassed" -ForegroundColor Green
Write-Host "Tests Failed: $testsFailed" -ForegroundColor $(if ($testsFailed -eq 0) { "Green" } else { "Red" })
Write-Host ""

if ($testsFailed -eq 0) {
    Write-Host "✓ All tests passed! RLaaS is working correctly." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "✗ Some tests failed. Check the logs for details." -ForegroundColor Red
    Write-Host "Run: docker-compose logs -f" -ForegroundColor Yellow
    exit 1
}
