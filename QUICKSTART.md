# RLaaS Quick Start Guide

This guide will get you up and running with RLaaS in under 5 minutes.

## Prerequisites

- Docker and Docker Compose installed
- At least 1GB RAM available
- Ports 8000 and 6379 available

## Quick Start (Development)

### 1. Clone and Start

```bash
# Navigate to the project directory
cd rlaas

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f
```

### 2. Verify Deployment

```bash
# Check health
curl http://localhost:8000/health

# Expected response:
# {"service":"rlaas_container","status":"healthy",...}
```

### 3. Test Rate Limiting

```bash
# Create a rate limit rule (100 requests per 60 seconds)
curl -X POST http://localhost:8000/v1/rate-limit/rules \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "user_123",
    "endpoint": "/api/orders",
    "http_method": "POST",
    "limit": 100,
    "window_seconds": 60,
    "burst": 120
  }'

# Check rate limit (should be ALLOWED)
curl -X POST http://localhost:8000/v1/rate-limit/check \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "user_123",
    "endpoint": "/api/orders",
    "http_method": "POST"
  }'

# Expected response:
# {"allowed":true,"remaining_tokens":119,"reset_after_ms":...}
```

### 4. View Metrics

```bash
# Prometheus metrics
curl http://localhost:8000/metrics

# Metrics summary (JSON)
curl http://localhost:8000/metrics/summary
```

## Production Deployment

### 1. Use Production Configuration

```bash
# Start with production settings
docker-compose -f docker-compose.prod.yml up -d

# Scale the application (3 instances)
docker-compose -f docker-compose.prod.yml up -d --scale rlaas=3
```

### 2. Configure Environment Variables

Create a `.env` file:

```bash
# Server Configuration
RLAAS_SERVER_HOST=0.0.0.0
RLAAS_SERVER_PORT=8000
RLAAS_SERVER_WORKERS=4
RLAAS_SERVER_LOG_LEVEL=INFO

# Redis Configuration
RLAAS_REDIS_HOST=redis
RLAAS_REDIS_PORT=6379
RLAAS_REDIS_PASSWORD=your_secure_password

# Circuit Breaker
RLAAS_REDIS_CIRCUIT_BREAKER_ENABLED=true
RLAAS_REDIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
RLAAS_REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=30

# Default Rate Limits
RLAAS_DEFAULT_RULES_LIMIT=1000
RLAAS_DEFAULT_RULES_WINDOW_SECONDS=3600
RLAAS_DEFAULT_RULES_BURST=1200

# Security
RLAAS_SECURITY_CORS_ENABLED=true
RLAAS_SECURITY_CORS_ORIGINS=["https://yourdomain.com"]
```

Then start with:

```bash
docker-compose -f docker-compose.prod.yml --env-file .env up -d
```

## Common Operations

### View Logs

```bash
# All services
docker-compose logs -f

# Just RLaaS
docker-compose logs -f rlaas

# Just Redis
docker-compose logs -f redis
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart just RLaaS
docker-compose restart rlaas
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v
```

### Update Application

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose up -d --build
```

## Monitoring

### Health Check

```bash
curl http://localhost:8000/health | jq
```

### Service Statistics

```bash
curl http://localhost:8000/stats | jq
```

### Check Specific Bucket

```bash
curl "http://localhost:8000/bucket-info/user_123?endpoint=/api/orders&http_method=POST" | jq
```

## Troubleshooting

### Redis Connection Issues

```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connectivity
docker exec rlaas-redis redis-cli ping
# Should return: PONG

# Check Redis logs
docker-compose logs redis
```

### Application Not Starting

```bash
# Check application logs
docker-compose logs rlaas

# Check if port is already in use
netstat -an | grep 8000

# Restart with fresh build
docker-compose down
docker-compose up -d --build
```

### Circuit Breaker Open

```bash
# Check health status
curl http://localhost:8000/health

# Wait for recovery timeout (default 30s)
# Or restart Redis
docker-compose restart redis
```

## Performance Testing

### Simple Load Test

```bash
# Install Apache Bench (if not installed)
# Ubuntu/Debian: apt-get install apache2-utils
# macOS: brew install httpd

# Test rate limit check endpoint
ab -n 1000 -c 10 -p request.json -T application/json \
  http://localhost:8000/v1/rate-limit/check
```

Create `request.json`:
```json
{
  "client_id": "test_user",
  "endpoint": "/api/test",
  "http_method": "GET"
}
```

## Next Steps

- Read [DEPLOYMENT.md](DEPLOYMENT.md) for advanced deployment options
- Read [CONFIG.md](CONFIG.md) for detailed configuration options
- Set up monitoring with Prometheus and Grafana
- Configure load balancer for production traffic
- Set up backup strategy for Redis data

## Support

For issues or questions:
1. Check the logs: `docker-compose logs -f`
2. Review [DEPLOYMENT.md](DEPLOYMENT.md) troubleshooting section
3. Check Redis connectivity and circuit breaker status
