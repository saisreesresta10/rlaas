"""Unit tests for Lua script integration in RedisStateManager"""

import pytest
import pytest_asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from rlaas.redis_state import RedisStateManager
from rlaas.redis_client import RedisClientManager
from rlaas.models import RateLimitRule, TokenBucketResult


class TestLuaScriptIntegration:
    """Test Lua script integration in RedisStateManager"""
    
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
            limit=100,  # 100 requests per window
            window_seconds=60,  # 60 second window
            burst=120  # 120 token burst capacity
        )
    
    async def test_atomic_refill_and_consume_success(self, redis_state_manager, sample_rule):
        """Test successful atomic refill and consume operation"""
        current_time = 1640995200.0
        
        # Mock Lua script execution to return success with 99 remaining tokens
        redis_state_manager.execute_lua_script = AsyncMock(return_value=[1, 99])
        
        result = await redis_state_manager.atomic_refill_and_consume(
            "user_123", "/api/orders", "POST", sample_rule, 1, current_time
        )
        
        assert isinstance(result, TokenBucketResult)
        assert result.success is True
        assert result.remaining_tokens == 99
        assert result.retry_after_ms is None
        assert result.reset_after_ms is not None
        
        # Verify Lua script was called with correct parameters
        redis_state_manager.execute_lua_script.assert_called_once()
        call_args = redis_state_manager.execute_lua_script.call_args
        
        # Check keys
        assert call_args[0][1] == ["rate_limit:user_123:/api/orders:POST"]
        
        # Check arguments
        args = call_args[0][2]
        assert args[0] == str(current_time)
        assert args[1] == str(sample_rule.get_refill_rate())
        assert args[2] == str(sample_rule.burst)
        assert args[3] == "1"  # tokens to consume
        assert args[4] == "120"  # TTL (window_seconds * 2)
    
    async def test_atomic_refill_and_consume_blocked(self, redis_state_manager, sample_rule):
        """Test blocked atomic refill and consume operation"""
        current_time = 1640995200.0
        
        # Mock Lua script execution to return failure with 0 remaining tokens
        redis_state_manager.execute_lua_script = AsyncMock(return_value=[0, 0])
        
        result = await redis_state_manager.atomic_refill_and_consume(
            "user_123", "/api/orders", "POST", sample_rule, 1, current_time
        )
        
        assert isinstance(result, TokenBucketResult)
        assert result.success is False
        assert result.remaining_tokens == 0
        assert result.retry_after_ms is not None
        assert result.reset_after_ms is None
        
        # Retry time should be calculated based on refill rate
        expected_retry_ms = int((1.0 / sample_rule.get_refill_rate()) * 1000)
        assert result.retry_after_ms == expected_retry_ms
    
    async def test_atomic_refill_and_consume_multiple_tokens(self, redis_state_manager, sample_rule):
        """Test atomic operation with multiple token consumption"""
        current_time = 1640995200.0
        
        # Mock Lua script execution to return success with 95 remaining tokens
        redis_state_manager.execute_lua_script = AsyncMock(return_value=[1, 95])
        
        result = await redis_state_manager.atomic_refill_and_consume(
            "user_123", "/api/orders", "POST", sample_rule, 5, current_time
        )
        
        assert result.success is True
        assert result.remaining_tokens == 95
        
        # Verify tokens_to_consume parameter
        call_args = redis_state_manager.execute_lua_script.call_args
        args = call_args[0][2]
        assert args[3] == "5"  # tokens to consume
    
    async def test_atomic_refill_and_consume_default_time(self, redis_state_manager, sample_rule):
        """Test atomic operation with default current time"""
        redis_state_manager.execute_lua_script = AsyncMock(return_value=[1, 99])
        
        with patch('time.time', return_value=1640995200.0):
            result = await redis_state_manager.atomic_refill_and_consume(
                "user_123", "/api/orders", "POST", sample_rule, 1
            )
        
        assert result.success is True
        
        # Verify time parameter was set
        call_args = redis_state_manager.execute_lua_script.call_args
        args = call_args[0][2]
        assert args[0] == "1640995200.0"
    
    async def test_atomic_get_and_refill_success(self, redis_state_manager, sample_rule):
        """Test successful atomic get and refill operation"""
        current_time = 1640995200.0
        
        # Mock Lua script execution to return 75 tokens
        redis_state_manager.execute_lua_script = AsyncMock(return_value=75)
        
        result = await redis_state_manager.atomic_get_and_refill(
            "user_123", "/api/orders", "POST", sample_rule, current_time
        )
        
        assert result == 75
        
        # Verify Lua script was called with correct parameters
        redis_state_manager.execute_lua_script.assert_called_once()
        call_args = redis_state_manager.execute_lua_script.call_args
        
        # Check keys
        assert call_args[0][1] == ["rate_limit:user_123:/api/orders:POST"]
        
        # Check arguments (no tokens_to_consume for get_and_refill)
        args = call_args[0][2]
        assert args[0] == str(current_time)
        assert args[1] == str(sample_rule.get_refill_rate())
        assert args[2] == str(sample_rule.burst)
        assert args[3] == "120"  # TTL
    
    async def test_create_or_update_bucket_with_rule_new_bucket(self, redis_state_manager, sample_rule):
        """Test creating new bucket with rule"""
        current_time = 1640995200.0
        
        # Mock no existing state
        redis_state_manager.get_bucket_state = AsyncMock(return_value=None)
        redis_state_manager.set_bucket_state = AsyncMock()
        redis_state_manager.set_rule = AsyncMock()
        
        result = await redis_state_manager.create_or_update_bucket_with_rule(
            "user_123", "/api/orders", "POST", sample_rule, current_time=current_time
        )
        
        # Should create new state with full burst capacity
        assert result.tokens == 120.0  # Full burst capacity
        assert result.last_refill == current_time
        assert result.rule == sample_rule
        
        # Verify state and rule were stored
        redis_state_manager.set_bucket_state.assert_called_once()
        redis_state_manager.set_rule.assert_called_once_with(sample_rule)
    
    async def test_create_or_update_bucket_preserve_tokens(self, redis_state_manager, sample_rule):
        """Test updating bucket while preserving existing tokens"""
        from rlaas.models import TokenBucketState
        
        current_time = 1640995200.0
        
        # Mock existing state with 50 tokens
        existing_rule = RateLimitRule(
            client_id="user_123",
            endpoint="/api/orders", 
            http_method="POST",
            limit=50,
            window_seconds=60,
            burst=60
        )
        existing_state = TokenBucketState(
            tokens=50.0,
            last_refill=current_time - 30.0,
            rule=existing_rule
        )
        
        redis_state_manager.get_bucket_state = AsyncMock(return_value=existing_state)
        redis_state_manager.set_bucket_state = AsyncMock()
        redis_state_manager.set_rule = AsyncMock()
        
        result = await redis_state_manager.create_or_update_bucket_with_rule(
            "user_123", "/api/orders", "POST", sample_rule, preserve_tokens=True, current_time=current_time
        )
        
        # Should preserve existing tokens (50) since it's less than new burst (120)
        assert result.tokens == 50.0
        assert result.last_refill == current_time
        assert result.rule == sample_rule
    
    async def test_create_or_update_bucket_cap_preserved_tokens(self, redis_state_manager, sample_rule):
        """Test updating bucket with tokens capped at new burst capacity"""
        from rlaas.models import TokenBucketState
        
        current_time = 1640995200.0
        
        # Mock existing state with 150 tokens (more than new burst of 120)
        existing_rule = RateLimitRule(
            client_id="user_123",
            endpoint="/api/orders",
            http_method="POST", 
            limit=200,
            window_seconds=60,
            burst=200
        )
        existing_state = TokenBucketState(
            tokens=150.0,
            last_refill=current_time - 30.0,
            rule=existing_rule
        )
        
        redis_state_manager.get_bucket_state = AsyncMock(return_value=existing_state)
        redis_state_manager.set_bucket_state = AsyncMock()
        redis_state_manager.set_rule = AsyncMock()
        
        result = await redis_state_manager.create_or_update_bucket_with_rule(
            "user_123", "/api/orders", "POST", sample_rule, preserve_tokens=True, current_time=current_time
        )
        
        # Should cap tokens at new burst capacity (120)
        assert result.tokens == 120.0
        assert result.rule == sample_rule
    
    async def test_create_or_update_bucket_no_preserve(self, redis_state_manager, sample_rule):
        """Test updating bucket without preserving tokens"""
        from rlaas.models import TokenBucketState
        
        current_time = 1640995200.0
        
        # Mock existing state
        existing_state = TokenBucketState(
            tokens=50.0,
            last_refill=current_time - 30.0,
            rule=sample_rule
        )
        
        redis_state_manager.get_bucket_state = AsyncMock(return_value=existing_state)
        redis_state_manager.set_bucket_state = AsyncMock()
        redis_state_manager.set_rule = AsyncMock()
        
        result = await redis_state_manager.create_or_update_bucket_with_rule(
            "user_123", "/api/orders", "POST", sample_rule, preserve_tokens=False, current_time=current_time
        )
        
        # Should reset to full burst capacity regardless of existing tokens
        assert result.tokens == 120.0
        assert result.last_refill == current_time
        assert result.rule == sample_rule