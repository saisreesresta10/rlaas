"""Configuration management for RLaaS application"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from .models import CircuitBreakerConfig
from .redis_client import RedisConfig, FailureMode
from .rule_management import DefaultRuleConfig


class LogLevel(str, Enum):
    """Supported log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ServerConfig:
    """FastAPI server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    log_level: LogLevel = LogLevel.INFO
    
    @classmethod
    def from_env(cls) -> 'ServerConfig':
        """Load server configuration from environment variables"""
        return cls(
            host=os.getenv("RLAAS_HOST", "0.0.0.0"),
            port=int(os.getenv("RLAAS_PORT", "8000")),
            workers=int(os.getenv("RLAAS_WORKERS", "1")),
            reload=os.getenv("RLAAS_RELOAD", "false").lower() == "true",
            log_level=LogLevel(os.getenv("RLAAS_LOG_LEVEL", "INFO").upper())
        )


@dataclass
class RedisConfiguration:
    """Redis configuration with environment variable support"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    enable_circuit_breaker: bool = True
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=lambda: CircuitBreakerConfig())
    failure_mode: FailureMode = FailureMode.FAIL_OPEN
    
    @classmethod
    def from_env(cls) -> 'RedisConfiguration':
        """Load Redis configuration from environment variables"""
        # Circuit breaker configuration
        cb_config = CircuitBreakerConfig(
            failure_threshold=int(os.getenv("RLAAS_REDIS_CB_FAILURE_THRESHOLD", "5")),
            recovery_timeout=float(os.getenv("RLAAS_REDIS_CB_RECOVERY_TIMEOUT", "30.0")),
            success_threshold=int(os.getenv("RLAAS_REDIS_CB_SUCCESS_THRESHOLD", "3")),
            timeout_ms=float(os.getenv("RLAAS_REDIS_CB_TIMEOUT_MS", "200.0"))
        )
        
        # Parse failure mode
        failure_mode_str = os.getenv("RLAAS_REDIS_FAILURE_MODE", "FAIL_OPEN").upper()
        failure_mode = FailureMode.FAIL_OPEN if failure_mode_str == "FAIL_OPEN" else FailureMode.FAIL_CLOSED
        
        return cls(
            host=os.getenv("RLAAS_REDIS_HOST", "localhost"),
            port=int(os.getenv("RLAAS_REDIS_PORT", "6379")),
            db=int(os.getenv("RLAAS_REDIS_DB", "0")),
            password=os.getenv("RLAAS_REDIS_PASSWORD"),
            socket_timeout=float(os.getenv("RLAAS_REDIS_SOCKET_TIMEOUT", "5.0")),
            socket_connect_timeout=float(os.getenv("RLAAS_REDIS_SOCKET_CONNECT_TIMEOUT", "5.0")),
            enable_circuit_breaker=os.getenv("RLAAS_REDIS_ENABLE_CIRCUIT_BREAKER", "true").lower() == "true",
            circuit_breaker_config=cb_config,
            failure_mode=failure_mode
        )
    
    def to_redis_config(self) -> RedisConfig:
        """Convert to RedisConfig for use with RedisClientManager"""
        return RedisConfig(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            socket_timeout=self.socket_timeout,
            socket_connect_timeout=self.socket_connect_timeout,
            enable_circuit_breaker=self.enable_circuit_breaker,
            circuit_breaker_config=self.circuit_breaker_config,
            failure_mode=self.failure_mode
        )


@dataclass
class DefaultRuleConfiguration:
    """Default rate limiting rule configuration"""
    limit: int = 100
    window_seconds: int = 60
    burst: int = 120
    
    @classmethod
    def from_env(cls) -> 'DefaultRuleConfiguration':
        """Load default rule configuration from environment variables"""
        return cls(
            limit=int(os.getenv("RLAAS_DEFAULT_LIMIT", "100")),
            window_seconds=int(os.getenv("RLAAS_DEFAULT_WINDOW_SECONDS", "60")),
            burst=int(os.getenv("RLAAS_DEFAULT_BURST", "120"))
        )
    
    def to_default_rule_config(self) -> DefaultRuleConfig:
        """Convert to DefaultRuleConfig for use with RuleManagementService"""
        return DefaultRuleConfig(
            limit=self.limit,
            window_seconds=self.window_seconds,
            burst=self.burst
        )


@dataclass
class MetricsConfig:
    """Metrics configuration"""
    enabled: bool = True
    export_interval_seconds: float = 60.0
    max_metrics_age_seconds: float = 3600.0
    
    @classmethod
    def from_env(cls) -> 'MetricsConfig':
        """Load metrics configuration from environment variables"""
        return cls(
            enabled=os.getenv("RLAAS_METRICS_ENABLED", "true").lower() == "true",
            export_interval_seconds=float(os.getenv("RLAAS_METRICS_EXPORT_INTERVAL", "60.0")),
            max_metrics_age_seconds=float(os.getenv("RLAAS_METRICS_MAX_AGE", "3600.0"))
        )


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: LogLevel = LogLevel.INFO
    structured: bool = True
    correlation_id_header: str = "X-Correlation-ID"
    
    @classmethod
    def from_env(cls) -> 'LoggingConfig':
        """Load logging configuration from environment variables"""
        return cls(
            level=LogLevel(os.getenv("RLAAS_LOG_LEVEL", "INFO").upper()),
            structured=os.getenv("RLAAS_STRUCTURED_LOGGING", "true").lower() == "true",
            correlation_id_header=os.getenv("RLAAS_CORRELATION_ID_HEADER", "X-Correlation-ID")
        )


@dataclass
class SecurityConfig:
    """Security configuration"""
    cors_enabled: bool = True
    cors_origins: list = field(default_factory=lambda: ["*"])
    cors_methods: list = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    cors_headers: list = field(default_factory=lambda: ["*"])
    
    @classmethod
    def from_env(cls) -> 'SecurityConfig':
        """Load security configuration from environment variables"""
        # Parse CORS origins from comma-separated string
        cors_origins_str = os.getenv("RLAAS_CORS_ORIGINS", "*")
        cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]
        
        # Parse CORS methods from comma-separated string
        cors_methods_str = os.getenv("RLAAS_CORS_METHODS", "GET,POST,PUT,DELETE,OPTIONS")
        cors_methods = [method.strip() for method in cors_methods_str.split(",")]
        
        # Parse CORS headers from comma-separated string
        cors_headers_str = os.getenv("RLAAS_CORS_HEADERS", "*")
        cors_headers = [header.strip() for header in cors_headers_str.split(",")]
        
        return cls(
            cors_enabled=os.getenv("RLAAS_CORS_ENABLED", "true").lower() == "true",
            cors_origins=cors_origins,
            cors_methods=cors_methods,
            cors_headers=cors_headers
        )


@dataclass
class RLaaSConfig:
    """Main application configuration"""
    server: ServerConfig = field(default_factory=ServerConfig)
    redis: RedisConfiguration = field(default_factory=RedisConfiguration)
    default_rules: DefaultRuleConfiguration = field(default_factory=DefaultRuleConfiguration)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    @classmethod
    def from_env(cls) -> 'RLaaSConfig':
        """Load complete application configuration from environment variables"""
        return cls(
            server=ServerConfig.from_env(),
            redis=RedisConfiguration.from_env(),
            default_rules=DefaultRuleConfiguration.from_env(),
            metrics=MetricsConfig.from_env(),
            logging=LoggingConfig.from_env(),
            security=SecurityConfig.from_env()
        )
    
    def validate(self) -> None:
        """Validate configuration parameters"""
        errors = []
        
        # Validate server configuration
        if self.server.port < 1 or self.server.port > 65535:
            errors.append(f"Invalid server port: {self.server.port}")
        
        if self.server.workers < 1:
            errors.append(f"Invalid worker count: {self.server.workers}")
        
        # Validate Redis configuration
        if self.redis.port < 1 or self.redis.port > 65535:
            errors.append(f"Invalid Redis port: {self.redis.port}")
        
        if self.redis.db < 0:
            errors.append(f"Invalid Redis database: {self.redis.db}")
        
        if self.redis.socket_timeout <= 0:
            errors.append(f"Invalid Redis socket timeout: {self.redis.socket_timeout}")
        
        if self.redis.socket_connect_timeout <= 0:
            errors.append(f"Invalid Redis socket connect timeout: {self.redis.socket_connect_timeout}")
        
        # Validate circuit breaker configuration
        cb_config = self.redis.circuit_breaker_config
        if cb_config.failure_threshold < 1:
            errors.append(f"Invalid circuit breaker failure threshold: {cb_config.failure_threshold}")
        
        if cb_config.recovery_timeout <= 0:
            errors.append(f"Invalid circuit breaker recovery timeout: {cb_config.recovery_timeout}")
        
        if cb_config.success_threshold < 1:
            errors.append(f"Invalid circuit breaker success threshold: {cb_config.success_threshold}")
        
        if cb_config.timeout_ms <= 0:
            errors.append(f"Invalid circuit breaker timeout: {cb_config.timeout_ms}")
        
        # Validate default rule configuration
        if self.default_rules.limit < 1:
            errors.append(f"Invalid default limit: {self.default_rules.limit}")
        
        if self.default_rules.window_seconds < 1:
            errors.append(f"Invalid default window seconds: {self.default_rules.window_seconds}")
        
        if self.default_rules.burst < self.default_rules.limit:
            errors.append(f"Default burst ({self.default_rules.burst}) must be >= limit ({self.default_rules.limit})")
        
        # Validate metrics configuration
        if self.metrics.export_interval_seconds <= 0:
            errors.append(f"Invalid metrics export interval: {self.metrics.export_interval_seconds}")
        
        if self.metrics.max_metrics_age_seconds <= 0:
            errors.append(f"Invalid metrics max age: {self.metrics.max_metrics_age_seconds}")
        
        if errors:
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for logging/debugging"""
        return {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "workers": self.server.workers,
                "reload": self.server.reload,
                "log_level": self.server.log_level.value
            },
            "redis": {
                "host": self.redis.host,
                "port": self.redis.port,
                "db": self.redis.db,
                "password": "***" if self.redis.password else None,
                "socket_timeout": self.redis.socket_timeout,
                "socket_connect_timeout": self.redis.socket_connect_timeout,
                "enable_circuit_breaker": self.redis.enable_circuit_breaker,
                "circuit_breaker": {
                    "failure_threshold": self.redis.circuit_breaker_config.failure_threshold,
                    "recovery_timeout": self.redis.circuit_breaker_config.recovery_timeout,
                    "success_threshold": self.redis.circuit_breaker_config.success_threshold,
                    "timeout_ms": self.redis.circuit_breaker_config.timeout_ms
                },
                "failure_mode": self.redis.failure_mode.value
            },
            "default_rules": {
                "limit": self.default_rules.limit,
                "window_seconds": self.default_rules.window_seconds,
                "burst": self.default_rules.burst
            },
            "metrics": {
                "enabled": self.metrics.enabled,
                "export_interval_seconds": self.metrics.export_interval_seconds,
                "max_metrics_age_seconds": self.metrics.max_metrics_age_seconds
            },
            "logging": {
                "level": self.logging.level.value,
                "structured": self.logging.structured,
                "correlation_id_header": self.logging.correlation_id_header
            },
            "security": {
                "cors_enabled": self.security.cors_enabled,
                "cors_origins": self.security.cors_origins,
                "cors_methods": self.security.cors_methods,
                "cors_headers": self.security.cors_headers
            }
        }


# Global configuration instance
_config: Optional[RLaaSConfig] = None


def get_config() -> RLaaSConfig:
    """
    Get the global configuration instance
    
    Returns:
        RLaaSConfig instance
    """
    global _config
    if _config is None:
        _config = RLaaSConfig.from_env()
        _config.validate()
    return _config


def reload_config() -> RLaaSConfig:
    """
    Reload configuration from environment variables
    
    Returns:
        New RLaaSConfig instance
    """
    global _config
    _config = RLaaSConfig.from_env()
    _config.validate()
    return _config


def set_config(config: RLaaSConfig) -> None:
    """
    Set the global configuration instance (for testing)
    
    Args:
        config: RLaaSConfig instance to set
    """
    global _config
    config.validate()
    _config = config