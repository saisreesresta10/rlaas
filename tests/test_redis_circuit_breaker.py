"""Tests for Redis circuit breaker integration"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as redis

from rlaas.redis_client import RedisClientManager, RedisConfig, FailureMode
from rlaas.circuit_breaker import CircuitBreakerError, CircuitBreakerState
from rlaas.models import CircuitBreakerConfig


class TestRedisCircuitBreakerIntegration:
    """Test Redis operations with circuit breaker protection"""
    
    @pytest.fixture
    def circuit_breaker_config(self):
        """Create circuit breaker configuration for testing"""
        return CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,  # Short timeout for tests
            success_threshold=1,
            timeout_ms=100
        )
    
    @pytest.fixture
    def redis_config_with_circuit_breaker(self, circuit_breaker_config):
        """Create Redis config with circuit breaker enabled"""
        return RedisConfig(
            host="localhost",
            port=6379,
            enable_circuit_breaker=True,
            circuit_breaker_config=circuit_breaker_config,
            failure_mode=FailureMode.FAIL_OPEN
        )
    
    @pytest.fixture
    def redis_config_without_circuit_breaker(self):
        """Create Redis config with circuit breaker disabled"""
        return RedisConfig(
            host="localhost",
            port=6379,
            enable_circuit_breaker=False
        )
    
    @pytest.fixture
    def redis_manager_with_cb(self, redis_config_with_circuit_breaker):
        """Create Redis manager with circuit breaker"""
        return RedisClientManager(redis_config_with_circuit_breaker)
    
    @pytest.fixture
    def redis_manager_without_cb(self, redis_config_without_circuit_breaker):
        """Create Redis manager without circuit breaker"""
        return RedisClientManager(redis_config_without_circuit_breaker)
    
    def test_circuit_breaker_initialization(self, redis_manager_with_cb):
        """Test circuit breaker is initialized when enabled"""
        assert redis_manager_with_cb.circuit_breaker is not None
        assert redis_manager_with_cb.circuit_breaker.name == "redis_client"
        assert redis_manager_with_cb.circuit_breaker.is_closed
    
    def test_no_circuit_breaker_when_disabled(self, redis_manager_without_cb):
        """Test circuit breaker is not initialized when disabled"""
        assert redis_manager_without_cb.circuit_breaker is None
    
    @pytest.mark.asyncio
    async def test_successful_operation_with_circuit_breaker(self, redis_manager_with_cb):
        """Test successful Redis operation with circuit breaker"""
        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_manager_with_cb._client = mock_client
        
        async def test_operation():
            return await mock_client.ping()
        
        result = await redis_manager_with_cb.execute_redis_operation(test_operation)
        assert result is True
        
        # Verify circuit breaker stats
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["total_requests"] == 1
        assert stats["total_successes"] == 1
        assert stats["total_failures"] == 0
        assert stats["state"] == "closed"
    
    @pytest.mark.asyncio
    async def test_failed_operation_with_circuit_breaker(self, redis_manager_with_cb):
        """Test failed Redis operation with circuit breaker"""
        # Mock Redis client to fail
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=redis.RedisError("Connection failed"))
        redis_manager_with_cb._client = mock_client
        
        async def test_operation():
            return await mock_client.ping()
        
        # First failure
        with pytest.raises(redis.RedisError):
            await redis_manager_with_cb.execute_redis_operation(test_operation)
        
        # Second failure should trigger circuit breaker open
        with pytest.raises(redis.RedisError):
            await redis_manager_with_cb.execute_redis_operation(test_operation)
        
        # Verify circuit breaker is now open
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["state"] == "open"
        assert stats["total_failures"] == 2
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_requests_when_open(self, redis_manager_with_cb):
        """Test circuit breaker blocks requests when open"""
        # Force circuit breaker to open state
        await redis_manager_with_cb.force_circuit_breaker_open()
        
        async def test_operation():
            return "should not execute"
        
        # Should raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError, match="Circuit breaker 'redis_client' is open"):
            await redis_manager_with_cb.execute_redis_operation(test_operation)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, redis_manager_with_cb):
        """Test circuit breaker recovery after timeout"""
        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_manager_with_cb._client = mock_client
        
        # Force circuit breaker to open state
        await redis_manager_with_cb.force_circuit_breaker_open()
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)  # Longer than recovery_timeout (0.1s)
        
        async def test_operation():
            return await mock_client.ping()
        
        # Should succeed and transition to closed
        result = await redis_manager_with_cb.execute_redis_operation(test_operation)
        assert result is True
        
        # Should be closed now (success_threshold = 1)
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["state"] == "closed"
    
    @pytest.mark.asyncio
    async def test_health_check_with_circuit_breaker(self, redis_manager_with_cb):
        """Test health check with circuit breaker protection"""
        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_manager_with_cb._client = mock_client
        
        # Health check should succeed
        result = await redis_manager_with_cb.health_check()
        assert result is True
        
        # Force circuit breaker open
        await redis_manager_with_cb.force_circuit_breaker_open()
        
        # Health check should fail due to circuit breaker
        result = await redis_manager_with_cb.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_operation_without_circuit_breaker(self, redis_manager_without_cb):
        """Test Redis operation without circuit breaker"""
        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_manager_without_cb._client = mock_client
        
        async def test_operation():
            return await mock_client.ping()
        
        result = await redis_manager_without_cb.execute_redis_operation(test_operation)
        assert result is True
        
        # No circuit breaker stats
        assert redis_manager_without_cb.get_circuit_breaker_stats() is None
    
    def test_failure_mode_configuration(self):
        """Test different failure mode configurations"""
        # Fail-open configuration
        config_open = RedisConfig(failure_mode=FailureMode.FAIL_OPEN)
        assert config_open.failure_mode == FailureMode.FAIL_OPEN
        
        # Fail-closed configuration
        config_closed = RedisConfig(failure_mode=FailureMode.FAIL_CLOSED)
        assert config_closed.failure_mode == FailureMode.FAIL_CLOSED
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_reset(self, redis_manager_with_cb):
        """Test circuit breaker reset functionality"""
        # Force some failures to change state
        await redis_manager_with_cb.force_circuit_breaker_open()
        
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["state"] == "open"
        
        # Reset circuit breaker
        await redis_manager_with_cb.reset_circuit_breaker()
        
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["state"] == "closed"
        assert stats["total_requests"] == 0
        assert stats["total_failures"] == 0
        assert stats["total_successes"] == 0
    
    @pytest.mark.asyncio
    async def test_force_circuit_breaker_states(self, redis_manager_with_cb):
        """Test forcing circuit breaker states"""
        # Initially closed
        assert redis_manager_with_cb.circuit_breaker.is_closed
        
        # Force open
        await redis_manager_with_cb.force_circuit_breaker_open()
        assert redis_manager_with_cb.circuit_breaker.is_open
        
        # Force closed
        await redis_manager_with_cb.force_circuit_breaker_closed()
        assert redis_manager_with_cb.circuit_breaker.is_closed
    
    def test_circuit_breaker_stats_format(self, redis_manager_with_cb):
        """Test circuit breaker statistics format"""
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        
        required_fields = [
            "state", "failure_count", "success_count", "total_requests",
            "total_failures", "total_successes", "failure_rate", 
            "success_rate", "state_changes"
        ]
        
        for field in required_fields:
            assert field in stats
        
        assert isinstance(stats["state"], str)
        assert isinstance(stats["failure_rate"], float)
        assert isinstance(stats["success_rate"], float)
    
    @pytest.mark.asyncio
    async def test_concurrent_operations_with_circuit_breaker(self, redis_manager_with_cb):
        """Test concurrent operations with circuit breaker"""
        # Mock Redis client
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        redis_manager_with_cb._client = mock_client
        
        async def test_operation():
            await asyncio.sleep(0.01)  # Small delay
            return await mock_client.ping()
        
        # Run multiple concurrent operations
        tasks = [
            redis_manager_with_cb.execute_redis_operation(test_operation)
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        assert all(result is True for result in results)
        
        # Verify stats
        stats = redis_manager_with_cb.get_circuit_breaker_stats()
        assert stats["total_requests"] == 5
        assert stats["total_successes"] == 5
        assert stats["total_failures"] == 0


class TestRedisStateManagerCircuitBreaker:
    """Test RedisStateManager with circuit breaker integration"""
    
    @pytest.fixture
    def mock_redis_manager_with_cb(self):
        """Create mock Redis manager with circuit breaker"""
        manager = MagicMock()
        manager.execute_redis_operation = AsyncMock()
        manager.health_check = AsyncMock(return_value=True)
        return manager
    
    @pytest.fixture
    def redis_state_manager(self, mock_redis_manager_with_cb):
        """Create RedisStateManager with mocked Redis manager"""
        from rlaas.redis_state import RedisStateManager
        return RedisStateManager(mock_redis_manager_with_cb)
    
    @pytest.mark.asyncio
    async def test_get_bucket_state_with_circuit_breaker(self, redis_state_manager, mock_redis_manager_with_cb):
        """Test get_bucket_state uses circuit breaker protection"""
        # Mock successful Redis operation
        mock_redis_manager_with_cb.execute_redis_operation.return_value = None
        
        result = await redis_state_manager.get_bucket_state("client1", "/api/test", "GET")
        assert result is None
        
        # Verify circuit breaker was used
        mock_redis_manager_with_cb.execute_redis_operation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_set_bucket_state_with_circuit_breaker(self, redis_state_manager, mock_redis_manager_with_cb):
        """Test set_bucket_state uses circuit breaker protection"""
        from rlaas.models import RateLimitRule, TokenBucketState
        
        rule = RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=10,
            window_seconds=60,
            burst=15
        )
        
        state = TokenBucketState(
            tokens=10.0,
            last_refill=1234567890.0,
            rule=rule
        )
        
        # Mock successful Redis operation
        mock_redis_manager_with_cb.execute_redis_operation.return_value = None
        
        await redis_state_manager.set_bucket_state("client1", "/api/test", "GET", state)
        
        # Verify circuit breaker was used
        mock_redis_manager_with_cb.execute_redis_operation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_lua_script_with_circuit_breaker(self, redis_state_manager, mock_redis_manager_with_cb):
        """Test execute_lua_script uses circuit breaker protection"""
        # Mock successful Lua script execution
        mock_redis_manager_with_cb.execute_redis_operation.return_value = [1, 42]
        
        result = await redis_state_manager.execute_lua_script(
            "return {1, 42}",
            ["test_key"],
            ["test_arg"]
        )
        
        assert result == [1, 42]
        
        # Verify circuit breaker was used
        mock_redis_manager_with_cb.execute_redis_operation.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_health_check_with_circuit_breaker(self, redis_state_manager, mock_redis_manager_with_cb):
        """Test health_check uses circuit breaker protection"""
        # Mock successful health check
        mock_redis_manager_with_cb.health_check.return_value = True
        
        result = await redis_state_manager.health_check()
        assert result is True
        
        # Verify circuit breaker was used
        mock_redis_manager_with_cb.health_check.assert_called_once()