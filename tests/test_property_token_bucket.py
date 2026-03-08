"""Property-based tests for token bucket service"""

import pytest
import time
from hypothesis import given, strategies as st, assume
from hypothesis import settings, HealthCheck

from rlaas.token_bucket import TokenBucketService
from rlaas.models import RateLimitRule, TokenBucketState


class TestPropertyTokenBucketService:
    """Property-based tests for TokenBucketService correctness properties"""
    
    @pytest.fixture
    def service(self):
        """Create TokenBucketService instance"""
        return TokenBucketService()
    
    @given(
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000),
        time_elapsed=st.floats(min_value=0.0, max_value=7200.0, allow_nan=False, allow_infinity=False),
        initial_tokens=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_token_bucket_refill_rate_consistency_property(self, service, limit, window_seconds, 
                                                          burst, time_elapsed, initial_tokens):
        """
        Property 1: Token Bucket Refill Rate Consistency
        For any token bucket with a configured refill rate, after any time period T, 
        the number of tokens added should equal the refill rate multiplied by T, 
        capped at the burst capacity.
        **Validates: Requirements 2.1**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        # Cap initial tokens at burst capacity
        assume(initial_tokens <= burst)
        
        rule = RateLimitRule(
            client_id="test_client",
            endpoint="/test",
            http_method="GET",
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        initial_time = 1640995200.0
        current_time = initial_time + time_elapsed
        
        initial_state = TokenBucketState(
            tokens=initial_tokens,
            last_refill=initial_time,
            rule=rule
        )
        
        # Refill tokens
        new_state = service.refill_tokens(initial_state, current_time)
        
        # Calculate expected tokens
        refill_rate = rule.get_refill_rate()
        tokens_to_add = refill_rate * time_elapsed
        expected_tokens = min(initial_tokens + tokens_to_add, float(burst))
        
        # Verify refill rate consistency (use more reasonable tolerance for floating point)
        assert abs(new_state.tokens - expected_tokens) < 1e-5, \
            f"Expected {expected_tokens}, got {new_state.tokens}"
        assert new_state.last_refill == current_time
        assert new_state.rule == rule
        
        # Verify tokens never exceed burst capacity
        assert new_state.tokens <= burst, \
            f"Tokens {new_state.tokens} exceeded burst capacity {burst}"
    
    @given(
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000),
        tokens=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_burst_capacity_invariant_property(self, service, limit, window_seconds, burst, tokens):
        """
        Property 2: Burst Capacity Invariant
        For any token bucket operation (refill or consumption), the resulting token count 
        should never exceed the configured burst capacity.
        **Validates: Requirements 2.2**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        
        rule = RateLimitRule(
            client_id="test_client",
            endpoint="/test",
            http_method="GET",
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        # Test initial bucket creation
        initial_state = service.create_initial_bucket_state(rule)
        assert initial_state.tokens <= burst, \
            f"Initial tokens {initial_state.tokens} exceeded burst capacity {burst}"
        
        # Test refill operation with various time periods
        current_time = time.time()
        state = TokenBucketState(
            tokens=min(tokens, float(burst)),  # Ensure starting tokens don't exceed burst
            last_refill=current_time - 3600.0,  # 1 hour ago
            rule=rule
        )
        
        # Refill with large time elapsed (should be capped at burst)
        refilled_state = service.refill_tokens(state, current_time)
        assert refilled_state.tokens <= burst, \
            f"Refilled tokens {refilled_state.tokens} exceeded burst capacity {burst}"
        
        # Test consumption (if tokens available)
        if refilled_state.tokens >= 1.0:
            consumed_state = service.consume_tokens(refilled_state, 1)
            assert consumed_state.tokens <= burst, \
                f"Tokens after consumption {consumed_state.tokens} exceeded burst capacity {burst}"
    
    @given(
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000),
        initial_tokens=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        tokens_to_consume=st.integers(min_value=1, max_value=10)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_token_consumption_atomicity_property(self, service, limit, window_seconds, burst, 
                                                 initial_tokens, tokens_to_consume):
        """
        Property 3: Token Consumption Atomicity
        For any rate limit check request, if the request is allowed, exactly the requested 
        number of tokens should be consumed from the bucket, and if blocked, the token count 
        should remain unchanged.
        **Validates: Requirements 1.4, 2.3, 2.4**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        # Cap initial tokens at burst capacity
        assume(initial_tokens <= burst)
        
        rule = RateLimitRule(
            client_id="test_client",
            endpoint="/test",
            http_method="GET",
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        current_time = time.time()
        initial_state = TokenBucketState(
            tokens=initial_tokens,
            last_refill=current_time,
            rule=rule
        )
        
        # Process token request
        result, final_state = service.process_token_request(
            initial_state, tokens_to_consume, current_time
        )
        
        if result.success:
            # If allowed, exactly tokens_to_consume should be consumed
            # (accounting for potential refill that happened)
            refilled_tokens = min(initial_tokens, float(burst))  # No refill since same time
            expected_final_tokens = refilled_tokens - tokens_to_consume
            
            assert abs(final_state.tokens - expected_final_tokens) < 1e-6, \
                f"Expected {expected_final_tokens} tokens after consumption, got {final_state.tokens}"
            assert result.remaining_tokens == int(final_state.tokens)
            assert result.retry_after_ms is None
            assert result.reset_after_ms is not None
        else:
            # If blocked, token count should remain unchanged (after refill)
            expected_tokens = min(initial_tokens, float(burst))  # No refill since same time
            assert abs(final_state.tokens - expected_tokens) < 1e-6, \
                f"Expected {expected_tokens} tokens when blocked, got {final_state.tokens}"
            assert result.remaining_tokens == int(final_state.tokens)
            assert result.retry_after_ms is not None
            assert result.reset_after_ms is None
        
        # Verify token count never goes negative
        assert final_state.tokens >= 0, f"Token count went negative: {final_state.tokens}"
        
        # Verify token count never exceeds burst
        assert final_state.tokens <= burst, \
            f"Token count {final_state.tokens} exceeded burst capacity {burst}"
    
    @given(
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000),
        tokens=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        tokens_needed=st.integers(min_value=1, max_value=100)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_time_calculations_consistency_property(self, service, limit, window_seconds, 
                                                   burst, tokens, tokens_needed):
        """
        Property: Time calculations should be consistent with refill rate
        **Validates: Requirements 2.1, 2.2**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        # Cap tokens at burst capacity
        assume(tokens <= burst)
        
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
            last_refill=time.time(),
            rule=rule
        )
        
        # Test time until tokens available
        time_until_available = service.calculate_time_until_tokens_available(state, tokens_needed)
        
        if tokens >= tokens_needed:
            # If tokens already available, time should be 0
            assert time_until_available == 0.0
        else:
            # If tokens not available, time should be calculated correctly
            expected_time = (tokens_needed - tokens) / rule.get_refill_rate()
            assert abs(time_until_available - expected_time) < 1e-6, \
                f"Expected {expected_time}s, got {time_until_available}s"
        
        # Test time until full
        time_until_full = service.calculate_time_until_full(state)
        
        if tokens >= burst:
            # If already full, time should be 0
            assert time_until_full == 0.0
        else:
            # If not full, time should be calculated correctly
            expected_time = (burst - tokens) / rule.get_refill_rate()
            assert abs(time_until_full - expected_time) < 1e-6, \
                f"Expected {expected_time}s until full, got {time_until_full}s"
    
    @given(
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_bucket_info_consistency_property(self, service, limit, window_seconds, burst):
        """
        Property: Bucket info should always reflect current state accurately
        **Validates: Requirements 2.1, 2.2**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        
        rule = RateLimitRule(
            client_id="test_client",
            endpoint="/test",
            http_method="GET",
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        # Create state with some tokens
        current_time = time.time()
        state = TokenBucketState(
            tokens=float(burst) / 2,  # Half full
            last_refill=current_time - 30.0,  # 30 seconds ago
            rule=rule
        )
        
        # Get bucket info
        info = service.get_bucket_info(state, current_time)
        
        # Verify info consistency
        assert info["max_tokens"] == burst
        assert info["refill_rate"] == rule.get_refill_rate()
        assert info["rule"]["limit"] == limit
        assert info["rule"]["window_seconds"] == window_seconds
        assert info["rule"]["burst"] == burst
        
        # Verify current tokens after refill
        expected_tokens = min(float(burst) / 2 + rule.get_refill_rate() * 30.0, float(burst))
        assert abs(info["current_tokens"] - expected_tokens) < 1e-6
        
        # Verify time calculations
        if info["current_tokens"] >= burst:
            assert info["time_until_full"] == 0.0
        else:
            expected_time_until_full = (burst - info["current_tokens"]) / rule.get_refill_rate()
            assert abs(info["time_until_full"] - expected_time_until_full) < 1e-6