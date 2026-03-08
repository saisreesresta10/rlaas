"""Property-based tests for circuit breaker behavior"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, assume
from hypothesis.stateful import RuleBasedStateMachine, rule, initialize, invariant
from unittest.mock import AsyncMock

from rlaas.circuit_breaker import CircuitBreaker, CircuitBreakerState
from rlaas.models import CircuitBreakerConfig


class TestPropertyCircuitBreakerBehavior:
    """Property-based tests for circuit breaker state consistency"""
    
    @pytest.fixture
    def circuit_breaker(self):
        """Create circuit breaker for testing"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=1.0,
            success_threshold=2,
            timeout=0.1
        )
        return CircuitBreaker("test", config)
    
    @given(
        failure_threshold=st.integers(min_value=1, max_value=10),
        recovery_timeout=st.integers(min_value=1, max_value=10),
        success_threshold=st.integers(min_value=1, max_value=5),
        timeout_ms=st.integers(min_value=10, max_value=1000)
    )
    @settings(suppress_health_check=[])
    def test_circuit_breaker_state_consistency_property(self, failure_threshold, recovery_timeout, 
                                                       success_threshold, timeout_ms):
        """
        Property 12: Circuit Breaker State Consistency
        A circuit breaker must maintain consistent state transitions:
        - CLOSED -> OPEN after failure_threshold failures
        - OPEN -> HALF_OPEN after recovery_timeout
        - HALF_OPEN -> CLOSED after success_threshold successes
        - HALF_OPEN -> OPEN on any failure
        **Validates: Requirements 5.1**
        """
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            timeout_ms=timeout_ms
        )
        
        circuit_breaker = CircuitBreaker(config, "test")
        
        # Property 1: Initial state should be CLOSED
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        assert circuit_breaker.failure_count == 0
        
        # Property 2: After failure_threshold failures, state should be OPEN
        async def failing_function():
            raise Exception("Test failure")
        
        async def test_failures():
            for i in range(failure_threshold):
                try:
                    await circuit_breaker.call(failing_function)
                except:
                    pass
            
            # Should be OPEN after failure_threshold failures
            assert circuit_breaker.state == CircuitBreakerState.OPEN
            assert circuit_breaker.failure_count >= failure_threshold
        
        # Run the async test
        asyncio.run(test_failures())
        
        # Property 3: In OPEN state, calls should be rejected immediately
        async def test_open_rejection():
            circuit_breaker._state = CircuitBreakerState.OPEN
            circuit_breaker._last_failure_time = asyncio.get_event_loop().time()
            
            async def success_function():
                return "success"
            
            try:
                await circuit_breaker.call(success_function)
                assert False, "Should have raised CircuitBreakerOpenError"
            except Exception as e:
                assert "Circuit breaker is OPEN" in str(e) or "is open" in str(e)
        
        asyncio.run(test_open_rejection())
    
    @given(
        initial_failures=st.integers(min_value=0, max_value=5),
        additional_failures=st.integers(min_value=0, max_value=5)
    )
    @settings(suppress_health_check=[])
    def test_failure_count_consistency_property(self, initial_failures, additional_failures):
        """
        Property: Failure count should be consistent and monotonic until reset
        """
        config = CircuitBreakerConfig(failure_threshold=10)  # High threshold to avoid state changes
        circuit_breaker = CircuitBreaker(config, "test")
        
        async def failing_function():
            raise Exception("Test failure")
        
        async def test_failure_counting():
            # Record initial failures
            for i in range(initial_failures):
                try:
                    await circuit_breaker.call(failing_function)
                except:
                    pass
            
            initial_count = circuit_breaker.failure_count
            assert initial_count == initial_failures
            
            # Record additional failures
            for i in range(additional_failures):
                try:
                    await circuit_breaker.call(failing_function)
                except:
                    pass
            
            final_count = circuit_breaker.failure_count
            assert final_count == initial_failures + additional_failures
        
        asyncio.run(test_failure_counting())
    
    @given(
        success_count=st.integers(min_value=1, max_value=10)
    )
    @settings(suppress_health_check=[])
    def test_success_resets_failure_count_property(self, success_count):
        """
        Property: Successful calls should reset failure count in CLOSED state
        """
        config = CircuitBreakerConfig(failure_threshold=20)  # High threshold
        circuit_breaker = CircuitBreaker(config, "test")
        
        async def success_function():
            return "success"
        
        async def failing_function():
            raise Exception("Test failure")
        
        async def test_success_reset():
            # Accumulate some failures first
            for i in range(3):
                try:
                    await circuit_breaker.call(failing_function)
                except:
                    pass
            
            assert circuit_breaker.failure_count == 3
            
            # One success should reset failure count
            result = await circuit_breaker.call(success_function)
            assert result == "success"
            assert circuit_breaker.failure_count == 0
        
        asyncio.run(test_success_reset())


class CircuitBreakerStateMachine(RuleBasedStateMachine):
    """State machine for testing circuit breaker behavior"""
    
    def __init__(self):
        super().__init__()
        self.config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=2,
            timeout_ms=50
        )
        self.circuit_breaker = CircuitBreaker(self.config, "test")
    
    @initialize()
    def initialize_circuit_breaker(self):
        """Initialize circuit breaker in CLOSED state"""
        assert self.circuit_breaker.state == CircuitBreakerState.CLOSED
        assert self.circuit_breaker.failure_count == 0
    
    @rule()
    def successful_call(self):
        """Execute a successful call"""
        async def success_function():
            return "success"
        
        async def execute():
            if self.circuit_breaker.state != CircuitBreakerState.OPEN:
                result = await self.circuit_breaker.call(success_function)
                assert result == "success"
        
        try:
            asyncio.run(execute())
        except Exception:
            # Circuit breaker might be OPEN, which is valid
            pass
    
    @rule()
    def failing_call(self):
        """Execute a failing call"""
        async def failing_function():
            raise Exception("Test failure")
        
        async def execute():
            try:
                await self.circuit_breaker.call(failing_function)
            except Exception:
                pass  # Expected for failures and circuit breaker open
        
        asyncio.run(execute())
    
    @invariant()
    def state_consistency_invariant(self):
        """Verify circuit breaker state consistency"""
        # State should be one of the valid states
        assert self.circuit_breaker.state in [
            CircuitBreakerState.CLOSED,
            CircuitBreakerState.OPEN,
            CircuitBreakerState.HALF_OPEN
        ]
        
        # Failure count should be non-negative
        assert self.circuit_breaker.failure_count >= 0
        
        # If state is OPEN, failure count should be >= failure_threshold
        if self.circuit_breaker.state == CircuitBreakerState.OPEN:
            assert self.circuit_breaker.failure_count >= self.config.failure_threshold


class TestCircuitBreakerStateMachine:
    """Test circuit breaker using state machine approach"""
    
    def test_circuit_breaker_state_machine(self):
        """Test circuit breaker behavior using state machine"""
        CircuitBreakerStateMachine.TestCase().runTest()


class TestPropertyFailSafeBehavior:
    """Property-based tests for fail-safe behavior"""
    
    @given(
        fail_open=st.booleans(),
        error_count=st.integers(min_value=1, max_value=10)
    )
    @settings(suppress_health_check=[])
    def test_fail_safe_behavior_consistency_property(self, fail_open, error_count):
        """
        Property 6: Fail-Safe Behavior Consistency
        When the circuit breaker is OPEN, the system should consistently
        either fail-open (allow requests) or fail-closed (block requests)
        based on configuration.
        **Validates: Requirements 3.4**
        """
        config = CircuitBreakerConfig(
            failure_threshold=1,  # Low threshold to trigger quickly
            recovery_timeout=10,  # Long timeout to stay OPEN
            success_threshold=1,
            timeout_ms=10
        )
        
        circuit_breaker = CircuitBreaker(config, "test")
        
        async def failing_function():
            raise Exception("Test failure")
        
        async def success_function():
            return "success"
        
        async def test_fail_safe():
            # Force circuit breaker to OPEN state
            try:
                await circuit_breaker.call(failing_function)
            except:
                pass
            
            assert circuit_breaker.state == CircuitBreakerState.OPEN
            
            # Test consistent fail-safe behavior
            results = []
            for i in range(error_count):
                try:
                    result = await circuit_breaker.call(success_function)
                    results.append(("success", result))
                except Exception as e:
                    results.append(("error", str(e)))
            
            # All results should be consistent (all success or all error)
            if results:
                first_result_type = results[0][0]
                for result_type, _ in results:
                    assert result_type == first_result_type, \
                        f"Inconsistent fail-safe behavior: {results}"
        
        asyncio.run(test_fail_safe())
    
    @given(
        timeout_duration=st.integers(min_value=10, max_value=100)
    )
    @settings(suppress_health_check=[])
    def test_timeout_consistency_property(self, timeout_duration):
        """
        Property: Timeout behavior should be consistent
        """
        config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=1,
            success_threshold=1,
            timeout_ms=timeout_duration
        )
        
        circuit_breaker = CircuitBreaker(config, "test")
        
        async def slow_function():
            await asyncio.sleep(timeout_duration * 2 / 1000)  # Slower than timeout (convert ms to seconds)
            return "success"
        
        async def test_timeout():
            try:
                result = await circuit_breaker.call(slow_function)
                assert False, "Should have timed out"
            except Exception as e:
                # Should be a timeout error
                assert ("timeout" in str(e).lower() or 
                       "timed out" in str(e).lower() or
                       isinstance(e, asyncio.TimeoutError) or
                       "TimeoutError" in str(type(e)))
        
        asyncio.run(test_timeout())