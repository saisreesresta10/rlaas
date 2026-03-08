@echo off
REM Build and run RLaaS with Docker Compose

echo Building RLaaS Docker containers...

REM Build the application
docker-compose build
if %errorlevel% neq 0 (
    echo Build failed!
    exit /b %errorlevel%
)

echo Starting RLaaS services...

REM Start services
docker-compose up -d
if %errorlevel% neq 0 (
    echo Failed to start services!
    exit /b %errorlevel%
)

echo Waiting for services to be healthy...

REM Wait for services to be ready
timeout /t 10 /nobreak > nul

REM Check health
echo Checking service health...
curl -f http://localhost:8000/health
if %errorlevel% neq 0 (
    echo Health check failed. Checking logs...
    docker-compose logs rlaas
    exit /b %errorlevel%
)

echo RLaaS is running successfully!
echo API available at: http://localhost:8000
echo Health check: http://localhost:8000/health
echo Metrics: http://localhost:8000/metrics

echo.
echo To stop services: docker-compose down
echo To view logs: docker-compose logs -f