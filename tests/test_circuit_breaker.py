"""Unit tests for CircuitBreaker implementation"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch

from rlaas.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerError,
    CircuitBreakerStats
)
from rlaas.models import CircuitBreakerConfig


class TestCircuitBreaker:
    """Test CircuitBreaker functionality"""
    
    @pytest.fixture
    def config(self):
        """Create test circuit breaker configuration"""
        return CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=1,  # 1 second for faster tests
            success_threshold=2,
            timeout_ms=100
        )
    
    @pytest.fixture
    def circuit_breaker(self, config):
        """Create circuit breaker instance"""
        return CircuitBreaker(config, name="test_breaker")
    
    def test_initial_state(self, circuit_breaker):
        """Test circuit breaker initial state"""
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.is_closed
        assert not circuit_breaker.is_open
        assert not circuit_breaker.is_half_open
        
        stats = circuit_breaker.get_stats()
        assert stats.failure_count == 0
        assert stats.success_count == 0
        assert stats.total_requests == 0
        assert stats.total_failures == 0
        assert stats.total_successes == 0
    
    @pytest.mark.asyncio
    async def test_successful_call(self, circuit_breaker):
        """Test successful function call"""
        async def success_func():
            return "success"
        
        result = await circuit_breaker.call(success_func)
        assert result == "success"
        
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 1
        assert stats.total_successes == 1
        assert stats.total_failures == 0
        assert stats.success_count == 1
        assert stats.failure_count == 0
        assert circuit_breaker.is_closed
    
    @pytest.mark.asyncio
    async def test_failed_call(self, circuit_breaker):
        """Test failed function call"""
        async def fail_func():
            raise ValueError("test error")
        
        with pytest.raises(ValueError, match="test error"):
            await circuit_breaker.call(fail_func)
        
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 1
        assert stats.total_successes == 0
        assert stats.total_failures == 1
        assert stats.success_count == 0
        assert stats.failure_count == 1
        assert circuit_breaker.is_closed  # Still closed, below threshold
    
    @pytest.mark.asyncio
    async def test_transition_to_open(self, circuit_breaker):
        """Test transition from closed to open state"""
        async def fail_func():
            raise ValueError("test error")
        
        # Fail enough times to trigger open state
        for i in range(3):  # failure_threshold = 3
            with pytest.raises(ValueError):
                await circuit_breaker.call(fail_func)
        
        assert circuit_breaker.is_open
        stats = circuit_breaker.get_stats()
        assert stats.total_failures == 3
        assert stats.state_changes == 1
    
    @pytest.mark.asyncio
    async def test_open_state_blocks_requests(self, circuit_breaker):
        """Test that open state blocks requests"""
        # Force circuit breaker to open state
        await circuit_breaker.force_open()
        
        async def success_func():
            return "success"
        
        with pytest.raises(CircuitBreakerError, match="Circuit breaker 'test_breaker' is open"):
            await circuit_breaker.call(success_func)
        
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 1
        assert stats.total_successes == 0
        assert stats.total_failures == 0  # Request was blocked, not failed
    
    @pytest.mark.asyncio
    async def test_recovery_timeout_transition_to_half_open(self, circuit_breaker):
        """Test transition from open to half-open after recovery timeout"""
        # Force to open state
        await circuit_breaker.force_open()
        assert circuit_breaker.is_open
        
        # Wait for recovery timeout (1 second in test config)
        await asyncio.sleep(1.1)
        
        async def success_func():
            return "success"
        
        # This should transition to half-open and allow the request
        result = await circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.is_half_open
    
    @pytest.mark.asyncio
    async def test_half_open_to_closed_transition(self, circuit_breaker):
        """Test transition from half-open to closed after enough successes"""
        # Force to half-open state
        circuit_breaker.stats.state = CircuitBreakerState.HALF_OPEN
        
        async def success_func():
            return "success"
        
        # Need 2 successes to close (success_threshold = 2)
        await circuit_breaker.call(success_func)
        assert circuit_breaker.is_half_open  # Still half-open after 1 success
        
        await circuit_breaker.call(success_func)
        assert circuit_breaker.is_closed  # Now closed after 2 successes
        
        stats = circuit_breaker.get_stats()
        assert stats.total_successes == 2
    
    @pytest.mark.asyncio
    async def test_half_open_to_open_on_failure(self, circuit_breaker):
        """Test transition from half-open back to open on failure"""
        # Set to half-open state
        circuit_breaker.stats.state = CircuitBreakerState.HALF_OPEN
        
        async def fail_func():
            raise ValueError("test error")
        
        # Single failure should transition back to open
        with pytest.raises(ValueError):
            await circuit_breaker.call(fail_func)
        
        assert circuit_breaker.is_open
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, circuit_breaker):
        """Test function timeout handling"""
        async def slow_func():
            await asyncio.sleep(0.2)  # Longer than 100ms timeout
            return "success"
        
        with pytest.raises(asyncio.TimeoutError):
            await circuit_breaker.call(slow_func)
        
        stats = circuit_breaker.get_stats()
        assert stats.total_failures == 1
        assert stats.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_reset_functionality(self, circuit_breaker):
        """Test circuit breaker reset"""
        # Generate some activity
        await circuit_breaker.force_open()
        
        async def success_func():
            return "success"
        
        # Try to call (will be blocked)
        with pytest.raises(CircuitBreakerError):
            await circuit_breaker.call(success_func)
        
        # Reset circuit breaker
        await circuit_breaker.reset()
        
        assert circuit_breaker.is_closed
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 0
        assert stats.total_failures == 0
        assert stats.total_successes == 0
        assert stats.state_changes == 0
    
    @pytest.mark.asyncio
    async def test_force_states(self, circuit_breaker):
        """Test forcing circuit breaker states"""
        # Force open
        await circuit_breaker.force_open()
        assert circuit_breaker.is_open
        
        # Force closed
        await circuit_breaker.force_closed()
        assert circuit_breaker.is_closed
    
    def test_failure_rate_calculation(self, circuit_breaker):
        """Test failure rate calculation"""
        # No requests yet
        assert circuit_breaker.get_failure_rate() == 0.0
        assert circuit_breaker.get_success_rate() == 0.0
        
        # Simulate some statistics
        circuit_breaker.stats.total_requests = 10
        circuit_breaker.stats.total_failures = 3
        circuit_breaker.stats.total_successes = 7
        
        assert circuit_breaker.get_failure_rate() == 30.0
        assert circuit_breaker.get_success_rate() == 70.0
    
    def test_string_representations(self, circuit_breaker):
        """Test string representations"""
        str_repr = str(circuit_breaker)
        assert "test_breaker" in str_repr
        assert "closed" in str_repr
        
        repr_str = repr(circuit_breaker)
        assert "CircuitBreaker" in repr_str
        assert "test_breaker" in repr_str
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self, circuit_breaker):
        """Test concurrent access to circuit breaker"""
        async def success_func():
            await asyncio.sleep(0.01)  # Small delay
            return "success"
        
        # Run multiple concurrent calls
        tasks = [circuit_breaker.call(success_func) for _ in range(5)]
        results = await asyncio.gather(*tasks)
        
        assert all(result == "success" for result in results)
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 5
        assert stats.total_successes == 5
    
    @pytest.mark.asyncio
    async def test_mixed_success_failure_pattern(self, circuit_breaker):
        """Test mixed success and failure patterns"""
        async def success_func():
            return "success"
        
        async def fail_func():
            raise ValueError("test error")
        
        # Pattern: success, fail, success, fail, fail, fail (should open)
        await circuit_breaker.call(success_func)
        assert circuit_breaker.is_closed
        
        with pytest.raises(ValueError):
            await circuit_breaker.call(fail_func)
        assert circuit_breaker.is_closed  # failure_count = 1
        
        await circuit_breaker.call(success_func)
        assert circuit_breaker.is_closed  # failure_count reset to 0
        
        # Now 3 consecutive failures should open it
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker.call(fail_func)
        
        assert circuit_breaker.is_open
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, circuit_breaker):
        """Test comprehensive statistics tracking"""
        async def success_func():
            return "success"
        
        async def fail_func():
            raise ValueError("test error")
        
        # Initial stats
        stats = circuit_breaker.get_stats()
        assert stats.state == CircuitBreakerState.CLOSED
        
        # Success
        await circuit_breaker.call(success_func)
        stats = circuit_breaker.get_stats()
        assert stats.last_success_time > 0
        assert stats.success_count == 1
        
        # Failure
        with pytest.raises(ValueError):
            await circuit_breaker.call(fail_func)
        stats = circuit_breaker.get_stats()
        assert stats.last_failure_time > 0
        assert stats.failure_count == 1
        assert stats.success_count == 0  # Reset on failure
    
    def test_config_validation(self):
        """Test circuit breaker with different configurations"""
        # Very sensitive configuration
        sensitive_config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            success_threshold=1,
            timeout_ms=50
        )
        
        breaker = CircuitBreaker(sensitive_config, name="sensitive")
        assert breaker.config.failure_threshold == 1
        assert breaker.config.recovery_timeout == 0.1
        
        # Very tolerant configuration
        tolerant_config = CircuitBreakerConfig(
            failure_threshold=100,
            recovery_timeout=300,
            success_threshold=10,
            timeout_ms=5000
        )
        
        breaker = CircuitBreaker(tolerant_config, name="tolerant")
        assert breaker.config.failure_threshold == 100
        assert breaker.config.recovery_timeout == 300


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error conditions"""
    
    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.5,
            success_threshold=1,
            timeout_ms=100
        )
    
    @pytest.fixture
    def circuit_breaker(self, config):
        """Create circuit breaker instance"""
        return CircuitBreaker(config, name="edge_test")
    
    @pytest.mark.asyncio
    async def test_zero_timeout(self, circuit_breaker):
        """Test with zero timeout configuration"""
        circuit_breaker.config.timeout_ms = 0
        
        async def instant_func():
            return "instant"
        
        # Should still work with zero timeout
        result = await circuit_breaker.call(instant_func)
        assert result == "instant"
    
    @pytest.mark.asyncio
    async def test_immediate_recovery(self, circuit_breaker):
        """Test immediate recovery with very short timeout"""
        circuit_breaker.config.recovery_timeout = 0.001  # 1ms
        
        # Force open
        await circuit_breaker.force_open()
        
        # Wait minimal time
        await asyncio.sleep(0.002)
        
        async def success_func():
            return "recovered"
        
        result = await circuit_breaker.call(success_func)
        assert result == "recovered"
        # With success_threshold=1, it should transition directly to closed
        assert circuit_breaker.is_closed
    
    @pytest.mark.asyncio
    async def test_exception_in_async_function(self, circuit_breaker):
        """Test various exception types"""
        async def runtime_error_func():
            raise RuntimeError("runtime error")
        
        async def type_error_func():
            raise TypeError("type error")
        
        async def custom_error_func():
            raise Exception("custom error")
        
        # All should be treated as failures
        with pytest.raises(RuntimeError):
            await circuit_breaker.call(runtime_error_func)
        
        with pytest.raises(TypeError):
            await circuit_breaker.call(type_error_func)
        
        # This should trigger open state (failure_threshold = 2)
        assert circuit_breaker.is_open
    
    @pytest.mark.asyncio
    async def test_state_consistency_under_load(self, circuit_breaker):
        """Test state consistency under concurrent load"""
        async def sometimes_fail():
            # Randomly fail to create race conditions
            import random
            if random.random() < 0.7:  # 70% failure rate
                raise ValueError("random failure")
            return "success"
        
        # Run many concurrent operations
        tasks = []
        for _ in range(20):
            task = asyncio.create_task(
                circuit_breaker.call(sometimes_fail)
            )
            tasks.append(task)
        
        # Gather results, ignoring exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify state is consistent
        stats = circuit_breaker.get_stats()
        assert stats.total_requests == 20
        assert stats.total_successes + stats.total_failures == 20
        
        # State should be deterministic based on failure pattern
        assert circuit_breaker.state in [
            CircuitBreakerState.CLOSED,
            CircuitBreakerState.OPEN,
            CircuitBreakerState.HALF_OPEN
        ]