"""Property-based tests for data model validation"""

import pytest
from hypothesis import given, strategies as st, assume
from hypothesis import settings, HealthCheck

from rlaas.models import (
    RateLimitCheckRequest,
    RateLimitResponse,
    RateLimitRule,
    TokenBucketState,
    CircuitBreakerConfig,
)


class TestPropertyDataModelValidation:
    """Property-based tests for data model validation consistency
    
    **Feature: distributed-rate-limiter, Property 8: Rule Validation Consistency**
    **Validates: Requirements 4.1, 4.5**
    
    For any rate limit rule configuration, valid parameters should be accepted 
    and invalid parameters should be rejected with appropriate error messages.
    """
    
    # Valid HTTP methods for testing
    VALID_HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_check_request_validation_property(self, client_id, endpoint, http_method):
        """
        Property: Valid RateLimitCheckRequest parameters should always pass validation
        **Validates: Requirements 4.1, 4.5**
        """
        # Create request with valid parameters
        request = RateLimitCheckRequest(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        # Should not raise any exception
        request.validate()
        
        # Verify fields are set correctly
        assert request.client_id == client_id
        assert request.endpoint == endpoint
        assert request.http_method == http_method
    
    @given(
        client_id=st.one_of(st.just(""), st.none()),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_check_request_empty_client_id_property(self, client_id, endpoint, http_method):
        """
        Property: Empty or None client_id should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        request = RateLimitCheckRequest(
            client_id=client_id or "",  # Handle None case
            endpoint=endpoint,
            http_method=http_method
        )
        
        with pytest.raises(ValueError, match="All fields are required"):
            request.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.one_of(st.just(""), st.none()),
        http_method=st.sampled_from(VALID_HTTP_METHODS)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_check_request_empty_endpoint_property(self, client_id, endpoint, http_method):
        """
        Property: Empty or None endpoint should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        request = RateLimitCheckRequest(
            client_id=client_id,
            endpoint=endpoint or "",  # Handle None case
            http_method=http_method
        )
        
        with pytest.raises(ValueError, match="All fields are required"):
            request.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.text().filter(lambda x: x not in ["GET", "POST", "PUT", "DELETE", "PATCH"] and x != "")
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_check_request_invalid_http_method_property(self, client_id, endpoint, http_method):
        """
        Property: Invalid HTTP methods should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        request = RateLimitCheckRequest(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        with pytest.raises(ValueError, match="Invalid HTTP method"):
            request.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS),
        limit=st.integers(min_value=1, max_value=10000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=20000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_rule_valid_parameters_property(self, client_id, endpoint, http_method, 
                                                      limit, window_seconds, burst):
        """
        Property: Valid RateLimitRule parameters should always pass validation when burst >= limit
        **Validates: Requirements 4.1, 4.5**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        # Should not raise any exception
        rule.validate()
        
        # Verify fields are set correctly
        assert rule.client_id == client_id
        assert rule.endpoint == endpoint
        assert rule.http_method == http_method
        assert rule.limit == limit
        assert rule.window_seconds == window_seconds
        assert rule.burst == burst
        
        # Verify calculated properties
        assert rule.get_refill_rate() == limit / window_seconds
        expected_key = f"rate_limit:{client_id}:{endpoint}:{http_method}"
        assert rule.get_bucket_key() == expected_key
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS),
        limit=st.integers(max_value=0),  # Invalid: <= 0
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=20000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_rule_invalid_limit_property(self, client_id, endpoint, http_method,
                                                   limit, window_seconds, burst):
        """
        Property: Non-positive limit values should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS),
        limit=st.integers(min_value=1, max_value=10000),
        window_seconds=st.integers(max_value=0),  # Invalid: <= 0
        burst=st.integers(min_value=1, max_value=20000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_rule_invalid_window_property(self, client_id, endpoint, http_method,
                                                    limit, window_seconds, burst):
        """
        Property: Non-positive window_seconds values should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS),
        limit=st.integers(min_value=1, max_value=10000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(max_value=0)  # Invalid: <= 0
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_rule_invalid_burst_property(self, client_id, endpoint, http_method,
                                                   limit, window_seconds, burst):
        """
        Property: Non-positive burst values should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        with pytest.raises(ValueError, match="All numeric values must be positive"):
            rule.validate()
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS),
        limit=st.integers(min_value=2, max_value=10000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_rule_burst_less_than_limit_property(self, client_id, endpoint, http_method,
                                                           limit, window_seconds, burst):
        """
        Property: Burst capacity less than limit should always be rejected
        **Validates: Requirements 4.1, 4.5**
        """
        # Ensure burst < limit for this test
        assume(burst < limit)
        
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        with pytest.raises(ValueError, match="Burst capacity must be >= limit"):
            rule.validate()
    
    @given(
        remaining_tokens=st.integers(min_value=0, max_value=10000),
        reset_after_ms=st.integers(min_value=0, max_value=3600000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_response_allowed_property(self, remaining_tokens, reset_after_ms):
        """
        Property: Allowed responses should always have consistent structure
        **Validates: Requirements 4.1, 4.5**
        """
        response = RateLimitResponse.allowed_response(remaining_tokens, reset_after_ms)
        
        assert response.allowed is True
        assert response.remaining_tokens == remaining_tokens
        assert response.reset_after_ms == reset_after_ms
        assert response.retry_after_ms is None
    
    @given(
        retry_after_ms=st.integers(min_value=1, max_value=3600000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rate_limit_response_blocked_property(self, retry_after_ms):
        """
        Property: Blocked responses should always have consistent structure
        **Validates: Requirements 4.1, 4.5**
        """
        response = RateLimitResponse.blocked_response(retry_after_ms)
        
        assert response.allowed is False
        assert response.remaining_tokens is None
        assert response.reset_after_ms is None
        assert response.retry_after_ms == retry_after_ms
    
    @given(
        failure_threshold=st.integers(min_value=1, max_value=100),
        recovery_timeout=st.integers(min_value=1, max_value=3600),
        success_threshold=st.integers(min_value=1, max_value=100),
        timeout_ms=st.integers(min_value=1, max_value=10000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_circuit_breaker_config_property(self, failure_threshold, recovery_timeout,
                                            success_threshold, timeout_ms):
        """
        Property: CircuitBreakerConfig should accept any positive integer values
        **Validates: Requirements 4.1, 4.5**
        """
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            timeout_ms=timeout_ms
        )
        
        assert config.failure_threshold == failure_threshold
        assert config.recovery_timeout == recovery_timeout
        assert config.success_threshold == success_threshold
        assert config.timeout_ms == timeout_ms
    
    @given(
        tokens=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        last_refill=st.floats(min_value=0.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False),
        limit=st.integers(min_value=1, max_value=10000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=20000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_token_bucket_state_property(self, tokens, last_refill, limit, window_seconds, burst):
        """
        Property: TokenBucketState should handle valid float tokens and timestamps
        **Validates: Requirements 4.1, 4.5**
        """
        # Ensure burst >= limit for valid rule
        assume(burst >= limit)
        
        rule = RateLimitRule(
            client_id="test_client",
            endpoint="/test",
            http_method="GET",
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        state = TokenBucketState(
            tokens=tokens,
            last_refill=last_refill,
            rule=rule
        )
        
        assert state.tokens == tokens
        assert state.last_refill == last_refill
        assert state.rule == rule
        
        # Test can_consume method
        if tokens >= 1.0:
            assert state.can_consume(1) is True
        else:
            assert state.can_consume(1) is False
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(VALID_HTTP_METHODS)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_redis_key_generation_consistency_property(self, client_id, endpoint, http_method):
        """
        Property: Redis key generation should be consistent and follow the specified pattern
        **Validates: Requirements 4.1, 4.5**
        """
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=100,
            window_seconds=60,
            burst=120
        )
        
        expected_key = f"rate_limit:{client_id}:{endpoint}:{http_method}"
        assert rule.get_bucket_key() == expected_key
        
        # Key should be deterministic - calling multiple times should return same result
        assert rule.get_bucket_key() == rule.get_bucket_key()
        assert rule.get_bucket_key() == expected_key