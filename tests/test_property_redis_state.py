"""Property-based tests for Redis state management"""

import pytest
import json
import time
from hypothesis import given, strategies as st, assume
from hypothesis import settings, HealthCheck
from unittest.mock import MagicMock

from rlaas.redis_state import RedisStateManager
from rlaas.redis_client import RedisClientManager
from rlaas.models import RateLimitRule, TokenBucketState


class TestPropertyRedisStateManager:
    """Property-based tests for Redis state management correctness properties"""
    
    @pytest.fixture
    def mock_redis_client_manager(self):
        """Create mock Redis client manager"""
        manager = MagicMock(spec=RedisClientManager)
        return manager
    
    @pytest.fixture
    def redis_state_manager(self, mock_redis_client_manager):
        """Create RedisStateManager with mock client"""
        return RedisStateManager(mock_redis_client_manager)
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"])
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_redis_key_generation_consistency_property(self, redis_state_manager, 
                                                      client_id, endpoint, http_method):
        """
        Property 5: Redis Key Generation Consistency
        For any combination of client_id, endpoint, and http_method, the generated Redis key 
        should follow the pattern rate_limit:{client_id}:{endpoint}:{http_method}.
        **Validates: Requirements 3.2**
        """
        # Generate bucket key
        bucket_key = redis_state_manager.generate_bucket_key(client_id, endpoint, http_method)
        expected_bucket_key = f"rate_limit:{client_id}:{endpoint}:{http_method}"
        
        assert bucket_key == expected_bucket_key, \
            f"Expected bucket key '{expected_bucket_key}', got '{bucket_key}'"
        
        # Generate rule key
        rule_key = redis_state_manager.generate_rule_key(client_id, endpoint, http_method)
        expected_rule_key = f"rule:{client_id}:{endpoint}:{http_method}"
        
        assert rule_key == expected_rule_key, \
            f"Expected rule key '{expected_rule_key}', got '{rule_key}'"
        
        # Verify keys are deterministic - calling multiple times should return same result
        assert redis_state_manager.generate_bucket_key(client_id, endpoint, http_method) == bucket_key
        assert redis_state_manager.generate_rule_key(client_id, endpoint, http_method) == rule_key
        
        # Verify keys are unique for different inputs
        if client_id != "different":
            different_bucket_key = redis_state_manager.generate_bucket_key("different", endpoint, http_method)
            assert different_bucket_key != bucket_key
        
        if endpoint != "/different":
            different_bucket_key = redis_state_manager.generate_bucket_key(client_id, "/different", http_method)
            assert different_bucket_key != bucket_key
        
        if http_method != "PATCH":
            different_bucket_key = redis_state_manager.generate_bucket_key(client_id, endpoint, "PATCH")
            assert different_bucket_key != bucket_key
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000),
        tokens=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
        last_refill=st.floats(min_value=1640995200.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_state_persistence_completeness_property(self, redis_state_manager, client_id, endpoint, 
                                                    http_method, limit, window_seconds, burst, 
                                                    tokens, last_refill):
        """
        Property 7: State Persistence Completeness
        For any token bucket operation, the Redis store should maintain current token count, 
        last refill timestamp, and rate configuration metadata.
        **Validates: Requirements 3.5**
        """
        # Ensure burst >= limit for valid configuration
        assume(burst >= limit)
        # Cap tokens at burst capacity
        assume(tokens <= burst)
        
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        state = TokenBucketState(
            tokens=tokens,
            last_refill=last_refill,
            rule=rule
        )
        
        # Test serialization completeness
        serialized_state = redis_state_manager.serialize_bucket_state(state)
        
        # Verify serialized data is valid JSON
        parsed_data = json.loads(serialized_state)
        
        # Verify all required fields are present
        required_fields = ["tokens", "last_refill", "limit", "window_seconds", "burst", 
                          "client_id", "endpoint", "http_method"]
        for field in required_fields:
            assert field in parsed_data, f"Missing required field: {field}"
        
        # Verify field values are correct
        assert parsed_data["tokens"] == tokens
        assert parsed_data["last_refill"] == last_refill
        assert parsed_data["limit"] == limit
        assert parsed_data["window_seconds"] == window_seconds
        assert parsed_data["burst"] == burst
        assert parsed_data["client_id"] == client_id
        assert parsed_data["endpoint"] == endpoint
        assert parsed_data["http_method"] == http_method
        
        # Test deserialization completeness
        deserialized_state = redis_state_manager.deserialize_bucket_state(serialized_state)
        
        # Verify deserialized state matches original
        assert abs(deserialized_state.tokens - tokens) < 1e-6
        assert abs(deserialized_state.last_refill - last_refill) < 1e-6
        assert deserialized_state.rule.client_id == client_id
        assert deserialized_state.rule.endpoint == endpoint
        assert deserialized_state.rule.http_method == http_method
        assert deserialized_state.rule.limit == limit
        assert deserialized_state.rule.window_seconds == window_seconds
        assert deserialized_state.rule.burst == burst
        
        # Test rule serialization completeness
        serialized_rule = redis_state_manager.serialize_rule(rule)
        parsed_rule_data = json.loads(serialized_rule)
        
        # Verify all rule fields are present
        rule_fields = ["client_id", "endpoint", "http_method", "limit", "window_seconds", "burst", "created_at"]
        for field in rule_fields:
            assert field in parsed_rule_data, f"Missing required rule field: {field}"
        
        # Verify rule field values
        assert parsed_rule_data["client_id"] == client_id
        assert parsed_rule_data["endpoint"] == endpoint
        assert parsed_rule_data["http_method"] == http_method
        assert parsed_rule_data["limit"] == limit
        assert parsed_rule_data["window_seconds"] == window_seconds
        assert parsed_rule_data["burst"] == burst
        assert isinstance(parsed_rule_data["created_at"], (int, float))
        
        # Test rule deserialization completeness
        deserialized_rule = redis_state_manager.deserialize_rule(serialized_rule)
        
        assert deserialized_rule.client_id == client_id
        assert deserialized_rule.endpoint == endpoint
        assert deserialized_rule.http_method == http_method
        assert deserialized_rule.limit == limit
        assert deserialized_rule.window_seconds == window_seconds
        assert deserialized_rule.burst == burst
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_serialization_roundtrip_consistency_property(self, redis_state_manager, client_id, 
                                                         endpoint, http_method, limit, 
                                                         window_seconds, burst):
        """
        Property: Serialization and deserialization should be perfect roundtrips
        **Validates: Requirements 3.5**
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
        
        # Test multiple roundtrips to ensure consistency
        for i in range(3):
            tokens = float(burst) * (i + 1) / 4  # Different token values
            last_refill = time.time() + i * 100
            
            original_state = TokenBucketState(
                tokens=tokens,
                last_refill=last_refill,
                rule=rule
            )
            
            # Serialize and deserialize
            serialized = redis_state_manager.serialize_bucket_state(original_state)
            deserialized = redis_state_manager.deserialize_bucket_state(serialized)
            
            # Verify perfect roundtrip
            assert abs(deserialized.tokens - original_state.tokens) < 1e-6
            assert abs(deserialized.last_refill - original_state.last_refill) < 1e-6
            assert deserialized.rule.client_id == original_state.rule.client_id
            assert deserialized.rule.endpoint == original_state.rule.endpoint
            assert deserialized.rule.http_method == original_state.rule.http_method
            assert deserialized.rule.limit == original_state.rule.limit
            assert deserialized.rule.window_seconds == original_state.rule.window_seconds
            assert deserialized.rule.burst == original_state.rule.burst
        
        # Test rule roundtrip
        serialized_rule = redis_state_manager.serialize_rule(rule)
        deserialized_rule = redis_state_manager.deserialize_rule(serialized_rule)
        
        assert deserialized_rule.client_id == rule.client_id
        assert deserialized_rule.endpoint == rule.endpoint
        assert deserialized_rule.http_method == rule.http_method
        assert deserialized_rule.limit == rule.limit
        assert deserialized_rule.window_seconds == rule.window_seconds
        assert deserialized_rule.burst == rule.burst
    
    @given(
        invalid_json=st.one_of(
            st.just("invalid json"),
            st.just("{incomplete"),
            st.just('{"missing": "fields"}'),
            st.just("null"),
            st.just("[]"),
            st.just("123")
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_deserialization_error_handling_property(self, redis_state_manager, invalid_json):
        """
        Property: Invalid JSON should always raise ValueError with descriptive message
        **Validates: Requirements 3.5**
        """
        # Test bucket state deserialization error handling
        with pytest.raises(ValueError, match="Failed to deserialize bucket state"):
            redis_state_manager.deserialize_bucket_state(invalid_json)
        
        # Test rule deserialization error handling
        with pytest.raises(ValueError, match="Failed to deserialize rule"):
            redis_state_manager.deserialize_rule(invalid_json)
    
    @given(
        client_id=st.text(min_size=1, max_size=100),
        endpoint=st.text(min_size=1, max_size=200),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"])
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_key_uniqueness_property(self, redis_state_manager, client_id, endpoint, http_method):
        """
        Property: Different client/endpoint/method combinations should generate unique keys
        **Validates: Requirements 3.2**
        """
        base_key = redis_state_manager.generate_bucket_key(client_id, endpoint, http_method)
        
        # Generate variations and ensure they're all different
        variations = [
            (client_id + "_diff", endpoint, http_method),
            (client_id, endpoint + "_diff", http_method),
            (client_id, endpoint, "GET" if http_method != "GET" else "POST"),
        ]
        
        for var_client, var_endpoint, var_method in variations:
            var_key = redis_state_manager.generate_bucket_key(var_client, var_endpoint, var_method)
            assert var_key != base_key, \
                f"Keys should be unique: '{base_key}' vs '{var_key}'"
        
        # Test rule keys too
        base_rule_key = redis_state_manager.generate_rule_key(client_id, endpoint, http_method)
        
        for var_client, var_endpoint, var_method in variations:
            var_rule_key = redis_state_manager.generate_rule_key(var_client, var_endpoint, var_method)
            assert var_rule_key != base_rule_key, \
                f"Rule keys should be unique: '{base_rule_key}' vs '{var_rule_key}'"