# RLaaS Deployment Script for Windows PowerShell
# This script automates the deployment process for RLaaS

param(
    [string]$Environment = "development"
)

$ErrorActionPreference = "Stop"

# Configuration
$ComposeFile = if ($Environment -eq "production") { "docker-compose.prod.yml" } else { "docker-compose.yml" }

Write-Host "========================================" -ForegroundColor Green
Write-Host "RLaaS Deployment Script" -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Function to check if Docker is installed
function Test-Docker {
    Write-Host "Checking Docker installation..." -ForegroundColor Yellow
    try {
        $null = docker --version
        Write-Host "✓ Docker is installed" -ForegroundColor Green
    }
    catch {
        Write-Host "Error: Docker is not installed" -ForegroundColor Red
        Write-Host "Please install Docker Desktop from https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }
}

# Function to check if Docker Compose is installed
function Test-DockerCompose {
    Write-Host "Checking Docker Compose installation..." -ForegroundColor Yellow
    try {
        $null = docker-compose --version
        Write-Host "✓ Docker Compose is installed" -ForegroundColor Green
    }
    catch {
        Write-Host "Error: Docker Compose is not installed" -ForegroundColor Red
        Write-Host "Please install Docker Compose"
        exit 1
    }
}

# Function to check if ports are available
function Test-Ports {
    Write-Host "Checking if required ports are available..." -ForegroundColor Yellow
    
    $port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    if ($port8000) {
        Write-Host "Warning: Port 8000 is already in use" -ForegroundColor Yellow
        Write-Host "Please stop the service using port 8000 or change RLAAS_SERVER_PORT"
    }
    
    $port6379 = Get-NetTCPConnection -LocalPort 6379 -ErrorAction SilentlyContinue
    if ($port6379) {
        Write-Host "Warning: Port 6379 is already in use" -ForegroundColor Yellow
        Write-Host "If you have Redis running locally, this is expected"
    }
    
    Write-Host "✓ Port check complete" -ForegroundColor Green
}

# Function to build Docker images
function Build-Images {
    Write-Host "Building Docker images..." -ForegroundColor Yellow
    docker-compose -f $ComposeFile build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Failed to build Docker images" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Docker images built successfully" -ForegroundColor Green
}

# Function to start services
function Start-Services {
    Write-Host "Starting services..." -ForegroundColor Yellow
    docker-compose -f $ComposeFile up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Failed to start services" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Services started" -ForegroundColor Green
}

# Function to wait for services to be healthy
function Wait-ForHealth {
    Write-Host "Waiting for services to be healthy..." -ForegroundColor Yellow
    
    $maxAttempts = 30
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host "✓ Services are healthy" -ForegroundColor Green
                return
            }
        }
        catch {
            # Service not ready yet
        }
        
        $attempt++
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    
    Write-Host ""
    Write-Host "Error: Services did not become healthy in time" -ForegroundColor Red
    Write-Host "Check logs with: docker-compose -f $ComposeFile logs"
    exit 1
}

# Function to display service information
function Show-Info {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "Deployment Successful!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Service URLs:"
    Write-Host "  - API: http://localhost:8000"
    Write-Host "  - Health Check: http://localhost:8000/health"
    Write-Host "  - Metrics: http://localhost:8000/metrics"
    Write-Host "  - API Docs: http://localhost:8000/docs"
    Write-Host ""
    Write-Host "Useful Commands:"
    Write-Host "  - View logs: docker-compose -f $ComposeFile logs -f"
    Write-Host "  - Stop services: docker-compose -f $ComposeFile down"
    Write-Host "  - Restart: docker-compose -f $ComposeFile restart"
    Write-Host ""
    Write-Host "Test the service:"
    Write-Host '  Invoke-WebRequest -Uri http://localhost:8000/v1/rate-limit/check `'
    Write-Host '    -Method POST -ContentType "application/json" `'
    Write-Host '    -Body ''{"client_id":"test","endpoint":"/api/test","http_method":"GET"}'''
    Write-Host ""
}

# Main deployment flow
try {
    Test-Docker
    Test-DockerCompose
    Test-Ports
    Build-Images
    Start-Services
    Wait-ForHealth
    Show-Info
}
catch {
    Write-Host "Deployment failed: $_" -ForegroundColor Red
    exit 1
}
