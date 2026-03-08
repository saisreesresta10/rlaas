# RLaaS Maintenance Runbook

## Overview

This runbook covers routine maintenance procedures for RLaaS to ensure optimal performance and reliability.

## Daily Maintenance

### Health Check Verification

```bash
# Automated daily health check
#!/bin/bash
HEALTH_URL="http://localhost:8000/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $RESPONSE -eq 200 ]; then
    echo "$(date): Health check PASSED"
else
    echo "$(date): Health check FAILED - HTTP $RESPONSE"
    # Send alert
fi
```

### Log Review

```bash
# Check for errors in the last 24 hours
docker-compose logs --since 24h rlaas | grep ERROR

# Check for warnings
docker-compose logs --since 24h rlaas | grep WARNING

# Monitor circuit breaker events
docker-compose logs --since 24h rlaas | grep "circuit_breaker_event"
```

### Metrics Review

```bash
# Get daily metrics summary
curl -s http://localhost:8000/metrics/summary | jq '.'

# Check key performance indicators
curl -s http://localhost:8000/metrics | grep -E "(rlaas_requests_total|rlaas_request_duration|rlaas_requests_blocked)"
```

## Weekly Maintenance

### Performance Analysis

```bash
# Analyze request patterns
docker-compose logs --since 7d rlaas | grep "rate_limit_decision" | \
  jq -r '.client_id' | sort | uniq -c | sort -nr | head -10

# Check average response times
docker-compose logs --since 7d rlaas | grep "api_request" | \
  jq -r '.duration_ms' | awk '{sum+=$1; count++} END {print "Average:", sum/count, "ms"}'

# Redis memory usage trend
docker-compose exec redis redis-cli info memory | grep used_memory_human
```

### Resource Utilization

```bash
# Check disk usage
df -h

# Check Docker volume usage
docker system df

# Check container resource usage
docker stats --no-stream

# Redis memory analysis
docker-compose exec redis redis-cli info memory
docker-compose exec redis redis-cli memory usage
```

### Configuration Review

```bash
# Verify environment variables
docker-compose config

# Check Redis configuration
docker-compose exec redis redis-cli config get "*"

# Review circuit breaker settings
docker-compose logs rlaas | grep "circuit_breaker" | tail -5
```

## Monthly Maintenance

### Security Updates

```bash
# Update base images
docker-compose pull

# Rebuild with latest dependencies
docker-compose build --no-cache

# Update Python dependencies
pip list --outdated
# Update requirements.txt as needed
```

### Data Cleanup

```bash
# Clean up old Docker images
docker image prune -f

# Clean up unused volumes
docker volume prune -f

# Redis memory optimization
docker-compose exec redis redis-cli memory purge

# Rotate logs if needed (depends on log driver)
docker-compose logs --tail=0 rlaas > /dev/null
```

### Backup Procedures

```bash
# Backup Redis data
docker exec rlaas-redis redis-cli BGSAVE
docker cp rlaas-redis:/data/dump.rdb ./backups/redis-$(date +%Y%m%d).rdb

# Backup configuration
tar -czf ./backups/config-$(date +%Y%m%d).tar.gz \
  docker-compose*.yml .env* scripts/ docs/

# Verify backup integrity
redis-cli --rdb ./backups/redis-$(date +%Y%m%d).rdb --rdb-check-mode
```

### Performance Tuning

```bash
# Analyze Redis slow queries
docker-compose exec redis redis-cli slowlog get 10

# Check Redis hit rate
docker-compose exec redis redis-cli info stats | grep keyspace

# Optimize Redis memory
docker-compose exec redis redis-cli memory doctor

# Review application metrics for optimization opportunities
curl -s http://localhost:8000/metrics | grep -E "(histogram|summary)" | head -20
```

## Quarterly Maintenance

### Capacity Planning

```bash
# Analyze growth trends
# Export metrics to analyze growth patterns
curl -s http://localhost:8000/metrics > metrics-$(date +%Y%m%d).txt

# Review resource usage trends
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" --no-stream

# Plan for scaling needs
echo "Current configuration:"
docker-compose config | grep -E "(replicas|WORKERS|memory|cpu)"
```

### Disaster Recovery Testing

```bash
# Test backup restoration
# 1. Stop services
docker-compose down

# 2. Restore from backup
docker cp ./backups/redis-latest.rdb rlaas-redis:/data/dump.rdb

# 3. Start services
docker-compose up -d

# 4. Verify data integrity
curl http://localhost:8000/health
```

### Documentation Updates

1. Review and update deployment documentation
2. Update runbooks based on recent incidents
3. Review and update monitoring dashboards
4. Update security procedures

## Monitoring Setup

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'rlaas'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

### Grafana Dashboard

Key metrics to monitor:
- Request rate and latency
- Error rates by endpoint
- Redis performance metrics
- Circuit breaker state
- Resource utilization

### Log Aggregation

```yaml
# docker-compose.logging.yml
version: '3.8'
services:
  rlaas:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
        labels: "service=rlaas"
```

## Troubleshooting Common Issues

### High Memory Usage

```bash
# Check memory breakdown
docker stats --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Redis memory analysis
docker-compose exec redis redis-cli info memory
docker-compose exec redis redis-cli memory usage

# Application memory profiling
# Add memory profiling to application if needed
```

### Slow Performance

```bash
# Check Redis latency
docker-compose exec redis redis-cli --latency-history

# Analyze slow operations
docker-compose logs rlaas | grep "duration_ms" | \
  jq -r 'select(.duration_ms > 100) | {endpoint: .path, duration: .duration_ms}'

# Check for resource contention
iostat -x 1 5
```

### Connection Issues

```bash
# Check network connectivity
docker-compose exec rlaas ping redis

# Check Redis connection pool
docker-compose logs rlaas | grep "redis_operation" | tail -10

# Verify Redis configuration
docker-compose exec redis redis-cli config get "*timeout*"
```

## Maintenance Schedules

### Automated Tasks

```cron
# Daily health check (6 AM)
0 6 * * * /path/to/health-check.sh

# Weekly log rotation (Sunday 2 AM)
0 2 * * 0 /path/to/log-rotation.sh

# Monthly backup (1st day, 3 AM)
0 3 1 * * /path/to/backup.sh

# Quarterly capacity review (1st day of quarter, 9 AM)
0 9 1 1,4,7,10 * /path/to/capacity-review.sh
```

### Manual Tasks

- **Weekly**: Performance review and optimization
- **Monthly**: Security updates and dependency updates
- **Quarterly**: Disaster recovery testing
- **Annually**: Architecture review and major upgrades

## Emergency Procedures

### Service Recovery

```bash
# Quick service restart
docker-compose restart rlaas

# Full environment reset
docker-compose down
docker-compose up -d

# Emergency scaling
docker-compose up -d --scale rlaas=5
```

### Data Recovery

```bash
# Restore from latest backup
docker-compose down
docker cp ./backups/redis-latest.rdb rlaas-redis:/data/
docker-compose up -d

# Verify data integrity
curl http://localhost:8000/health
```

### Rollback Procedures

```bash
# Rollback to previous version
docker-compose down
git checkout previous-stable-tag
docker-compose build
docker-compose up -d
```

## Maintenance Checklist

### Pre-Maintenance
- [ ] Notify stakeholders of maintenance window
- [ ] Create backup of current state
- [ ] Verify rollback procedures
- [ ] Prepare monitoring for post-maintenance

### During Maintenance
- [ ] Follow documented procedures
- [ ] Monitor system health continuously
- [ ] Document any deviations from plan
- [ ] Test functionality after changes

### Post-Maintenance
- [ ] Verify all services are healthy
- [ ] Check performance metrics
- [ ] Monitor for any issues
- [ ] Update documentation if needed
- [ ] Notify stakeholders of completion

## Contact Information

```
Primary Maintainer: [CONTACT]
Backup Maintainer: [CONTACT]
Infrastructure Team: [CONTACT]
Emergency Escalation: [CONTACT]
```