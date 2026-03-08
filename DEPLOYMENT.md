# RLaaS Deployment Guide

This guide covers deploying the Rate Limiting as a Service (RLaaS) application in various environments.

## Quick Start with Docker Compose

### Prerequisites

- Docker and Docker Compose installed
- At least 1GB RAM available
- Port 8000 and 6379 available

### Development Deployment

```bash
# Clone the repository
git clone <repository-url>
cd rlaas

# Start services
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

### Production Deployment

```bash
# Use production configuration
docker-compose -f docker-compose.prod.yml up -d

# Scale the application
docker-compose -f docker-compose.prod.yml up -d --scale rlaas=3
```

## Environment Variables

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RLAAS_SERVER_HOST` | `0.0.0.0` | Server bind address |
| `RLAAS_SERVER_PORT` | `8000` | Server port |
| `RLAAS_SERVER_WORKERS` | `1` | Number of worker processes |
| `RLAAS_SERVER_RELOAD` | `false` | Enable auto-reload (dev only) |
| `RLAAS_SERVER_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

### Redis Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RLAAS_REDIS_HOST` | `localhost` | Redis server host |
| `RLAAS_REDIS_PORT` | `6379` | Redis server port |
| `RLAAS_REDIS_DB` | `0` | Redis database number |
| `RLAAS_REDIS_PASSWORD` | `""` | Redis password (if required) |
| `RLAAS_REDIS_SSL` | `false` | Enable SSL connection |
| `RLAAS_REDIS_POOL_SIZE` | `10` | Connection pool size |
| `RLAAS_REDIS_TIMEOUT` | `5.0` | Connection timeout (seconds) |

### Circuit Breaker Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RLAAS_REDIS_CIRCUIT_BREAKER_ENABLED` | `true` | Enable circuit breaker |
| `RLAAS_REDIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Failures before opening |
| `RLAAS_REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT` | `30` | Recovery timeout (seconds) |
| `RLAAS_REDIS_CIRCUIT_BREAKER_SUCCESS_THRESHOLD` | `3` | Successes to close |
| `RLAAS_REDIS_CIRCUIT_BREAKER_TIMEOUT` | `0.2` | Operation timeout (seconds) |

### Default Rate Limiting Rules

| Variable | Default | Description |
|----------|---------|-------------|
| `RLAAS_DEFAULT_RULES_LIMIT` | `100` | Default requests per window |
| `RLAAS_DEFAULT_RULES_WINDOW_SECONDS` | `3600` | Default window size (seconds) |
| `RLAAS_DEFAULT_RULES_BURST` | `120` | Default burst capacity |

### Observability Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RLAAS_METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `RLAAS_SECURITY_CORS_ENABLED` | `true` | Enable CORS |
| `RLAAS_SECURITY_CORS_ORIGINS` | `["*"]` | Allowed CORS origins |

## Deployment Scenarios

### 1. Single Node Deployment

For small to medium workloads:

```yaml
# docker-compose.yml
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    
  rlaas:
    build: .
    ports:
      - "8000:8000"
    environment:
      - RLAAS_REDIS_HOST=redis
      - RLAAS_SERVER_WORKERS=2
```

### 2. High Availability Deployment

For production workloads with redundancy:

```yaml
# docker-compose.ha.yml
version: '3.8'
services:
  redis-master:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    
  redis-replica:
    image: redis:7-alpine
    command: redis-server --replicaof redis-master 6379
    
  rlaas:
    build: .
    deploy:
      replicas: 3
    environment:
      - RLAAS_REDIS_HOST=redis-master
      - RLAAS_SERVER_WORKERS=4
```

### 3. Kubernetes Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rlaas
spec:
  replicas: 3
  selector:
    matchLabels:
      app: rlaas
  template:
    metadata:
      labels:
        app: rlaas
    spec:
      containers:
      - name: rlaas
        image: rlaas:latest
        ports:
        - containerPort: 8000
        env:
        - name: RLAAS_REDIS_HOST
          value: "redis-service"
        - name: RLAAS_SERVER_WORKERS
          value: "4"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

## Health Checks and Monitoring

### Health Check Endpoint

```bash
# Basic health check
curl http://localhost:8000/health

# Expected response (healthy):
{
  "service": "rlaas_container",
  "status": "healthy",
  "components": {
    "redis_state": {"status": "healthy"},
    "rule_management": {"status": "healthy"},
    "metrics": {"status": "healthy"}
  },
  "timestamp": 1234567890.0
}
```

### Metrics Endpoint

```bash
# Prometheus metrics
curl http://localhost:8000/metrics

# Metrics summary
curl http://localhost:8000/metrics/summary
```

### Key Metrics to Monitor

- `rlaas_requests_total` - Total requests processed
- `rlaas_requests_blocked_total` - Total requests blocked
- `rlaas_request_duration_seconds` - Request processing time
- `rlaas_redis_operations_total` - Redis operations count
- `rlaas_circuit_breaker_state` - Circuit breaker state

## Performance Tuning

### Redis Configuration

```bash
# redis.conf optimizations
maxmemory 1gb
maxmemory-policy allkeys-lru
tcp-keepalive 60
timeout 300
```

### Application Configuration

```bash
# High throughput settings
RLAAS_SERVER_WORKERS=4
RLAAS_REDIS_POOL_SIZE=20
RLAAS_REDIS_TIMEOUT=1.0
RLAAS_REDIS_CIRCUIT_BREAKER_TIMEOUT=0.5
```

## Security Considerations

### Network Security

- Use internal networks for Redis communication
- Enable Redis AUTH if exposed
- Configure firewall rules
- Use TLS for external connections

### Application Security

```bash
# Disable CORS in production
RLAAS_SECURITY_CORS_ENABLED=false

# Restrict CORS origins
RLAAS_SECURITY_CORS_ORIGINS='["https://yourdomain.com"]'
```

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   ```bash
   # Check Redis connectivity
   docker-compose logs redis
   redis-cli -h localhost ping
   ```

2. **High Memory Usage**
   ```bash
   # Check Redis memory usage
   redis-cli info memory
   
   # Monitor application metrics
   curl http://localhost:8000/metrics/summary
   ```

3. **Circuit Breaker Open**
   ```bash
   # Check circuit breaker status
   curl http://localhost:8000/health
   
   # Adjust thresholds if needed
   RLAAS_REDIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=10
   ```

### Log Analysis

```bash
# View application logs
docker-compose logs -f rlaas

# Filter for errors
docker-compose logs rlaas | grep ERROR

# Monitor structured logs
docker-compose logs rlaas | jq '.event_type'
```

## Backup and Recovery

### Redis Data Backup

```bash
# Create backup
docker exec rlaas-redis redis-cli BGSAVE

# Copy backup file
docker cp rlaas-redis:/data/dump.rdb ./backup/

# Restore from backup
docker cp ./backup/dump.rdb rlaas-redis:/data/
docker-compose restart redis
```

### Configuration Backup

```bash
# Backup environment configuration
cp .env .env.backup

# Backup Docker Compose files
tar -czf config-backup.tar.gz docker-compose*.yml .env*
```

## Scaling Guidelines

### Horizontal Scaling

- Scale application instances: `docker-compose up -d --scale rlaas=3`
- Use load balancer (nginx, HAProxy)
- Monitor per-instance metrics

### Vertical Scaling

- Increase worker processes: `RLAAS_SERVER_WORKERS=8`
- Increase Redis memory: `maxmemory 2gb`
- Adjust connection pools: `RLAAS_REDIS_POOL_SIZE=50`

### Performance Benchmarks

Expected performance (single instance):
- **Throughput**: 1000-5000 RPS
- **Latency**: <10ms p95
- **Memory**: 100-500MB
- **CPU**: 0.5-2 cores

## Support and Maintenance

### Regular Maintenance

1. Monitor disk usage (Redis AOF/RDB files)
2. Review error logs weekly
3. Update dependencies monthly
4. Backup configuration and data

### Upgrade Procedure

1. Test new version in staging
2. Backup current configuration
3. Deploy with rolling update
4. Verify health checks
5. Monitor metrics post-deployment