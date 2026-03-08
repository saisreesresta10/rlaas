"""Unit tests for RuleManagementService"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from rlaas.rule_management import (
    RuleManagementService,
    DefaultRuleConfig,
    RuleValidationError
)
from rlaas.models import RateLimitRule
from rlaas.circuit_breaker import CircuitBreakerError


class TestDefaultRuleConfig:
    """Test DefaultRuleConfig functionality"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = DefaultRuleConfig()
        
        assert config.limit == 100
        assert config.window_seconds == 60
        assert config.burst == 120
    
    def test_custom_values(self):
        """Test custom configuration values"""
        config = DefaultRuleConfig(
            limit=50,
            window_seconds=30,
            burst=75
        )
        
        assert config.limit == 50
        assert config.window_seconds == 30
        assert config.burst == 75
    
    def test_to_rule_conversion(self):
        """Test conversion to RateLimitRule"""
        config = DefaultRuleConfig(limit=200, window_seconds=120, burst=250)
        
        rule = config.to_rule("client1", "/api/test", "GET")
        
        assert rule.client_id == "client1"
        assert rule.endpoint == "/api/test"
        assert rule.http_method == "GET"
        assert rule.limit == 200
        assert rule.window_seconds == 120
        assert rule.burst == 250


class TestRuleManagementService:
    """Test RuleManagementService functionality"""
    
    @pytest.fixture
    def mock_redis_state_manager(self):
        """Create mock Redis state manager"""
        manager = MagicMock()
        manager.get_rule = AsyncMock()
        manager.set_rule = AsyncMock()
        manager.delete_rule = AsyncMock()
        manager.create_or_update_bucket_with_rule = AsyncMock()
        manager.health_check = AsyncMock(return_value=True)
        return manager
    
    @pytest.fixture
    def default_config(self):
        """Create default rule configuration"""
        return DefaultRuleConfig(limit=100, window_seconds=60, burst=120)
    
    @pytest.fixture
    def rule_service(self, mock_redis_state_manager, default_config):
        """Create RuleManagementService instance"""
        return RuleManagementService(mock_redis_state_manager, default_config)
    
    def test_initialization(self, rule_service, default_config):
        """Test service initialization"""
        assert rule_service.default_rule_config == default_config
        assert rule_service.redis_state_manager is not None
    
    def test_initialization_with_default_config(self, mock_redis_state_manager):
        """Test service initialization with default configuration"""
        service = RuleManagementService(mock_redis_state_manager)
        
        assert service.default_rule_config.limit == 100
        assert service.default_rule_config.window_seconds == 60
        assert service.default_rule_config.burst == 120
    
    def test_validate_rule_success(self, rule_service):
        """Test successful rule validation"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        # Should not raise exception
        rule_service.validate_rule(rule)
    
    def test_validate_rule_empty_client_id(self, rule_service):
        """Test rule validation with empty client_id"""
        rule = RateLimitRule(
            client_id="",
            endpoint="/api/test",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        with pytest.raises(RuleValidationError, match="client_id cannot be empty"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_empty_endpoint(self, rule_service):
        """Test rule validation with empty endpoint"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        with pytest.raises(RuleValidationError, match="endpoint cannot be empty"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_invalid_http_method(self, rule_service):
        """Test rule validation with invalid HTTP method"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="INVALID",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        with pytest.raises(RuleValidationError, match="http_method must be one of"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_negative_limit(self, rule_service):
        """Test rule validation with negative limit"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=-1,
            window_seconds=60,
            burst=75
        )
        
        with pytest.raises(RuleValidationError, match="limit must be positive"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_burst_less_than_limit(self, rule_service):
        """Test rule validation with burst less than limit"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=100,
            window_seconds=60,
            burst=50
        )
        
        with pytest.raises(RuleValidationError, match="burst must be greater than or equal to limit"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_excessive_limits(self, rule_service):
        """Test rule validation with excessive limits"""
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=200000,  # Exceeds max
            window_seconds=60,
            burst=300000   # Exceeds max
        )
        
        with pytest.raises(RuleValidationError, match="limit exceeds maximum"):
            rule_service.validate_rule(rule)
    
    @pytest.mark.asyncio
    async def test_create_rule_success(self, rule_service, mock_redis_state_manager):
        """Test successful rule creation"""
        mock_redis_state_manager.get_rule.return_value = None  # No existing rule
        
        rule = await rule_service.create_rule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        assert rule.client_id == "client1"
        assert rule.endpoint == "/api/test"
        assert rule.http_method == "GET"
        assert rule.limit == 50
        assert rule.window_seconds == 60
        assert rule.burst == 75
        
        # Verify Redis operations were called
        mock_redis_state_manager.set_rule.assert_called_once()
        mock_redis_state_manager.create_or_update_bucket_with_rule.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_create_rule_update_existing(self, rule_service, mock_redis_state_manager):
        """Test updating existing rule"""
        existing_rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=100,
            window_seconds=60,
            burst=120
        )
        mock_redis_state_manager.get_rule.return_value = existing_rule
        
        rule = await rule_service.create_rule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75,
            preserve_existing_tokens=True
        )
        
        assert rule.limit == 50
        assert rule.burst == 75
        
        # Verify bucket update was called
        mock_redis_state_manager.create_or_update_bucket_with_rule.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_rule_validation_error(self, rule_service):
        """Test rule creation with validation error"""
        with pytest.raises(RuleValidationError):
            await rule_service.create_rule(
                client_id="",  # Invalid
                endpoint="/api/test",
                http_method="GET",
                limit=50,
                window_seconds=60,
                burst=75
            )
    
    @pytest.mark.asyncio
    async def test_create_rule_circuit_breaker_error(self, rule_service, mock_redis_state_manager):
        """Test rule creation with circuit breaker error"""
        mock_redis_state_manager.get_rule.side_effect = CircuitBreakerError("Circuit breaker open")
        
        with pytest.raises(CircuitBreakerError):
            await rule_service.create_rule(
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                limit=50,
                window_seconds=60,
                burst=75
            )
    
    @pytest.mark.asyncio
    async def test_get_rule_configured(self, rule_service, mock_redis_state_manager):
        """Test getting configured rule"""
        configured_rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=200,
            window_seconds=120,
            burst=250
        )
        mock_redis_state_manager.get_rule.return_value = configured_rule
        
        rule = await rule_service.get_rule("client1", "/api/test", "GET")
        
        assert rule == configured_rule
        mock_redis_state_manager.get_rule.assert_called_once_with("client1", "/api/test", "GET")
    
    @pytest.mark.asyncio
    async def test_get_rule_default_fallback(self, rule_service, mock_redis_state_manager):
        """Test getting rule with default fallback"""
        mock_redis_state_manager.get_rule.return_value = None  # No configured rule
        
        rule = await rule_service.get_rule("client1", "/api/test", "GET")
        
        # Should return default rule
        assert rule.client_id == "client1"
        assert rule.endpoint == "/api/test"
        assert rule.http_method == "GET"
        assert rule.limit == 100  # Default
        assert rule.window_seconds == 60  # Default
        assert rule.burst == 120  # Default
    
    @pytest.mark.asyncio
    async def test_get_rule_no_fallback(self, rule_service, mock_redis_state_manager):
        """Test getting rule without fallback"""
        mock_redis_state_manager.get_rule.return_value = None
        
        with pytest.raises(ValueError, match="No rule found"):
            await rule_service.get_rule(
                "client1", "/api/test", "GET", 
                use_default_fallback=False
            )
    
    @pytest.mark.asyncio
    async def test_get_rule_circuit_breaker_fallback(self, rule_service, mock_redis_state_manager):
        """Test getting rule with circuit breaker error and fallback"""
        mock_redis_state_manager.get_rule.side_effect = CircuitBreakerError("Circuit breaker open")
        
        rule = await rule_service.get_rule("client1", "/api/test", "GET")
        
        # Should return default rule due to circuit breaker
        assert rule.limit == 100  # Default
        assert rule.window_seconds == 60  # Default
        assert rule.burst == 120  # Default
    
    @pytest.mark.asyncio
    async def test_update_rule_success(self, rule_service, mock_redis_state_manager):
        """Test successful rule update"""
        existing_rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=100,
            window_seconds=60,
            burst=120
        )
        mock_redis_state_manager.get_rule.return_value = existing_rule
        
        updated_rule = await rule_service.update_rule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=80,  # Update to lower limit (still valid with burst=120)
            preserve_existing_tokens=False
        )
        
        assert updated_rule.limit == 80
        assert updated_rule.window_seconds == 60  # Unchanged
        assert updated_rule.burst == 120  # Unchanged
    
    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, rule_service, mock_redis_state_manager):
        """Test updating non-existent rule"""
        mock_redis_state_manager.get_rule.return_value = None
        
        with pytest.raises(ValueError, match="No rule found"):
            await rule_service.update_rule(
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                limit=200
            )
    
    @pytest.mark.asyncio
    async def test_delete_rule_success(self, rule_service, mock_redis_state_manager):
        """Test successful rule deletion"""
        mock_redis_state_manager.delete_rule.return_value = True
        
        result = await rule_service.delete_rule("client1", "/api/test", "GET")
        
        assert result is True
        mock_redis_state_manager.delete_rule.assert_called_once_with("client1", "/api/test", "GET")
    
    @pytest.mark.asyncio
    async def test_delete_rule_not_found(self, rule_service, mock_redis_state_manager):
        """Test deleting non-existent rule"""
        mock_redis_state_manager.delete_rule.return_value = False
        
        result = await rule_service.delete_rule("client1", "/api/test", "GET")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_list_rules_placeholder(self, rule_service):
        """Test list rules placeholder implementation"""
        rules = await rule_service.list_rules()
        
        # Should return empty list (placeholder implementation)
        assert rules == []
    
    def test_get_default_rule_config(self, rule_service, default_config):
        """Test getting default rule configuration"""
        config = rule_service.get_default_rule_config()
        
        assert config == default_config
    
    def test_update_default_rule_config(self, rule_service):
        """Test updating default rule configuration"""
        updated_config = rule_service.update_default_rule_config(
            limit=200,
            window_seconds=120,
            burst=250
        )
        
        assert updated_config.limit == 200
        assert updated_config.window_seconds == 120
        assert updated_config.burst == 250
        
        # Verify it's actually updated
        assert rule_service.default_rule_config.limit == 200
    
    def test_update_default_rule_config_partial(self, rule_service):
        """Test partial update of default rule configuration"""
        original_window = rule_service.default_rule_config.window_seconds
        original_burst = rule_service.default_rule_config.burst
        
        updated_config = rule_service.update_default_rule_config(limit=300)
        
        assert updated_config.limit == 300
        assert updated_config.window_seconds == original_window  # Unchanged
        assert updated_config.burst == original_burst  # Unchanged
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, rule_service, mock_redis_state_manager):
        """Test health check when Redis is healthy"""
        mock_redis_state_manager.health_check.return_value = True
        
        health = await rule_service.health_check()
        
        assert health["service"] == "rule_management"
        assert health["status"] == "healthy"
        assert health["redis_connectivity"] is True
        assert "default_config" in health
        assert "timestamp" in health
    
    @pytest.mark.asyncio
    async def test_health_check_degraded(self, rule_service, mock_redis_state_manager):
        """Test health check when Redis is unhealthy"""
        mock_redis_state_manager.health_check.return_value = False
        
        health = await rule_service.health_check()
        
        assert health["service"] == "rule_management"
        assert health["status"] == "degraded"
        assert health["redis_connectivity"] is False
        assert "message" in health
    
    @pytest.mark.asyncio
    async def test_health_check_exception(self, rule_service, mock_redis_state_manager):
        """Test health check with exception"""
        mock_redis_state_manager.health_check.side_effect = Exception("Redis error")
        
        health = await rule_service.health_check()
        
        assert health["service"] == "rule_management"
        assert health["status"] == "unhealthy"
        assert "error" in health


class TestRuleValidationEdgeCases:
    """Test edge cases for rule validation"""
    
    @pytest.fixture
    def rule_service(self):
        """Create rule service for validation testing"""
        mock_redis = MagicMock()
        return RuleManagementService(mock_redis)
    
    def test_validate_rule_whitespace_client_id(self, rule_service):
        """Test rule validation with whitespace-only client_id"""
        rule = RateLimitRule(
            client_id="   ",  # Whitespace only
            endpoint="/api/test",
            http_method="GET",
            limit=50,
            window_seconds=60,
            burst=75
        )
        
        with pytest.raises(RuleValidationError, match="client_id cannot be empty"):
            rule_service.validate_rule(rule)
    
    def test_validate_rule_all_http_methods(self, rule_service):
        """Test rule validation with all valid HTTP methods"""
        valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        
        for method in valid_methods:
            rule = RateLimitRule(
                client_id="client1",
                endpoint="/api/test",
                http_method=method,
                limit=50,
                window_seconds=60,
                burst=75
            )
            
            # Should not raise exception
            rule_service.validate_rule(rule)
    
    def test_validate_rule_boundary_values(self, rule_service):
        """Test rule validation with boundary values"""
        # Test minimum valid values
        rule = RateLimitRule(
            client_id="c",
            endpoint="/",
            http_method="GET",
            limit=1,
            window_seconds=1,
            burst=1
        )
        
        rule_service.validate_rule(rule)  # Should pass
        
        # Test maximum valid values
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=100000,
            window_seconds=86400,
            burst=200000
        )
        
        rule_service.validate_rule(rule)  # Should pass
    
    def test_validate_rule_multiple_errors(self, rule_service):
        """Test rule validation with multiple errors"""
        rule = RateLimitRule(
            client_id="",  # Error 1
            endpoint="",   # Error 2
            http_method="INVALID",  # Error 3
            limit=-1,      # Error 4
            window_seconds=0,  # Error 5
            burst=-1       # Error 6
        )
        
        with pytest.raises(RuleValidationError) as exc_info:
            rule_service.validate_rule(rule)
        
        error_message = str(exc_info.value)
        assert "client_id cannot be empty" in error_message
        assert "endpoint cannot be empty" in error_message
        assert "http_method must be one of" in error_message
        assert "limit must be positive" in error_message
        assert "window_seconds must be positive" in error_message