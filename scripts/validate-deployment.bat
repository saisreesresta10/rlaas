@echo off
REM RLaaS Deployment Validation Script for Windows
REM This script validates that RLaaS is properly deployed and functioning

setlocal enabledelayedexpansion

REM Configuration
if "%RLAAS_URL%"=="" set RLAAS_URL=http://localhost:8000
set BASE_URL=%RLAAS_URL%
set TIMEOUT=30
set RETRY_COUNT=5

REM Counters
set PASSED=0
set FAILED=0

echo [INFO] Starting RLaaS deployment validation...
echo [INFO] Target URL: %BASE_URL%
echo.

REM Wait for service to be ready
echo [INFO] Waiting for RLaaS service to be ready...
for /L %%i in (1,1,%RETRY_COUNT%) do (
    curl -f -s "%BASE_URL%/health" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [INFO] Service is ready!
        goto :service_ready
    )
    echo [WARN] Attempt %%i/%RETRY_COUNT% failed, retrying in 5 seconds...
    timeout /t 5 /nobreak >nul
)

echo [ERROR] Service failed to become ready after %RETRY_COUNT% attempts
exit /b 1

:service_ready

REM Test health endpoint
echo [INFO] Testing health endpoint...
curl -s -w "%%{http_code}" "%BASE_URL%/health" > temp_response.txt
if !errorlevel! equ 0 (
    for /f %%a in (temp_response.txt) do set response=%%a
    set http_code=!response:~-3!
    
    if "!http_code!"=="200" (
        echo [INFO] Health check passed ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else (
        echo [ERROR] Health check failed ^(HTTP !http_code!^)
        set /a FAILED+=1
    )
) else (
    echo [ERROR] Health check request failed
    set /a FAILED+=1
)
del temp_response.txt >nul 2>&1
echo.

REM Test rate limiting functionality
echo [INFO] Testing rate limiting functionality...
echo {"client_id":"test-client","endpoint":"/api/test","http_method":"GET"} > temp_payload.json
curl -s -w "%%{http_code}" -X POST -H "Content-Type: application/json" -d @temp_payload.json "%BASE_URL%/v1/rate-limit/check" > temp_response.txt
if !errorlevel! equ 0 (
    for /f %%a in (temp_response.txt) do set response=%%a
    set http_code=!response:~-3!
    
    if "!http_code!"=="200" (
        echo [INFO] Rate limit check passed ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else (
        echo [ERROR] Rate limit check failed ^(HTTP !http_code!^)
        set /a FAILED+=1
    )
) else (
    echo [ERROR] Rate limit check request failed
    set /a FAILED+=1
)
del temp_payload.json >nul 2>&1
del temp_response.txt >nul 2>&1
echo.

REM Test metrics endpoint
echo [INFO] Testing metrics endpoint...
curl -s -w "%%{http_code}" "%BASE_URL%/metrics" > temp_response.txt
if !errorlevel! equ 0 (
    for /f %%a in (temp_response.txt) do set response=%%a
    set http_code=!response:~-3!
    
    if "!http_code!"=="200" (
        echo [INFO] Metrics endpoint accessible ^(HTTP !http_code!^)
        
        REM Check for expected metrics
        findstr "rlaas_requests_total" temp_response.txt >nul
        if !errorlevel! equ 0 (
            echo [INFO] Found expected metrics
            set /a PASSED+=1
        ) else (
            echo [WARN] Expected metrics not found
            set /a FAILED+=1
        )
    ) else (
        echo [ERROR] Metrics endpoint failed ^(HTTP !http_code!^)
        set /a FAILED+=1
    )
) else (
    echo [ERROR] Metrics endpoint request failed
    set /a FAILED+=1
)
del temp_response.txt >nul 2>&1
echo.

REM Test rule management
echo [INFO] Testing rule management...
echo {"client_id":"test-client-rule","endpoint":"/api/test","http_method":"GET","limit":100,"window_seconds":3600,"burst":120} > temp_rule.json
curl -s -w "%%{http_code}" -X POST -H "Content-Type: application/json" -d @temp_rule.json "%BASE_URL%/v1/rate-limit/rules" > temp_response.txt
if !errorlevel! equ 0 (
    for /f %%a in (temp_response.txt) do set response=%%a
    set http_code=!response:~-3!
    
    if "!http_code!"=="200" (
        echo [INFO] Rule creation passed ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else if "!http_code!"=="201" (
        echo [INFO] Rule creation passed ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else (
        echo [ERROR] Rule creation failed ^(HTTP !http_code!^)
        set /a FAILED+=1
    )
) else (
    echo [ERROR] Rule creation request failed
    set /a FAILED+=1
)
del temp_rule.json >nul 2>&1
del temp_response.txt >nul 2>&1
echo.

REM Test error handling
echo [INFO] Testing error handling...
echo {"invalid":"request"} > temp_invalid.json
curl -s -w "%%{http_code}" -X POST -H "Content-Type: application/json" -d @temp_invalid.json "%BASE_URL%/v1/rate-limit/check" > temp_response.txt
if !errorlevel! equ 0 (
    for /f %%a in (temp_response.txt) do set response=%%a
    set http_code=!response:~-3!
    
    if "!http_code!"=="400" (
        echo [INFO] Error handling works correctly ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else if "!http_code!"=="422" (
        echo [INFO] Error handling works correctly ^(HTTP !http_code!^)
        set /a PASSED+=1
    ) else (
        echo [ERROR] Unexpected response to invalid request ^(HTTP !http_code!^)
        set /a FAILED+=1
    )
) else (
    echo [ERROR] Error handling test request failed
    set /a FAILED+=1
)
del temp_invalid.json >nul 2>&1
del temp_response.txt >nul 2>&1
echo.

REM Performance test
echo [INFO] Running basic performance test...
set start_time=%time%
for /L %%i in (1,1,10) do (
    curl -s -f "%BASE_URL%/health" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Performance test failed on request %%i
        set /a FAILED+=1
        goto :skip_perf
    )
)
set end_time=%time%
echo [INFO] Performance test completed: 10 requests
set /a PASSED+=1

:skip_perf
echo.

REM Summary
set /a TOTAL=PASSED+FAILED
echo [INFO] Validation Summary:
echo [INFO]   Total tests: %TOTAL%
echo [INFO]   Passed: %PASSED%
echo [INFO]   Failed: %FAILED%
echo.

if %FAILED% equ 0 (
    echo [INFO] All validation tests passed! RLaaS is ready for use.
    exit /b 0
) else (
    echo [ERROR] %FAILED% test^(s^) failed. Please review the deployment.
    exit /b 1
)