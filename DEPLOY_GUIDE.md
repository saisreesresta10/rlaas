# Complete RLaaS Deployment Guide

This comprehensive guide covers everything you need to deploy RLaaS from development to production.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (5 Minutes)](#quick-start-5-minutes)
3. [Development Deployment](#development-deployment)
4. [Production Deployment](#production-deployment)
5. [Cloud Deployment](#cloud-deployment)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
  - Download: https://docs.docker.com/get-docker/
  - Minimum version: 20.10+
  
- **Docker Compose**
  - Usually included with Docker Desktop
  - Minimum version: 2.0+

### System Requirements

- **RAM**: Minimum 2GB, Recommended 4GB+
- **CPU**: 2+ cores recommended
- **Disk**: 2GB free space
- **Ports**: 8000 (API), 6379 (Redis)

### Verify Installation

```powershell
# Check Docker
docker --version
# Expected: Docker version 20.10.x or higher

# Check Docker Compose
docker-compose --version
# Expected: Docker Compose version 2.x.x or higher
```

---

## Quick Start (5 Minutes)

### Option 1: Automated Deployment (Windows)

```powershell
# Navigate to project directory
cd path\to\rlaas

# Run deployment script
.\scripts\deploy.ps1

# Test the deployment
.\scripts\test-deployment.ps1
```

### Option 2: Manual Deployment

```powershell
# 1. Start services
docker-compose up -d

# 2. Check health
Start-Sleep -Seconds 10
Invoke-WebRequest http://localhost:8000/health

# 3. View logs
docker-compose logs -f
```

### Verify Deployment

```powershell
# Health check
curl http://localhost:8000/health

# Create a test rule
$body = @{
    client_id = "test_user"
    endpoint = "/api/test"
    http_method = "GET"
    limit = 100
    window_seconds = 60
    burst = 120
} | ConvertTo-Json

Invoke-WebRequest -Uri http://localhost:8000/v1/rate-limit/rules `
    -Method POST -Body $body -ContentType "application/json"

# Test rate limiting
$checkBody = @{
    client_id = "test_user"
    endpoint = "/api/test"
    http_method = "GET"
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8000/v1/rate-limit/check `
    -Method POST -Body $checkBody -ContentType "application/json"
```

---

## Development Deployment

### Step 1: Clone and Configure

```powershell
# Clone repository (if not already done)
git clone <repository-url>
cd rlaas

# Copy environment template
Copy-Item .env.example .env

# Edit .env for development
notepad .env
```

### Step 2: Start Services

```powershell
# Start in detached mode
docker-compose up -d

# Or start with logs visible
docker-compose up
```

### Step 3: Access Services

- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Metrics**: http://localhost:8000/metrics
- **Redis**: localhost:6379

### Development Configuration

Edit `.env` for development:

```env
RLAAS_SERVER_RELOAD=true
RLAAS_SERVER_LOG_LEVEL=DEBUG
RLAAS_SECURITY_CORS_ORIGINS=["*"]
RLAAS_SERVER_WORKERS=1
```

### Hot Reload

For code changes without rebuilding:

```powershell
# Mount code as volume (edit docker-compose.yml)
# Add under rlaas service:
volumes:
  - ./rlaas:/app/rlaas

# Restart with reload enabled
docker-compose restart rlaas
```

---

## Production Deployment

### Step 1: Production Configuration

```powershell
# Copy and edit production environment
Copy-Item .env.example .env.production
notepad .env.production
```

**Production `.env.production`:**

```env
# Server - Production Settings
RLAAS_SERVER_HOST=0.0.0.0
RLAAS_SERVER_PORT=8000
RLAAS_SERVER_WORKERS=8
RLAAS_SERVER_LOG_LEVEL=INFO
RLAAS_SERVER_RELOAD=false

# Redis - Secure Configuration
RLAAS_REDIS_HOST=redis
RLAAS_REDIS_PORT=6379
RLAAS_REDIS_PASSWORD=YOUR_SECURE_PASSWORD_HERE
RLAAS_REDIS_SOCKET_TIMEOUT=5.0

# Circuit Breaker - Stricter Settings
RLAAS_REDIS_CIRCUIT_BREAKER_ENABLED=true
RLAAS_REDIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3
RLAAS_REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60.0

# Default Rules - Production Limits
RLAAS_DEFAULT_RULES_LIMIT=1000
RLAAS_DEFAULT_RULES_WINDOW_SECONDS=3600
RLAAS_DEFAULT_RULES_BURST=1200

# Security - Restrict CORS
RLAAS_SECURITY_CORS_ENABLED=true
RLAAS_SECURITY_CORS_ORIGINS=["https://yourdomain.com","https://api.yourdomain.com"]
RLAAS_SECURITY_CORS_METHODS=["GET","POST","PUT","DELETE"]
```

### Step 2: Deploy with Production Config

```powershell
# Deploy with production compose file
docker-compose -f docker-compose.prod.yml --env-file .env.production up -d

# Or use deployment script
.\scripts\deploy.ps1 -Environment production
```

### Step 3: Scale Services

```powershell
# Scale RLaaS instances
docker-compose -f docker-compose.prod.yml up -d --scale rlaas=3

# Verify scaling
docker-compose -f docker-compose.prod.yml ps
```

### Step 4: Setup Load Balancer

For multiple instances, use a load balancer (nginx, HAProxy, or cloud LB):

**nginx.conf example:**

```nginx
upstream rlaas_backend {
    least_conn;
    server localhost:8001;
    server localhost:8002;
    server localhost:8003;
}

server {
    listen 80;
    server_name rlaas.yourdomain.com;

    location / {
        proxy_pass http://rlaas_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Cloud Deployment

### AWS Deployment

#### Option 1: ECS (Elastic Container Service)

```powershell
# 1. Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

docker build -t rlaas .
docker tag rlaas:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/rlaas:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/rlaas:latest

# 2. Create ECS task definition (use AWS Console or CLI)
# 3. Create ECS service with Application Load Balancer
# 4. Use ElastiCache for Redis
```

#### Option 2: EC2 with Docker

```bash
# SSH into EC2 instance
ssh -i your-key.pem ec2-user@your-instance-ip

# Install Docker
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Clone and deploy
git clone <repository-url>
cd rlaas
docker-compose -f docker-compose.prod.yml up -d
```

### Azure Deployment

#### Azure Container Instances

```powershell
# Login to Azure
az login

# Create resource group
az group create --name rlaas-rg --location eastus

# Create container registry
az acr create --resource-group rlaas-rg --name rlaasregistry --sku Basic

# Build and push
az acr build --registry rlaasregistry --image rlaas:latest .

# Deploy container
az container create `
    --resource-group rlaas-rg `
    --name rlaas-app `
    --image rlaasregistry.azurecr.io/rlaas:latest `
    --dns-name-label rlaas-app `
    --ports 8000 `
    --environment-variables `
        RLAAS_REDIS_HOST=your-redis-host `
        RLAAS_REDIS_PASSWORD=your-password
```

### Google Cloud Platform

#### Cloud Run

```bash
# Build and push to GCR
gcloud builds submit --tag gcr.io/PROJECT-ID/rlaas

# Deploy to Cloud Run
gcloud run deploy rlaas \
    --image gcr.io/PROJECT-ID/rlaas \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --set-env-vars RLAAS_REDIS_HOST=your-redis-host
```

---

## Monitoring & Maintenance

### Health Monitoring

```powershell
# Check health status
Invoke-RestMethod http://localhost:8000/health | ConvertTo-Json

# Monitor continuously
while ($true) {
    $health = Invoke-RestMethod http://localhost:8000/health
    Write-Host "Status: $($health.status)" -ForegroundColor $(if ($health.status -eq "healthy") { "Green" } else { "Red" })
    Start-Sleep -Seconds 30
}
```

### Prometheus Integration

**prometheus.yml:**

```yaml
scrape_configs:
  - job_name: 'rlaas'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Grafana Dashboard

Import metrics from Prometheus:

- Request rate: `rate(rlaas_requests_total[5m])`
- Error rate: `rate(rlaas_requests_total{result="error"}[5m])`
- Latency: `histogram_quantile(0.95, rlaas_request_duration_seconds_bucket)`
- Circuit breaker state: `rlaas_circuit_breaker_state`

### Log Management

```powershell
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f rlaas

# View last 100 lines
docker-compose logs --tail=100 rlaas

# Export logs
docker-compose logs --no-color > rlaas-logs.txt
```

### Backup Strategy

```powershell
# Backup Redis data
docker exec rlaas-redis redis-cli BGSAVE

# Copy backup file
docker cp rlaas-redis:/data/dump.rdb ./backups/dump-$(Get-Date -Format 'yyyyMMdd-HHmmss').rdb

# Automated backup script
$backupDir = ".\backups"
New-Item -ItemType Directory -Force -Path $backupDir
docker exec rlaas-redis redis-cli BGSAVE
Start-Sleep -Seconds 5
docker cp rlaas-redis:/data/dump.rdb "$backupDir\dump-$(Get-Date -Format 'yyyyMMdd-HHmmss').rdb"
```

### Updates and Upgrades

```powershell
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Verify health
Start-Sleep -Seconds 10
Invoke-WebRequest http://localhost:8000/health
```

---

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

```powershell
# Find process using port 8000
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
Get-Process -Id <ProcessId>

# Kill the process or change port in .env
$env:RLAAS_SERVER_PORT=8001
```

#### 2. Redis Connection Failed

```powershell
# Check Redis is running
docker-compose ps redis

# Test Redis connectivity
docker exec rlaas-redis redis-cli ping
# Should return: PONG

# Check Redis logs
docker-compose logs redis

# Restart Redis
docker-compose restart redis
```

#### 3. Circuit Breaker Open

```powershell
# Check circuit breaker status
$health = Invoke-RestMethod http://localhost:8000/health
$health.components.circuit_breaker

# Wait for recovery timeout (default 30s) or restart Redis
docker-compose restart redis
```

#### 4. High Memory Usage

```powershell
# Check container stats
docker stats

# Check Redis memory
docker exec rlaas-redis redis-cli INFO memory

# Configure Redis max memory in docker-compose.yml
# command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
```

#### 5. Application Won't Start

```powershell
# Check logs for errors
docker-compose logs rlaas

# Common issues:
# - Missing environment variables
# - Redis not accessible
# - Port conflicts

# Rebuild from scratch
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

### Debug Mode

```powershell
# Enable debug logging
$env:RLAAS_SERVER_LOG_LEVEL="DEBUG"
docker-compose restart rlaas

# View detailed logs
docker-compose logs -f rlaas
```

### Performance Issues

```powershell
# Check request latency
Measure-Command {
    Invoke-RestMethod -Uri http://localhost:8000/v1/rate-limit/check `
        -Method POST -Body '{"client_id":"test","endpoint":"/api/test","http_method":"GET"}' `
        -ContentType "application/json"
}

# Monitor metrics
Invoke-RestMethod http://localhost:8000/metrics/summary | ConvertTo-Json
```

---

## Security Checklist

- [ ] Change default Redis password
- [ ] Restrict CORS origins in production
- [ ] Use HTTPS/TLS for external access
- [ ] Enable firewall rules
- [ ] Regular security updates
- [ ] Monitor access logs
- [ ] Implement rate limiting for API endpoints
- [ ] Use secrets management (AWS Secrets Manager, Azure Key Vault)
- [ ] Regular backups
- [ ] Disaster recovery plan

---

## Support

For issues or questions:

1. Check logs: `docker-compose logs -f`
2. Review health status: `curl http://localhost:8000/health`
3. Check Redis connectivity: `docker exec rlaas-redis redis-cli ping`
4. Review this troubleshooting guide
5. Check GitHub issues or create a new one

---

## Next Steps

- Set up monitoring with Prometheus and Grafana
- Configure alerting for critical metrics
- Implement automated backups
- Set up CI/CD pipeline
- Load testing and performance tuning
- Documentation for your team
