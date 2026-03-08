# RLaaS Configuration Guide

RLaaS supports comprehensive configuration through environment variables. All configuration parameters have sensible defaults and can be customized for different deployment environments.

## Server Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_HOST` | `0.0.0.0` | Server bind address |
| `RLAAS_PORT` | `8000` | Server port |
| `RLAAS_WORKERS` | `1` | Number of worker processes |
| `RLAAS_RELOAD` | `false` | Enable auto-reload for development |
| `RLAAS_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |

## Redis Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_REDIS_HOST` | `localhost` | Redis server hostname |
| `RLAAS_REDIS_PORT` | `6379` | Redis server port |
| `RLAAS_REDIS_DB` | `0` | Redis database number |
| `RLAAS_REDIS_PASSWORD` | `None` | Redis password (if required) |
| `RLAAS_REDIS_SOCKET_TIMEOUT` | `5.0` | Socket timeout in seconds |
| `RLAAS_REDIS_SOCKET_CONNECT_TIMEOUT` | `5.0` | Connection timeout in seconds |
| `RLAAS_REDIS_ENABLE_CIRCUIT_BREAKER` | `true` | Enable circuit breaker protection |
| `RLAAS_REDIS_FAILURE_MODE` | `FAIL_OPEN` | Failure mode (FAIL_OPEN, FAIL_CLOSED) |

## Circuit Breaker Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_REDIS_CB_FAILURE_THRESHOLD` | `5` | Failures before opening circuit |
| `RLAAS_REDIS_CB_RECOVERY_TIMEOUT` | `30.0` | Recovery timeout in seconds |
| `RLAAS_REDIS_CB_SUCCESS_THRESHOLD` | `3` | Successes needed to close circuit |
| `RLAAS_REDIS_CB_TIMEOUT_MS` | `200.0` | Operation timeout in milliseconds |

## Default Rate Limiting Rules

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_DEFAULT_LIMIT` | `100` | Default requests per window |
| `RLAAS_DEFAULT_WINDOW_SECONDS` | `60` | Default time window in seconds |
| `RLAAS_DEFAULT_BURST` | `120` | Default burst capacity |

## Metrics Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_METRICS_ENABLED` | `true` | Enable metrics collection |
| `RLAAS_METRICS_EXPORT_INTERVAL` | `60.0` | Metrics export interval in seconds |
| `RLAAS_METRICS_MAX_AGE` | `3600.0` | Maximum metrics age in seconds |

## Logging Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_LOG_LEVEL` | `INFO` | Log level |
| `RLAAS_STRUCTURED_LOGGING` | `true` | Enable structured logging |
| `RLAAS_CORRELATION_ID_HEADER` | `X-Correlation-ID` | HTTP header for correlation ID |

## Security Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RLAAS_CORS_ENABLED` | `true` | Enable CORS middleware |
| `RLAAS_CORS_ORIGINS` | `*` | Allowed origins (comma-separated) |
| `RLAAS_CORS_METHODS` | `GET,POST,PUT,DELETE,OPTIONS` | Allowed methods (comma-separated) |
| `RLAAS_CORS_HEADERS` | `*` | Allowed headers (comma-separated) |

## Example Configuration

### Development Environment

```bash
# Server
export RLAAS_HOST=127.0.0.1
export RLAAS_PORT=8000
export RLAAS_RELOAD=true
export RLAAS_LOG_LEVEL=DEBUG

# Redis
export RLAAS_REDIS_HOST=localhost
export RLAAS_REDIS_PORT=6379

# CORS (allow all for development)
export RLAAS_CORS_ORIGINS=*
```

### Production Environment

```bash
# Server
export RLAAS_HOST=0.0.0.0
export RLAAS_PORT=8000
export RLAAS_WORKERS=4
export RLAAS_LOG_LEVEL=INFO

# Redis
export RLAAS_REDIS_HOST=redis-cluster.internal
export RLAAS_REDIS_PORT=6379
export RLAAS_REDIS_PASSWORD=secure_password
export RLAAS_REDIS_CB_FAILURE_THRESHOLD=3
export RLAAS_REDIS_CB_RECOVERY_TIMEOUT=60

# Default rules (more restrictive)
export RLAAS_DEFAULT_LIMIT=50
export RLAAS_DEFAULT_WINDOW_SECONDS=60
export RLAAS_DEFAULT_BURST=75

# CORS (restrict origins)
export RLAAS_CORS_ORIGINS=https://api.example.com,https://app.example.com
export RLAAS_CORS_METHODS=GET,POST,PUT,DELETE
export RLAAS_CORS_HEADERS=Content-Type,Authorization,X-Correlation-ID
```

### Docker Environment

```bash
# Use environment-specific values
export RLAAS_REDIS_HOST=${REDIS_HOST:-redis}
export RLAAS_REDIS_PORT=${REDIS_PORT:-6379}
export RLAAS_REDIS_PASSWORD=${REDIS_PASSWORD}

# Scale with container orchestration
export RLAAS_WORKERS=${WORKERS:-2}
export RLAAS_PORT=${PORT:-8000}
```

## Configuration Validation

RLaaS validates all configuration parameters on startup and will fail to start with clear error messages if invalid values are provided:

- Port numbers must be between 1 and 65535
- Worker count must be positive
- Timeouts must be positive
- Default burst must be >= default limit
- Circuit breaker thresholds must be positive

## Environment Variable Priority

Configuration is loaded in the following order (later values override earlier ones):

1. Default values (hardcoded)
2. Environment variables
3. Configuration set via `set_config()` (for testing)

## Runtime Configuration Changes

Most configuration changes require an application restart. However, some operational parameters can be modified at runtime through the management API (if implemented in future versions).

## Security Considerations

- Never expose Redis passwords in logs or configuration files
- Use restrictive CORS settings in production
- Consider using environment variable files (.env) with proper file permissions
- Rotate Redis passwords regularly if authentication is enabled
- Monitor circuit breaker metrics to detect Redis connectivity issues