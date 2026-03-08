"""Unit tests for core data models"""

import pytest
import time
from rlaas.models import (
    RateLimitCheckRequest,
    RateLimitResponse,
    RateLimitRule,
    TokenBucketState,
    TokenBucketResult,
    CircuitBreakerConfig,
)


class TestRateLimitCheckRequest:
    """Test RateLimitCheckRequest validation and behavior"""
    
    def test_valid_request(self):
        """Test valid request creation"""
        request = RateLimitCheckRequest(
            client_id="user_123",
            endpoint="/api/orders",
            http_method="POST"
        )
        request.validate()  # Should not raise
    
    def test_empty_fields_validation(self):
        """Test validation fails for empty fields"""
        with pytest.raises(ValueError, match="All fields are required"):
            request = RateLimitCheckRequest("", "/api/orders", "POST")
            request.validate()
        
        with pytest.raises(ValueError, match="All fields are required"):
            request = RateLimitCheckRequest("user_123", "", "POST")
            request.validate()
        
        with pytest.raises(ValueError, match="All fields are required"):
            request = RateLimitCheckRequest("user_123", "/api/orders", "")
            request.validate()
    
    def test_invalid_http_method(self):
        """Test validation fails for invalid HTTP methods"""
        with pytest.raises(ValueError, match="Invalid HTTP method"):
            request = RateLimitCheckRequest("user_123", "/api/orders", "INVALID")
            request.validate()
    
    def test_valid_http_methods(self):
        """Test all valid HTTP methods are accepted"""
        valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        for method in valid_methods:
            request = RateLimitCheckRequest("user_123", "/api/orders", method)
            request.validate()  # Should not raise


class TestRateLimitResponse:
    """Test RateLimitResponse creation and factory methods"""
    
    def test_allowed_response(self):
        """Test allowed response creation"""
        response = RateLimitResponse.allowed_response(remaining=42, reset_after=12000)
        
        assert response.allowed is True
        assert response.remaining_tokens == 42
        assert response.reset_after_ms == 12000
        assert response.retry_after_ms is None
    
    def test_blocked_response(self):
        """Test blocked response creation"""
        response = RateLimitResponse.blocked_response(retry_after=3000)
        
        assert response.allowed is False
        assert response.remaining_tokens is None
        assert response.reset_after_ms is None
        assert response.retry_after_ms == 3000


class TestRateLimitRule:
    """Test RateLimitRule validation and behavior"""
    
    def test_valid_rule(self):
        """Test valid rule creation"""
        rule = RateLimitRule(
            client_id="user_123",
            endpoint="/api/orders",
            http_method="POST",
            limit=100,
            window_seconds=60,
            burst=120
        )
        rule.validate()  # Should not raise
    
    def test_negative_values_validation(self):
        """Test validation fails for negative values"""
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule = RateLimitRule("user_123", "/api/orders", "POST", -1, 60, 120)
            rule.validate()
        
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule = RateLimitRule("user_123", "/api/orders", "POST", 100, -1, 120)
            rule.validate()
        
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, -1)
            rule.validate()
    
    def test_burst_less_than_limit_validation(self):
        """Test validation fails when burst < limit"""
        with pytest.raises(ValueError, match="Burst capacity must be >= limit"):
            rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 50)
            rule.validate()
    
    def test_refill_rate_calculation(self):
        """Test refill rate calculation"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        assert rule.get_refill_rate() == pytest.approx(100 / 60, rel=1e-9)
    
    def test_bucket_key_generation(self):
        """Test Redis key generation"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        expected_key = "rate_limit:user_123:/api/orders:POST"
        assert rule.get_bucket_key() == expected_key


class TestTokenBucketState:
    """Test TokenBucketState behavior"""
    
    def test_refill_tokens(self):
        """Test token refill calculation"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        initial_time = time.time()
        
        state = TokenBucketState(
            tokens=50.0,
            last_refill=initial_time,
            rule=rule
        )
        
        # Simulate 30 seconds passing
        current_time = initial_time + 30.0
        new_state = state.refill_tokens(current_time)
        
        # Should add 50 tokens (100/60 * 30 = 50)
        expected_tokens = min(50.0 + 50.0, 120.0)  # Capped at burst
        assert new_state.tokens == pytest.approx(expected_tokens, rel=1e-9)
        assert new_state.last_refill == current_time
    
    def test_refill_tokens_capped_at_burst(self):
        """Test token refill is capped at burst capacity"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        initial_time = time.time()
        
        state = TokenBucketState(
            tokens=100.0,
            last_refill=initial_time,
            rule=rule
        )
        
        # Simulate 60 seconds passing (should add 100 tokens)
        current_time = initial_time + 60.0
        new_state = state.refill_tokens(current_time)
        
        # Should be capped at burst capacity
        assert new_state.tokens == 120.0
    
    def test_can_consume(self):
        """Test token consumption availability check"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        state = TokenBucketState(tokens=5.0, last_refill=time.time(), rule=rule)
        
        assert state.can_consume(1) is True
        assert state.can_consume(5) is True
        assert state.can_consume(6) is False
    
    def test_consume_tokens(self):
        """Test token consumption"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        state = TokenBucketState(tokens=5.0, last_refill=time.time(), rule=rule)
        
        new_state = state.consume(2)
        assert new_state.tokens == 3.0
    
    def test_consume_insufficient_tokens(self):
        """Test consumption fails when insufficient tokens"""
        rule = RateLimitRule("user_123", "/api/orders", "POST", 100, 60, 120)
        state = TokenBucketState(tokens=2.0, last_refill=time.time(), rule=rule)
        
        with pytest.raises(ValueError, match="Insufficient tokens"):
            state.consume(3)


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig default values"""
    
    def test_default_values(self):
        """Test default configuration values"""
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 30
        assert config.success_threshold == 3
        assert config.timeout_ms == 100
    
    def test_custom_values(self):
        """Test custom configuration values"""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=60,
            success_threshold=5,
            timeout_ms=200
        )
        
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 60
        assert config.success_threshold == 5
        assert config.timeout_ms == 200