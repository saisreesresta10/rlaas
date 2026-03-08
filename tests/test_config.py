"""Unit tests for configuration management"""

import os
import pytest
from unittest.mock import patch

from rlaas.config import (
    RLaaSConfig,
    ServerConfig,
    RedisConfiguration,
    DefaultRuleConfiguration,
    MetricsConfig,
    LoggingConfig,
    SecurityConfig,
    LogLevel,
    get_config,
    reload_config,
    set_config
)
from rlaas.redis_client import FailureMode


class TestServerConfig:
    """Test ServerConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = ServerConfig()
        
        assert config.host == "0.0.0.0"
        assert config.port == 8000
        assert config.workers == 1
        assert config.reload is False
        assert config.log_level == LogLevel.INFO
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_HOST": "127.0.0.1",
            "RLAAS_PORT": "9000",
            "RLAAS_WORKERS": "4",
            "RLAAS_RELOAD": "true",
            "RLAAS_LOG_LEVEL": "DEBUG"
        }
        
        with patch.dict(os.environ, env_vars):
            config = ServerConfig.from_env()
            
            assert config.host == "127.0.0.1"
            assert config.port == 9000
            assert config.workers == 4
            assert config.reload is True
            assert config.log_level == LogLevel.DEBUG


class TestRedisConfiguration:
    """Test RedisConfiguration functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = RedisConfiguration()
        
        assert config.host == "localhost"
        assert config.port == 6379
        assert config.db == 0
        assert config.password is None
        assert config.socket_timeout == 5.0
        assert config.socket_connect_timeout == 5.0
        assert config.enable_circuit_breaker is True
        assert config.failure_mode == FailureMode.FAIL_OPEN
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_REDIS_HOST": "redis.example.com",
            "RLAAS_REDIS_PORT": "6380",
            "RLAAS_REDIS_DB": "1",
            "RLAAS_REDIS_PASSWORD": "secret",
            "RLAAS_REDIS_SOCKET_TIMEOUT": "10.0",
            "RLAAS_REDIS_SOCKET_CONNECT_TIMEOUT": "15.0",
            "RLAAS_REDIS_ENABLE_CIRCUIT_BREAKER": "false",
            "RLAAS_REDIS_CB_FAILURE_THRESHOLD": "10",
            "RLAAS_REDIS_CB_RECOVERY_TIMEOUT": "60.0",
            "RLAAS_REDIS_CB_SUCCESS_THRESHOLD": "5",
            "RLAAS_REDIS_CB_TIMEOUT_MS": "500.0",
            "RLAAS_REDIS_FAILURE_MODE": "FAIL_CLOSED"
        }
        
        with patch.dict(os.environ, env_vars):
            config = RedisConfiguration.from_env()
            
            assert config.host == "redis.example.com"
            assert config.port == 6380
            assert config.db == 1
            assert config.password == "secret"
            assert config.socket_timeout == 10.0
            assert config.socket_connect_timeout == 15.0
            assert config.enable_circuit_breaker is False
            assert config.circuit_breaker_config.failure_threshold == 10
            assert config.circuit_breaker_config.recovery_timeout == 60.0
            assert config.circuit_breaker_config.success_threshold == 5
            assert config.circuit_breaker_config.timeout_ms == 500.0
            assert config.failure_mode == FailureMode.FAIL_CLOSED
    
    def test_to_redis_config(self):
        """Test conversion to RedisConfig"""
        config = RedisConfiguration(
            host="test.redis.com",
            port=6380,
            db=2
        )
        
        redis_config = config.to_redis_config()
        
        assert redis_config.host == "test.redis.com"
        assert redis_config.port == 6380
        assert redis_config.db == 2


class TestDefaultRuleConfiguration:
    """Test DefaultRuleConfiguration functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = DefaultRuleConfiguration()
        
        assert config.limit == 100
        assert config.window_seconds == 60
        assert config.burst == 120
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_DEFAULT_LIMIT": "200",
            "RLAAS_DEFAULT_WINDOW_SECONDS": "120",
            "RLAAS_DEFAULT_BURST": "250"
        }
        
        with patch.dict(os.environ, env_vars):
            config = DefaultRuleConfiguration.from_env()
            
            assert config.limit == 200
            assert config.window_seconds == 120
            assert config.burst == 250
    
    def test_to_default_rule_config(self):
        """Test conversion to DefaultRuleConfig"""
        config = DefaultRuleConfiguration(
            limit=150,
            window_seconds=90,
            burst=180
        )
        
        rule_config = config.to_default_rule_config()
        
        assert rule_config.limit == 150
        assert rule_config.window_seconds == 90
        assert rule_config.burst == 180


class TestMetricsConfig:
    """Test MetricsConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = MetricsConfig()
        
        assert config.enabled is True
        assert config.export_interval_seconds == 60.0
        assert config.max_metrics_age_seconds == 3600.0
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_METRICS_ENABLED": "false",
            "RLAAS_METRICS_EXPORT_INTERVAL": "30.0",
            "RLAAS_METRICS_MAX_AGE": "1800.0"
        }
        
        with patch.dict(os.environ, env_vars):
            config = MetricsConfig.from_env()
            
            assert config.enabled is False
            assert config.export_interval_seconds == 30.0
            assert config.max_metrics_age_seconds == 1800.0


class TestLoggingConfig:
    """Test LoggingConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = LoggingConfig()
        
        assert config.level == LogLevel.INFO
        assert config.structured is True
        assert config.correlation_id_header == "X-Correlation-ID"
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_LOG_LEVEL": "ERROR",
            "RLAAS_STRUCTURED_LOGGING": "false",
            "RLAAS_CORRELATION_ID_HEADER": "X-Request-ID"
        }
        
        with patch.dict(os.environ, env_vars):
            config = LoggingConfig.from_env()
            
            assert config.level == LogLevel.ERROR
            assert config.structured is False
            assert config.correlation_id_header == "X-Request-ID"


class TestSecurityConfig:
    """Test SecurityConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = SecurityConfig()
        
        assert config.cors_enabled is True
        assert config.cors_origins == ["*"]
        assert config.cors_methods == ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        assert config.cors_headers == ["*"]
    
    def test_from_env(self):
        """Test loading from environment variables"""
        env_vars = {
            "RLAAS_CORS_ENABLED": "false",
            "RLAAS_CORS_ORIGINS": "https://example.com,https://app.example.com",
            "RLAAS_CORS_METHODS": "GET,POST,PUT",
            "RLAAS_CORS_HEADERS": "Content-Type,Authorization"
        }
        
        with patch.dict(os.environ, env_vars):
            config = SecurityConfig.from_env()
            
            assert config.cors_enabled is False
            assert config.cors_origins == ["https://example.com", "https://app.example.com"]
            assert config.cors_methods == ["GET", "POST", "PUT"]
            assert config.cors_headers == ["Content-Type", "Authorization"]


class TestRLaaSConfig:
    """Test RLaaSConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = RLaaSConfig()
        
        assert isinstance(config.server, ServerConfig)
        assert isinstance(config.redis, RedisConfiguration)
        assert isinstance(config.default_rules, DefaultRuleConfiguration)
        assert isinstance(config.metrics, MetricsConfig)
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.security, SecurityConfig)
    
    def test_from_env(self):
        """Test loading complete configuration from environment"""
        env_vars = {
            "RLAAS_HOST": "0.0.0.0",
            "RLAAS_PORT": "8080",
            "RLAAS_REDIS_HOST": "redis-server",
            "RLAAS_REDIS_PORT": "6379",
            "RLAAS_DEFAULT_LIMIT": "50",
            "RLAAS_METRICS_ENABLED": "true",
            "RLAAS_LOG_LEVEL": "WARNING",
            "RLAAS_CORS_ENABLED": "true"
        }
        
        with patch.dict(os.environ, env_vars):
            config = RLaaSConfig.from_env()
            
            assert config.server.host == "0.0.0.0"
            assert config.server.port == 8080
            assert config.redis.host == "redis-server"
            assert config.redis.port == 6379
            assert config.default_rules.limit == 50
            assert config.metrics.enabled is True
            assert config.logging.level == LogLevel.WARNING
            assert config.security.cors_enabled is True
    
    def test_validate_success(self):
        """Test successful validation"""
        config = RLaaSConfig()
        # Should not raise any exception
        config.validate()
    
    def test_validate_invalid_server_port(self):
        """Test validation with invalid server port"""
        config = RLaaSConfig()
        config.server.port = -1
        
        with pytest.raises(ValueError, match="Invalid server port"):
            config.validate()
    
    def test_validate_invalid_redis_port(self):
        """Test validation with invalid Redis port"""
        config = RLaaSConfig()
        config.redis.port = 70000
        
        with pytest.raises(ValueError, match="Invalid Redis port"):
            config.validate()
    
    def test_validate_invalid_default_limit(self):
        """Test validation with invalid default limit"""
        config = RLaaSConfig()
        config.default_rules.limit = 0
        
        with pytest.raises(ValueError, match="Invalid default limit"):
            config.validate()
    
    def test_validate_burst_less_than_limit(self):
        """Test validation with burst less than limit"""
        config = RLaaSConfig()
        config.default_rules.limit = 100
        config.default_rules.burst = 50
        
        with pytest.raises(ValueError, match="Default burst.*must be >= limit"):
            config.validate()
    
    def test_to_dict(self):
        """Test conversion to dictionary"""
        config = RLaaSConfig()
        config_dict = config.to_dict()
        
        assert "server" in config_dict
        assert "redis" in config_dict
        assert "default_rules" in config_dict
        assert "metrics" in config_dict
        assert "logging" in config_dict
        assert "security" in config_dict
        
        # Check that password is masked
        config.redis.password = "secret"
        config_dict = config.to_dict()
        assert config_dict["redis"]["password"] == "***"


class TestGlobalConfigFunctions:
    """Test global configuration functions"""
    
    def test_get_config(self):
        """Test getting global configuration"""
        # Clear any existing config
        import rlaas.config
        rlaas.config._config = None
        
        config = get_config()
        
        assert isinstance(config, RLaaSConfig)
        
        # Should return the same instance
        config2 = get_config()
        assert config is config2
    
    def test_reload_config(self):
        """Test reloading configuration"""
        # Set initial config
        import rlaas.config
        rlaas.config._config = RLaaSConfig()
        
        # Reload should create new instance
        new_config = reload_config()
        
        assert isinstance(new_config, RLaaSConfig)
    
    def test_set_config(self):
        """Test setting configuration"""
        custom_config = RLaaSConfig()
        custom_config.server.port = 9999
        
        set_config(custom_config)
        
        retrieved_config = get_config()
        assert retrieved_config.server.port == 9999
    
    def test_set_config_invalid(self):
        """Test setting invalid configuration"""
        invalid_config = RLaaSConfig()
        invalid_config.server.port = -1
        
        with pytest.raises(ValueError):
            set_config(invalid_config)