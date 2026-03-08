# RLaaS Incident Response Runbook

## Overview

This runbook provides step-by-step procedures for responding to common RLaaS incidents.

## Incident Classification

### Severity Levels

- **P0 (Critical)**: Service completely down, affecting all users
- **P1 (High)**: Major functionality impaired, affecting most users  
- **P2 (Medium)**: Minor functionality impaired, affecting some users
- **P3 (Low)**: Cosmetic issues, minimal user impact

## Common Incidents

### 1. Service Completely Down (P0)

**Symptoms:**
- Health check endpoint returns 503 or times out
- All rate limit requests failing
- Application containers not running

**Response Steps:**

1. **Immediate Assessment (0-5 minutes)**
   ```bash
   # Check service status
   curl -f http://localhost:8000/health
   
   # Check container status
   docker-compose ps
   
   # Check recent logs
   docker-compose logs --tail=50 rlaas
   ```

2. **Quick Recovery Attempt (5-10 minutes)**
   ```bash
   # Restart services
   docker-compose restart rlaas
   
   # If that fails, full restart
   docker-compose down && docker-compose up -d
   
   # Verify recovery
   curl http://localhost:8000/health
   ```

3. **Root Cause Analysis (10+ minutes)**
   ```bash
   # Check system resources
   df -h
   free -m
   
   # Check Redis connectivity
   docker-compose exec redis redis-cli ping
   
   # Review error logs
   docker-compose logs rlaas | grep ERROR | tail -20
   ```

### 2. Redis Connection Issues (P1)

**Symptoms:**
- Health check shows Redis as unhealthy
- Rate limit requests timing out
- Circuit breaker in OPEN state

**Response Steps:**

1. **Check Redis Status**
   ```bash
   # Check Redis container
   docker-compose ps redis
   
   # Test Redis connectivity
   docker-compose exec redis redis-cli ping
   
   # Check Redis logs
   docker-compose logs redis --tail=20
   ```

2. **Redis Recovery**
   ```bash
   # Restart Redis if needed
   docker-compose restart redis
   
   # Check Redis memory usage
   docker-compose exec redis redis-cli info memory
   
   # Clear Redis if corrupted (CAUTION: Data loss)
   docker-compose exec redis redis-cli FLUSHALL
   ```

3. **Circuit Breaker Reset**
   ```bash
   # Wait for circuit breaker recovery (default 30s)
   # Or restart application to reset immediately
   docker-compose restart rlaas
   ```

### 3. High Error Rate (P1-P2)

**Symptoms:**
- Increased 5xx responses
- High error metrics in monitoring
- Users reporting failures

**Response Steps:**

1. **Identify Error Pattern**
   ```bash
   # Check error logs
   docker-compose logs rlaas | grep ERROR | tail -50
   
   # Check metrics
   curl http://localhost:8000/metrics/summary
   
   # Check specific endpoints
   curl -v http://localhost:8000/v1/rate-limit/check
   ```

2. **Common Error Resolutions**
   
   **Validation Errors:**
   ```bash
   # Check for malformed requests in logs
   docker-compose logs rlaas | grep "validation_error"
   ```
   
   **Redis Timeouts:**
   ```bash
   # Increase timeout temporarily
   docker-compose exec rlaas env RLAAS_REDIS_CIRCUIT_BREAKER_TIMEOUT=1.0
   ```
   
   **Memory Issues:**
   ```bash
   # Check memory usage
   docker stats
   
   # Restart if memory leak suspected
   docker-compose restart rlaas
   ```

### 4. Performance Degradation (P2)

**Symptoms:**
- Slow response times
- High CPU/memory usage
- Timeouts under load

**Response Steps:**

1. **Performance Analysis**
   ```bash
   # Check resource usage
   docker stats
   
   # Check request latency metrics
   curl http://localhost:8000/metrics | grep duration
   
   # Check Redis performance
   docker-compose exec redis redis-cli --latency
   ```

2. **Immediate Mitigation**
   ```bash
   # Scale up application instances
   docker-compose up -d --scale rlaas=3
   
   # Increase worker processes (if single instance)
   # Edit docker-compose.yml: RLAAS_SERVER_WORKERS=4
   docker-compose up -d
   ```

3. **Long-term Optimization**
   - Review and optimize Redis configuration
   - Analyze slow queries in logs
   - Consider horizontal scaling

### 5. Circuit Breaker Stuck Open (P2)

**Symptoms:**
- All requests failing with circuit breaker errors
- Health check shows circuit breaker as OPEN
- Redis is actually healthy

**Response Steps:**

1. **Verify Redis Health**
   ```bash
   # Test Redis directly
   docker-compose exec redis redis-cli ping
   docker-compose exec redis redis-cli info
   ```

2. **Reset Circuit Breaker**
   ```bash
   # Restart application to reset circuit breaker
   docker-compose restart rlaas
   
   # Or wait for automatic recovery (default 30s)
   ```

3. **Adjust Circuit Breaker Settings**
   ```bash
   # Increase failure threshold if too sensitive
   # Edit docker-compose.yml:
   # RLAAS_REDIS_CIRCUIT_BREAKER_FAILURE_THRESHOLD=10
   docker-compose up -d
   ```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Service Health**
   - Health check endpoint status
   - Container uptime
   - Response time

2. **Error Rates**
   - HTTP 5xx responses
   - Redis connection errors
   - Circuit breaker state

3. **Performance**
   - Request latency (p95, p99)
   - Throughput (RPS)
   - Resource utilization

### Alert Thresholds

```yaml
# Example alerting rules
alerts:
  - name: RLaaS Service Down
    condition: health_check_status != 200
    severity: P0
    
  - name: High Error Rate
    condition: error_rate > 5%
    severity: P1
    
  - name: High Latency
    condition: p95_latency > 100ms
    severity: P2
    
  - name: Circuit Breaker Open
    condition: circuit_breaker_state == "OPEN"
    severity: P2
```

## Communication Templates

### Incident Declaration

```
INCIDENT: RLaaS Service Impact
Severity: P[X]
Start Time: [TIMESTAMP]
Impact: [DESCRIPTION]
Status: Investigating

Initial assessment shows [SYMPTOMS].
Investigating [SUSPECTED_CAUSE].
ETA for resolution: [TIME_ESTIMATE]
```

### Status Update

```
UPDATE: RLaaS Incident
Time: [TIMESTAMP]
Status: [Investigating/Mitigating/Resolved]

Progress: [ACTIONS_TAKEN]
Next Steps: [PLANNED_ACTIONS]
ETA: [UPDATED_ESTIMATE]
```

### Resolution Notice

```
RESOLVED: RLaaS Incident
Resolution Time: [TIMESTAMP]
Duration: [TOTAL_TIME]

Root Cause: [CAUSE_DESCRIPTION]
Resolution: [ACTIONS_TAKEN]
Prevention: [PREVENTIVE_MEASURES]

Post-mortem scheduled for [DATE].
```

## Post-Incident Actions

### Immediate (0-24 hours)
1. Document incident timeline
2. Collect relevant logs and metrics
3. Implement immediate preventive measures
4. Update monitoring/alerting if needed

### Short-term (1-7 days)
1. Conduct post-mortem meeting
2. Create action items for improvements
3. Update runbooks based on learnings
4. Test incident response procedures

### Long-term (1-4 weeks)
1. Implement architectural improvements
2. Enhance monitoring and alerting
3. Update documentation
4. Conduct incident response training

## Emergency Contacts

```
Primary On-Call: [CONTACT_INFO]
Secondary On-Call: [CONTACT_INFO]
Engineering Manager: [CONTACT_INFO]
Infrastructure Team: [CONTACT_INFO]
```

## Useful Commands Reference

```bash
# Quick health check
curl -f http://localhost:8000/health

# Service status
docker-compose ps

# Recent logs
docker-compose logs --tail=50 rlaas

# Error logs only
docker-compose logs rlaas | grep ERROR

# Restart services
docker-compose restart

# Scale up
docker-compose up -d --scale rlaas=3

# Resource usage
docker stats

# Redis health
docker-compose exec redis redis-cli ping

# Metrics
curl http://localhost:8000/metrics/summary
```