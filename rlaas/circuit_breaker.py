"""Circuit breaker implementation for fault tolerance"""

import time
import asyncio
from enum import Enum
from typing import Callable, Any, Optional, TypeVar, Awaitable
from dataclasses import dataclass, field
import structlog

from .models import CircuitBreakerConfig

logger = structlog.get_logger()

T = TypeVar('T')


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitBreakerStats:
    """Circuit breaker statistics and state tracking"""
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    state_changes: int = 0


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open"""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance
    
    Implements the circuit breaker pattern with three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failing state, requests are blocked
    - HALF_OPEN: Testing recovery, limited requests allowed
    """
    
    def __init__(self, config: CircuitBreakerConfig, name: str = "default"):
        """
        Initialize circuit breaker
        
        Args:
            config: Circuit breaker configuration
            name: Name for logging and identification
        """
        self.config = config
        self.name = name
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        
        logger.info(
            "Circuit breaker initialized",
            name=self.name,
            failure_threshold=config.failure_threshold,
            recovery_timeout=config.recovery_timeout,
            success_threshold=config.success_threshold,
            timeout_ms=config.timeout_ms
        )
    
    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state"""
        return self.stats.state
    
    @property
    def failure_count(self) -> int:
        """Get current failure count"""
        return self.stats.failure_count
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit breaker is closed (normal operation)"""
        return self.stats.state == CircuitBreakerState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit breaker is open (blocking requests)"""
        return self.stats.state == CircuitBreakerState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit breaker is half-open (testing recovery)"""
        return self.stats.state == CircuitBreakerState.HALF_OPEN
    
    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        """
        Execute function with circuit breaker protection
        
        Args:
            func: Async function to execute
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit breaker is open
            Exception: Any exception from the wrapped function
        """
        async with self._lock:
            # Check current state and handle transitions
            current_time = time.time()
            
            if self.stats.state == CircuitBreakerState.OPEN:
                # Check if recovery timeout has passed
                time_since_failure = current_time - self.stats.last_failure_time
                if time_since_failure >= self.config.recovery_timeout:
                    await self._transition_to_half_open()
                else:
                    # Still in open state, block the request
                    self.stats.total_requests += 1
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self.name}' is {self.stats.state.value}"
                    )
            elif self.stats.state == CircuitBreakerState.CLOSED:
                # Allow request in closed state
                pass
            elif self.stats.state == CircuitBreakerState.HALF_OPEN:
                # Allow request in half-open state for testing
                pass
            
            self.stats.total_requests += 1
        
        # Execute the function with timeout
        try:
            # Avoid zero timeout issues
            timeout_seconds = max(self.config.timeout_ms / 1000.0, 0.001)  # Minimum 1ms
            result = await asyncio.wait_for(
                func(),
                timeout=timeout_seconds
            )
            
            # Record success
            await self._record_success()
            return result
            
        except asyncio.TimeoutError as e:
            await self._record_failure()
            logger.warning(
                "Circuit breaker timeout",
                name=self.name,
                timeout_ms=self.config.timeout_ms
            )
            raise e
            
        except Exception as e:
            await self._record_failure()
            raise e
    
    async def _record_success(self) -> None:
        """Record successful operation and update state if needed"""
        async with self._lock:
            current_time = time.time()
            self.stats.success_count += 1
            self.stats.total_successes += 1
            self.stats.last_success_time = current_time
            
            # Reset failure count on success
            self.stats.failure_count = 0
            
            # Transition from half-open to closed if enough successes
            if (self.stats.state == CircuitBreakerState.HALF_OPEN and 
                self.stats.success_count >= self.config.success_threshold):
                await self._transition_to_closed()
            
            logger.debug(
                "Circuit breaker success recorded",
                name=self.name,
                state=self.stats.state.value,
                success_count=self.stats.success_count,
                total_successes=self.stats.total_successes
            )
    
    async def _record_failure(self) -> None:
        """Record failed operation and update state if needed"""
        async with self._lock:
            current_time = time.time()
            self.stats.failure_count += 1
            self.stats.total_failures += 1
            self.stats.last_failure_time = current_time
            
            # Reset success count on failure
            self.stats.success_count = 0
            
            # Transition to open based on state and failure count
            if self.stats.state == CircuitBreakerState.HALF_OPEN:
                # Any failure in half-open state should transition to open
                await self._transition_to_open()
            elif (self.stats.state == CircuitBreakerState.CLOSED and
                  self.stats.failure_count >= self.config.failure_threshold):
                # Transition to open if failure threshold exceeded in closed state
                await self._transition_to_open()
            
            logger.debug(
                "Circuit breaker failure recorded",
                name=self.name,
                state=self.stats.state.value,
                failure_count=self.stats.failure_count,
                total_failures=self.stats.total_failures
            )
    
    async def _transition_to_closed(self) -> None:
        """Transition circuit breaker to closed state"""
        if self.stats.state != CircuitBreakerState.CLOSED:
            old_state = self.stats.state
            self.stats.state = CircuitBreakerState.CLOSED
            self.stats.failure_count = 0
            self.stats.success_count = 0
            self.stats.state_changes += 1
            
            logger.info(
                "Circuit breaker transitioned to CLOSED",
                name=self.name,
                old_state=old_state.value,
                new_state=self.stats.state.value,
                total_successes=self.stats.total_successes,
                total_failures=self.stats.total_failures
            )
    
    async def _transition_to_open(self) -> None:
        """Transition circuit breaker to open state"""
        if self.stats.state != CircuitBreakerState.OPEN:
            old_state = self.stats.state
            self.stats.state = CircuitBreakerState.OPEN
            self.stats.success_count = 0
            self.stats.state_changes += 1
            
            logger.warning(
                "Circuit breaker transitioned to OPEN",
                name=self.name,
                old_state=old_state.value,
                new_state=self.stats.state.value,
                failure_count=self.stats.failure_count,
                failure_threshold=self.config.failure_threshold,
                total_failures=self.stats.total_failures
            )
    
    async def _transition_to_half_open(self) -> None:
        """Transition circuit breaker to half-open state"""
        if self.stats.state != CircuitBreakerState.HALF_OPEN:
            old_state = self.stats.state
            self.stats.state = CircuitBreakerState.HALF_OPEN
            self.stats.failure_count = 0
            self.stats.success_count = 0
            self.stats.state_changes += 1
            
            logger.info(
                "Circuit breaker transitioned to HALF_OPEN",
                name=self.name,
                old_state=old_state.value,
                new_state=self.stats.state.value,
                recovery_timeout=self.config.recovery_timeout
            )
    
    async def reset(self) -> None:
        """Reset circuit breaker to closed state and clear statistics"""
        async with self._lock:
            old_state = self.stats.state
            self.stats = CircuitBreakerStats()
            
            logger.info(
                "Circuit breaker reset",
                name=self.name,
                old_state=old_state.value,
                new_state=self.stats.state.value
            )
    
    async def force_open(self) -> None:
        """Force circuit breaker to open state"""
        async with self._lock:
            # Set last_failure_time to current time to prevent immediate recovery
            self.stats.last_failure_time = time.time()
            await self._transition_to_open()
            
            logger.warning(
                "Circuit breaker forced to OPEN",
                name=self.name
            )
    
    async def force_closed(self) -> None:
        """Force circuit breaker to closed state"""
        async with self._lock:
            await self._transition_to_closed()
            
            logger.info(
                "Circuit breaker forced to CLOSED",
                name=self.name
            )
    
    def get_stats(self) -> CircuitBreakerStats:
        """
        Get current circuit breaker statistics
        
        Returns:
            Copy of current statistics
        """
        return CircuitBreakerStats(
            state=self.stats.state,
            failure_count=self.stats.failure_count,
            success_count=self.stats.success_count,
            last_failure_time=self.stats.last_failure_time,
            last_success_time=self.stats.last_success_time,
            total_requests=self.stats.total_requests,
            total_failures=self.stats.total_failures,
            total_successes=self.stats.total_successes,
            state_changes=self.stats.state_changes
        )
    
    def get_failure_rate(self) -> float:
        """
        Calculate current failure rate
        
        Returns:
            Failure rate as percentage (0.0 to 100.0)
        """
        if self.stats.total_requests == 0:
            return 0.0
        
        return (self.stats.total_failures / self.stats.total_requests) * 100.0
    
    def get_success_rate(self) -> float:
        """
        Calculate current success rate
        
        Returns:
            Success rate as percentage (0.0 to 100.0)
        """
        if self.stats.total_requests == 0:
            return 0.0
        
        return (self.stats.total_successes / self.stats.total_requests) * 100.0
    
    def __str__(self) -> str:
        """String representation of circuit breaker"""
        return (
            f"CircuitBreaker(name='{self.name}', "
            f"state={self.stats.state.value}, "
            f"failures={self.stats.total_failures}, "
            f"successes={self.stats.total_successes}, "
            f"requests={self.stats.total_requests})"
        )
    
    def __repr__(self) -> str:
        """Detailed representation of circuit breaker"""
        return (
            f"CircuitBreaker("
            f"name='{self.name}', "
            f"config={self.config}, "
            f"stats={self.stats})"
        )