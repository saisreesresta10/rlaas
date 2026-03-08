"""Redis client configuration and connection handling with circuit breaker protection"""

import redis.asyncio as redis
from typing import Optional, Any, Callable, TypeVar, Awaitable
from enum import Enum
import structlog

from .circuit_breaker import CircuitBreaker, CircuitBreakerError
from .models import CircuitBreakerConfig

logger = structlog.get_logger()

T = TypeVar('T')


class FailureMode(Enum):
    """Circuit breaker failure modes"""
    FAIL_OPEN = "fail_open"    # Allow requests when circuit breaker is open
    FAIL_CLOSED = "fail_closed"  # Block requests when circuit breaker is open


class RedisConfig:
    """Configuration for Redis connection"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 10,
        socket_timeout: float = 0.1,  # 100ms timeout for low latency
        socket_connect_timeout: float = 0.1,
        # Circuit breaker configuration
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        failure_mode: FailureMode = FailureMode.FAIL_OPEN,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.enable_circuit_breaker = enable_circuit_breaker
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=30,
            success_threshold=3,
            timeout_ms=200  # 200ms timeout for Redis operations
        )
        self.failure_mode = failure_mode


class RedisClientManager:
    """Manages Redis connection pool and basic operations with circuit breaker protection"""
    
    def __init__(self, config: RedisConfig):
        self.config = config
        self._pool: Optional[redis.ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._circuit_breaker: Optional[CircuitBreaker] = None
        
        # Initialize circuit breaker if enabled
        if config.enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                config.circuit_breaker_config,
                name="redis_client"
            )
    
    async def initialize(self) -> None:
        """Initialize Redis connection pool"""
        try:
            self._pool = redis.ConnectionPool(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                password=self.config.password,
                max_connections=self.config.max_connections,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.socket_connect_timeout,
                decode_responses=True,
            )
            
            self._client = redis.Redis(connection_pool=self._pool)
            
            # Test connection with circuit breaker protection
            await self._execute_with_circuit_breaker(self._client.ping)
            logger.info("Redis connection initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize Redis connection", error=str(e))
            raise
    
    async def close(self) -> None:
        """Close Redis connection pool"""
        if self._client:
            await self._client.aclose()
        if self._pool:
            await self._pool.disconnect()
        logger.info("Redis connection closed")
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client instance"""
        if not self._client:
            raise RuntimeError("Redis client not initialized")
        return self._client
    
    @property
    def circuit_breaker(self) -> Optional[CircuitBreaker]:
        """Get circuit breaker instance"""
        return self._circuit_breaker
    
    async def _execute_with_circuit_breaker(self, func: Callable[[], Awaitable[T]]) -> T:
        """
        Execute Redis operation with circuit breaker protection
        
        Args:
            func: Redis operation to execute
            
        Returns:
            Operation result
            
        Raises:
            Exception: Redis operation exception or circuit breaker failure
        """
        if not self._circuit_breaker:
            # No circuit breaker, execute directly
            return await func()
        
        try:
            return await self._circuit_breaker.call(func)
        except CircuitBreakerError as e:
            # Handle circuit breaker open state based on failure mode
            if self.config.failure_mode == FailureMode.FAIL_OPEN:
                logger.warning(
                    "Circuit breaker open, failing open (allowing operation)",
                    error=str(e),
                    failure_mode=self.config.failure_mode.value
                )
                # In fail-open mode, we could return a default value or skip the operation
                # For now, we'll re-raise to let the caller handle it
                raise
            else:  # FAIL_CLOSED
                logger.warning(
                    "Circuit breaker open, failing closed (blocking operation)",
                    error=str(e),
                    failure_mode=self.config.failure_mode.value
                )
                raise
    
    async def execute_redis_operation(self, func: Callable[[], Awaitable[T]]) -> T:
        """
        Public method to execute Redis operations with circuit breaker protection
        
        Args:
            func: Redis operation to execute
            
        Returns:
            Operation result
        """
        return await self._execute_with_circuit_breaker(func)
    
    async def health_check(self) -> bool:
        """Check Redis connectivity with circuit breaker protection"""
        try:
            if not self._client:
                return False
            
            await self._execute_with_circuit_breaker(self._client.ping)
            return True
        except CircuitBreakerError:
            # Circuit breaker is open, but Redis might still be healthy
            # Return False to indicate service degradation
            logger.warning("Health check failed due to circuit breaker")
            return False
        except Exception as e:
            logger.warning("Redis health check failed", error=str(e))
            return False
    
    def get_circuit_breaker_stats(self) -> Optional[dict]:
        """
        Get circuit breaker statistics
        
        Returns:
            Circuit breaker stats or None if not enabled
        """
        if not self._circuit_breaker:
            return None
        
        stats = self._circuit_breaker.get_stats()
        return {
            "state": stats.state.value,
            "failure_count": stats.failure_count,
            "success_count": stats.success_count,
            "total_requests": stats.total_requests,
            "total_failures": stats.total_failures,
            "total_successes": stats.total_successes,
            "failure_rate": self._circuit_breaker.get_failure_rate(),
            "success_rate": self._circuit_breaker.get_success_rate(),
            "state_changes": stats.state_changes,
        }
    
    async def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker to closed state"""
        if self._circuit_breaker:
            await self._circuit_breaker.reset()
            logger.info("Circuit breaker reset")
    
    async def force_circuit_breaker_open(self) -> None:
        """Force circuit breaker to open state"""
        if self._circuit_breaker:
            await self._circuit_breaker.force_open()
            logger.warning("Circuit breaker forced open")
    
    async def force_circuit_breaker_closed(self) -> None:
        """Force circuit breaker to closed state"""
        if self._circuit_breaker:
            await self._circuit_breaker.force_closed()
            logger.info("Circuit breaker forced closed")