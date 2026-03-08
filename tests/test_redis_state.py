"""Unit tests for RedisStateManager"""

import pytest
import pytest_asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as redis

from rlaas.redis_state import RedisStateManager
from rlaas.redis_client import RedisClientManager
from rlaas.models import RateLimitRule, TokenBucketState


class TestRedisStateManager:
    """Test RedisStateManager functionality"""
    
    @pytest.fixture
    def mock_redis_client_manager(self):
        """Create mock Redis client manager"""
        manager = MagicMock(spec=RedisClientManager)
        manager.client = AsyncMock()
        return manager
    
    @pytest.fixture
    def redis_state_manager(self, mock_redis_client_manager):
        """Create RedisStateManager with mock client"""
        return RedisStateManager(mock_redis_client_manager)
    
    @pytest.fixture
    def sample_rule(self):
        """Create sample rate limit rule"""
        return RateLimitRule(
            client_id="user_123",
            endpoint="/api/orders",
            http_method="POST",
            limit=100,
            window_seconds=60,
            burst=120
        )
    
    @pytest.fixture
    def sample_bucket_state(self, sample_rule):
        """Create sample token bucket state"""
        return TokenBucketState(
            tokens=75.5,
            last_refill=1640995200.123,
            rule=sample_rule
        )
    
    def test_generate_bucket_key(self, redis_state_manager):
        """Test bucket key generation"""
        key = redis_state_manager.generate_bucket_key("user_123", "/api/orders", "POST")
        assert key == "rate_limit:user_123:/api/orders:POST"
    
    def test_generate_rule_key(self, redis_state_manager):
        """Test rule key generation"""
        key = redis_state_manager.generate_rule_key("user_123", "/api/orders", "POST")
        assert key == "rule:user_123:/api/orders:POST"
    
    def test_serialize_bucket_state(self, redis_state_manager, sample_bucket_state):
        """Test bucket state serialization"""
        serialized = redis_state_manager.serialize_bucket_state(sample_bucket_state)
        data = json.loads(serialized)
        
        assert data["tokens"] == 75.5
        assert data["last_refill"] == 1640995200.123
        assert data["limit"] == 100
        assert data["window_seconds"] == 60
        assert data["burst"] == 120
        assert data["client_id"] == "user_123"
        assert data["endpoint"] == "/api/orders"
        assert data["http_method"] == "POST"
    
    def test_deserialize_bucket_state(self, redis_state_manager, sample_rule):
        """Test bucket state deserialization"""
        data = {
            "tokens": 75.5,
            "last_refill": 1640995200.123,
            "limit": 100,
            "window_seconds": 60,
            "burst": 120,
            "client_id": "user_123",
            "endpoint": "/api/orders",
            "http_method": "POST"
        }
        serialized = json.dumps(data)
        
        state = redis_state_manager.deserialize_bucket_state(serialized)
        
        assert state.tokens == 75.5
        assert state.last_refill == 1640995200.123
        assert state.rule.client_id == "user_123"
        assert state.rule.endpoint == "/api/orders"
        assert state.rule.http_method == "POST"
        assert state.rule.limit == 100
        assert state.rule.window_seconds == 60
        assert state.rule.burst == 120
    
    def test_deserialize_bucket_state_invalid_json(self, redis_state_manager):
        """Test bucket state deserialization with invalid JSON"""
        with pytest.raises(ValueError, match="Failed to deserialize bucket state"):
            redis_state_manager.deserialize_bucket_state("invalid json")
    
    def test_deserialize_bucket_state_missing_fields(self, redis_state_manager):
        """Test bucket state deserialization with missing fields"""
        data = {"tokens": 75.5}  # Missing required fields
        serialized = json.dumps(data)
        
        with pytest.raises(ValueError, match="Failed to deserialize bucket state"):
            redis_state_manager.deserialize_bucket_state(serialized)
    
    def test_serialize_rule(self, redis_state_manager, sample_rule):
        """Test rule serialization"""
        with patch('time.time', return_value=1640995300.0):
            serialized = redis_state_manager.serialize_rule(sample_rule)
            data = json.loads(serialized)
            
            assert data["client_id"] == "user_123"
            assert data["endpoint"] == "/api/orders"
            assert data["http_method"] == "POST"
            assert data["limit"] == 100
            assert data["window_seconds"] == 60
            assert data["burst"] == 120
            assert data["created_at"] == 1640995300.0
    
    def test_deserialize_rule(self, redis_state_manager):
        """Test rule deserialization"""
        data = {
            "client_id": "user_123",
            "endpoint": "/api/orders",
            "http_method": "POST",
            "limit": 100,
            "window_seconds": 60,
            "burst": 120,
            "created_at": 1640995300.0
        }
        serialized = json.dumps(data)
        
        rule = redis_state_manager.deserialize_rule(serialized)
        
        assert rule.client_id == "user_123"
        assert rule.endpoint == "/api/orders"
        assert rule.http_method == "POST"
        assert rule.limit == 100
        assert rule.window_seconds == 60
        assert rule.burst == 120
    
    def test_deserialize_rule_invalid_json(self, redis_state_manager):
        """Test rule deserialization with invalid JSON"""
        with pytest.raises(ValueError, match="Failed to deserialize rule"):
            redis_state_manager.deserialize_rule("invalid json")
    
    async def test_get_bucket_state_found(self, redis_state_manager, sample_bucket_state):
        """Test getting bucket state when it exists"""
        # Setup mock to return serialized state
        serialized_state = redis_state_manager.serialize_bucket_state(sample_bucket_state)
        redis_state_manager.redis_client_manager.client.get.return_value = serialized_state
        
        result = await redis_state_manager.get_bucket_state("user_123", "/api/orders", "POST")
        
        assert result is not None
        assert result.tokens == 75.5
        assert result.last_refill == 1640995200.123
        assert result.rule.client_id == "user_123"
        
        # Verify Redis was called with correct key
        redis_state_manager.redis_client_manager.client.get.assert_called_once_with(
            "rate_limit:user_123:/api/orders:POST"
        )
    
    async def test_get_bucket_state_not_found(self, redis_state_manager):
        """Test getting bucket state when it doesn't exist"""
        redis_state_manager.redis_client_manager.client.get.return_value = None
        
        result = await redis_state_manager.get_bucket_state("user_123", "/api/orders", "POST")
        
        assert result is None
    
    async def test_get_bucket_state_redis_error(self, redis_state_manager):
        """Test getting bucket state with Redis error"""
        redis_state_manager.redis_client_manager.client.get.side_effect = redis.RedisError("Connection failed")
        
        with pytest.raises(redis.RedisError):
            await redis_state_manager.get_bucket_state("user_123", "/api/orders", "POST")
    
    async def test_get_bucket_state_corrupted_data(self, redis_state_manager):
        """Test getting bucket state with corrupted data"""
        redis_state_manager.redis_client_manager.client.get.return_value = "corrupted json"
        
        result = await redis_state_manager.get_bucket_state("user_123", "/api/orders", "POST")
        
        # Should return None for corrupted data
        assert result is None
    
    async def test_set_bucket_state_success(self, redis_state_manager, sample_bucket_state):
        """Test setting bucket state successfully"""
        redis_state_manager.redis_client_manager.client.setex = AsyncMock()
        
        await redis_state_manager.set_bucket_state("user_123", "/api/orders", "POST", sample_bucket_state)
        
        # Verify Redis was called with correct parameters
        expected_key = "rate_limit:user_123:/api/orders:POST"
        expected_ttl = 120  # window_seconds * 2
        
        redis_state_manager.redis_client_manager.client.setex.assert_called_once()
        call_args = redis_state_manager.redis_client_manager.client.setex.call_args
        
        assert call_args[0][0] == expected_key
        assert call_args[0][1] == expected_ttl
        # Third argument should be serialized state (JSON string)
        assert isinstance(call_args[0][2], str)
    
    async def test_set_bucket_state_custom_ttl(self, redis_state_manager, sample_bucket_state):
        """Test setting bucket state with custom TTL"""
        redis_state_manager.redis_client_manager.client.setex = AsyncMock()
        
        await redis_state_manager.set_bucket_state(
            "user_123", "/api/orders", "POST", sample_bucket_state, ttl_seconds=300
        )
        
        # Verify custom TTL was used
        call_args = redis_state_manager.redis_client_manager.client.setex.call_args
        assert call_args[0][1] == 300
    
    async def test_set_bucket_state_redis_error(self, redis_state_manager, sample_bucket_state):
        """Test setting bucket state with Redis error"""
        redis_state_manager.redis_client_manager.client.setex.side_effect = redis.RedisError("Connection failed")
        
        with pytest.raises(redis.RedisError):
            await redis_state_manager.set_bucket_state("user_123", "/api/orders", "POST", sample_bucket_state)
    
    async def test_get_rule_found(self, redis_state_manager, sample_rule):
        """Test getting rule when it exists"""
        serialized_rule = redis_state_manager.serialize_rule(sample_rule)
        redis_state_manager.redis_client_manager.client.get.return_value = serialized_rule
        
        result = await redis_state_manager.get_rule("user_123", "/api/orders", "POST")
        
        assert result is not None
        assert result.client_id == "user_123"
        assert result.endpoint == "/api/orders"
        assert result.http_method == "POST"
        assert result.limit == 100
        assert result.window_seconds == 60
        assert result.burst == 120
        
        # Verify Redis was called with correct key
        redis_state_manager.redis_client_manager.client.get.assert_called_once_with(
            "rule:user_123:/api/orders:POST"
        )
    
    async def test_get_rule_not_found(self, redis_state_manager):
        """Test getting rule when it doesn't exist"""
        redis_state_manager.redis_client_manager.client.get.return_value = None
        
        result = await redis_state_manager.get_rule("user_123", "/api/orders", "POST")
        
        assert result is None
    
    async def test_set_rule_success(self, redis_state_manager, sample_rule):
        """Test setting rule successfully"""
        redis_state_manager.redis_client_manager.client.set = AsyncMock()
        
        await redis_state_manager.set_rule(sample_rule)
        
        # Verify Redis was called with correct parameters
        expected_key = "rule:user_123:/api/orders:POST"
        
        redis_state_manager.redis_client_manager.client.set.assert_called_once()
        call_args = redis_state_manager.redis_client_manager.client.set.call_args
        
        assert call_args[0][0] == expected_key
        # Second argument should be serialized rule (JSON string)
        assert isinstance(call_args[0][1], str)
    
    async def test_delete_rule_success(self, redis_state_manager):
        """Test deleting rule successfully"""
        redis_state_manager.redis_client_manager.client.delete.return_value = 1
        
        result = await redis_state_manager.delete_rule("user_123", "/api/orders", "POST")
        
        assert result is True
        redis_state_manager.redis_client_manager.client.delete.assert_called_once_with(
            "rule:user_123:/api/orders:POST"
        )
    
    async def test_delete_rule_not_found(self, redis_state_manager):
        """Test deleting rule that doesn't exist"""
        redis_state_manager.redis_client_manager.client.delete.return_value = 0
        
        result = await redis_state_manager.delete_rule("user_123", "/api/orders", "POST")
        
        assert result is False
    
    async def test_execute_lua_script_success(self, redis_state_manager):
        """Test executing Lua script successfully"""
        redis_state_manager.redis_client_manager.client.eval.return_value = [1, 42]
        
        result = await redis_state_manager.execute_lua_script(
            "return {1, 42}",
            ["key1", "key2"],
            ["arg1", "arg2"]
        )
        
        assert result == [1, 42]
        redis_state_manager.redis_client_manager.client.eval.assert_called_once_with(
            "return {1, 42}",
            2,  # Number of keys
            "key1", "key2",  # Keys
            "arg1", "arg2"   # Args
        )
    
    async def test_execute_lua_script_error(self, redis_state_manager):
        """Test executing Lua script with error"""
        redis_state_manager.redis_client_manager.client.eval.side_effect = redis.RedisError("Script error")
        
        with pytest.raises(redis.RedisError):
            await redis_state_manager.execute_lua_script("return 1", ["key1"], ["arg1"])
    
    async def test_health_check_success(self, redis_state_manager):
        """Test health check success"""
        redis_state_manager.redis_client_manager.health_check.return_value = True
        
        result = await redis_state_manager.health_check()
        
        assert result is True
        redis_state_manager.redis_client_manager.health_check.assert_called_once()
    
    async def test_health_check_failure(self, redis_state_manager):
        """Test health check failure"""
        redis_state_manager.redis_client_manager.health_check.return_value = False
        
        result = await redis_state_manager.health_check()
        
        assert result is False
    
    async def test_get_bucket_info_complete(self, redis_state_manager, sample_bucket_state, sample_rule):
        """Test getting bucket info when both state and rule exist"""
        # Mock both state and rule retrieval
        redis_state_manager.get_bucket_state = AsyncMock(return_value=sample_bucket_state)
        redis_state_manager.get_rule = AsyncMock(return_value=sample_rule)
        
        result = await redis_state_manager.get_bucket_info("user_123", "/api/orders", "POST")
        
        assert result is not None
        assert result["bucket_key"] == "rate_limit:user_123:/api/orders:POST"
        assert result["rule_key"] == "rule:user_123:/api/orders:POST"
        assert result["has_state"] is True
        assert result["has_rule"] is True
        assert result["current_tokens"] == 75.5
        assert result["last_refill"] == 1640995200.123
        assert result["state_rule"]["limit"] == 100
        assert result["configured_rule"]["limit"] == 100
    
    async def test_get_bucket_info_not_found(self, redis_state_manager):
        """Test getting bucket info when neither state nor rule exist"""
        redis_state_manager.get_bucket_state = AsyncMock(return_value=None)
        redis_state_manager.get_rule = AsyncMock(return_value=None)
        
        result = await redis_state_manager.get_bucket_info("user_123", "/api/orders", "POST")
        
        assert result is None