# Quick Start Script for RLaaS
# This script provides an interactive menu for common operations

param(
    [switch]$AutoDeploy
)

$ErrorActionPreference = "Stop"

function Show-Menu {
    Clear-Host
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "   RLaaS - Rate Limiter as a Service   " -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. Deploy RLaaS (Development)" -ForegroundColor Green
    Write-Host "2. Deploy RLaaS (Production)" -ForegroundColor Green
    Write-Host "3. Test Deployment" -ForegroundColor Yellow
    Write-Host "4. View Logs" -ForegroundColor Yellow
    Write-Host "5. Check Health" -ForegroundColor Yellow
    Write-Host "6. Stop Services" -ForegroundColor Red
    Write-Host "7. Restart Services" -ForegroundColor Yellow
    Write-Host "8. Clean Up (Remove all containers and volumes)" -ForegroundColor Red
    Write-Host "9. View Documentation" -ForegroundColor Cyan
    Write-Host "0. Exit" -ForegroundColor Gray
    Write-Host ""
}

function Deploy-Development {
    Write-Host "Deploying RLaaS in Development mode..." -ForegroundColor Green
    .\scripts\deploy.ps1 -Environment development
}

function Deploy-Production {
    Write-Host "Deploying RLaaS in Production mode..." -ForegroundColor Green
    .\scripts\deploy.ps1 -Environment production
}

function Test-Deployment {
    Write-Host "Testing RLaaS deployment..." -ForegroundColor Yellow
    .\scripts\test-deployment.ps1
}

function Show-Logs {
    Write-Host "Showing logs (Press Ctrl+C to exit)..." -ForegroundColor Yellow
    docker-compose logs -f
}

function Check-Health {
    Write-Host "Checking RLaaS health..." -ForegroundColor Yellow
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5
        Write-Host ""
        Write-Host "Service Status: $($health.status)" -ForegroundColor $(if ($health.status -eq "healthy") { "Green" } else { "Red" })
        Write-Host ""
        Write-Host "Components:" -ForegroundColor Cyan
        $health.components.PSObject.Properties | ForEach-Object {
            $status = if ($_.Value.status) { $_.Value.status } else { $_.Value }
            $color = if ($status -eq "healthy") { "Green" } else { "Yellow" }
            Write-Host "  - $($_.Name): $status" -ForegroundColor $color
        }
        Write-Host ""
    }
    catch {
        Write-Host "Error: Could not connect to RLaaS" -ForegroundColor Red
        Write-Host "Make sure the service is running (Option 1 or 2)" -ForegroundColor Yellow
    }
}

function Stop-Services {
    Write-Host "Stopping RLaaS services..." -ForegroundColor Red
    docker-compose down
    Write-Host "Services stopped." -ForegroundColor Green
}

function Restart-Services {
    Write-Host "Restarting RLaaS services..." -ForegroundColor Yellow
    docker-compose restart
    Write-Host "Services restarted." -ForegroundColor Green
    Start-Sleep -Seconds 5
    Check-Health
}

function Clean-Up {
    Write-Host "WARNING: This will remove all containers, volumes, and data!" -ForegroundColor Red
    $confirm = Read-Host "Are you sure? (yes/no)"
    if ($confirm -eq "yes") {
        Write-Host "Cleaning up..." -ForegroundColor Red
        docker-compose down -v
        Write-Host "Cleanup complete." -ForegroundColor Green
    }
    else {
        Write-Host "Cleanup cancelled." -ForegroundColor Yellow
    }
}

function Show-Documentation {
    Write-Host ""
    Write-Host "Available Documentation:" -ForegroundColor Cyan
    Write-Host "  1. QUICKSTART.md - Get started in 5 minutes"
    Write-Host "  2. DEPLOY_GUIDE.md - Complete deployment guide"
    Write-Host "  3. CONFIG.md - Configuration reference"
    Write-Host "  4. DEPLOYMENT.md - Advanced deployment scenarios"
    Write-Host "  5. README.md - Project overview"
    Write-Host ""
    $choice = Read-Host "Enter number to open (or press Enter to skip)"
    
    switch ($choice) {
        "1" { Start-Process "QUICKSTART.md" }
        "2" { Start-Process "DEPLOY_GUIDE.md" }
        "3" { Start-Process "CONFIG.md" }
        "4" { Start-Process "DEPLOYMENT.md" }
        "5" { Start-Process "README.md" }
    }
}

# Auto-deploy if flag is set
if ($AutoDeploy) {
    Deploy-Development
    exit 0
}

# Main menu loop
while ($true) {
    Show-Menu
    $choice = Read-Host "Select an option"
    
    switch ($choice) {
        "1" { Deploy-Development; Read-Host "Press Enter to continue" }
        "2" { Deploy-Production; Read-Host "Press Enter to continue" }
        "3" { Test-Deployment; Read-Host "Press Enter to continue" }
        "4" { Show-Logs }
        "5" { Check-Health; Read-Host "Press Enter to continue" }
        "6" { Stop-Services; Read-Host "Press Enter to continue" }
        "7" { Restart-Services; Read-Host "Press Enter to continue" }
        "8" { Clean-Up; Read-Host "Press Enter to continue" }
        "9" { Show-Documentation; Read-Host "Press Enter to continue" }
        "0" { Write-Host "Goodbye!" -ForegroundColor Cyan; exit 0 }
        default { Write-Host "Invalid option. Please try again." -ForegroundColor Red; Start-Sleep -Seconds 2 }
    }
}
