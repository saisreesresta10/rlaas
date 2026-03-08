"""Core data models for RLaaS"""

from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class RateLimitCheckRequest:
    """Request to check if a rate limit should allow or block a request"""
    client_id: str          # Unique identifier for the client
    endpoint: str           # API endpoint being accessed
    http_method: str        # HTTP method (GET, POST, etc.)
    
    def validate(self) -> None:
        """Validate request parameters"""
        if not self.client_id or not self.endpoint or not self.http_method:
            raise ValueError("All fields are required")
        if self.http_method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise ValueError("Invalid HTTP method")


@dataclass
class RateLimitResponse:
    """Response from rate limit check containing decision and metadata"""
    allowed: bool                    # Whether request is allowed
    remaining_tokens: Optional[int]  # Tokens remaining (if allowed)
    reset_after_ms: Optional[int]    # Time until bucket refills (if allowed)
    retry_after_ms: Optional[int]    # Time to wait before retry (if blocked)
    
    @classmethod
    def allowed_response(cls, remaining: int, reset_after: int) -> 'RateLimitResponse':
        """Create response for allowed request"""
        return cls(
            allowed=True, 
            remaining_tokens=remaining, 
            reset_after_ms=reset_after, 
            retry_after_ms=None
        )
    
    @classmethod
    def blocked_response(cls, retry_after: int) -> 'RateLimitResponse':
        """Create response for blocked request"""
        return cls(
            allowed=False, 
            remaining_tokens=None, 
            reset_after_ms=None, 
            retry_after_ms=retry_after
        )


@dataclass
class RateLimitRule:
    """Configuration for rate limiting rules"""
    client_id: str          # Client identifier (can be "*" for default)
    endpoint: str           # Endpoint pattern (can be "*" for default)
    http_method: str        # HTTP method (can be "*" for default)
    limit: int              # Requests per window
    window_seconds: int     # Time window in seconds
    burst: int              # Maximum burst capacity
    
    def validate(self) -> None:
        """Validate rule parameters"""
        if self.limit <= 0 or self.window_seconds <= 0 or self.burst <= 0:
            raise ValueError("All numeric values must be positive")
        if self.burst < self.limit:
            raise ValueError("Burst capacity must be >= limit")
    
    def get_refill_rate(self) -> float:
        """Calculate tokens per second refill rate"""
        return self.limit / self.window_seconds
    
    def get_bucket_key(self) -> str:
        """Generate Redis key for this rule"""
        return f"rate_limit:{self.client_id}:{self.endpoint}:{self.http_method}"


@dataclass
class TokenBucketState:
    """State of a token bucket including current tokens and metadata"""
    tokens: float           # Current token count
    last_refill: float      # Timestamp of last refill
    rule: RateLimitRule     # Associated rule configuration
    
    def refill_tokens(self, current_time: float) -> 'TokenBucketState':
        """Calculate new token count after refill"""
        time_elapsed = current_time - self.last_refill
        tokens_to_add = self.rule.get_refill_rate() * time_elapsed
        new_tokens = min(self.tokens + tokens_to_add, self.rule.burst)
        
        return TokenBucketState(
            tokens=new_tokens,
            last_refill=current_time,
            rule=self.rule
        )
    
    def can_consume(self, count: int = 1) -> bool:
        """Check if tokens can be consumed"""
        return self.tokens >= count
    
    def consume(self, count: int = 1) -> 'TokenBucketState':
        """Consume tokens and return new state"""
        if not self.can_consume(count):
            raise ValueError("Insufficient tokens")
        
        return TokenBucketState(
            tokens=self.tokens - count,
            last_refill=self.last_refill,
            rule=self.rule
        )


@dataclass
class TokenBucketResult:
    """Result of token bucket operation"""
    success: bool           # Whether operation succeeded
    remaining_tokens: int   # Tokens remaining after operation
    retry_after_ms: Optional[int]  # Time to wait before retry (if blocked)
    reset_after_ms: Optional[int]  # Time until bucket refills (if allowed)


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: int = 30          # Seconds before attempting recovery
    success_threshold: int = 3          # Successes needed to close
    timeout_ms: int = 100              # Operation timeout