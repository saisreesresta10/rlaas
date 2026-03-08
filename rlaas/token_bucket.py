"""Token bucket service implementation for rate limiting"""

import time
from typing import Optional
import structlog

from .models import (
    RateLimitRule,
    TokenBucketState,
    TokenBucketResult,
)

logger = structlog.get_logger()


class TokenBucketService:
    """Service for managing token bucket rate limiting logic"""
    
    def __init__(self):
        """Initialize the token bucket service"""
        pass
    
    def create_initial_bucket_state(self, rule: RateLimitRule, current_time: Optional[float] = None) -> TokenBucketState:
        """
        Create initial token bucket state for a new bucket
        
        Args:
            rule: Rate limiting rule configuration
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            TokenBucketState with full burst capacity
        """
        if current_time is None:
            current_time = time.time()
            
        return TokenBucketState(
            tokens=float(rule.burst),  # Start with full burst capacity
            last_refill=current_time,
            rule=rule
        )
    
    def refill_tokens(self, state: TokenBucketState, current_time: Optional[float] = None) -> TokenBucketState:
        """
        Calculate new token count after refill based on elapsed time
        
        Args:
            state: Current token bucket state
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            TokenBucketState with updated token count and refill time
        """
        if current_time is None:
            current_time = time.time()
            
        # Calculate time elapsed since last refill
        time_elapsed = max(0, current_time - state.last_refill)
        
        # Calculate tokens to add based on refill rate
        tokens_to_add = state.rule.get_refill_rate() * time_elapsed
        
        # Add tokens but cap at burst capacity
        new_tokens = min(state.tokens + tokens_to_add, float(state.rule.burst))
        
        return TokenBucketState(
            tokens=new_tokens,
            last_refill=current_time,
            rule=state.rule
        )
    
    def can_consume_tokens(self, state: TokenBucketState, tokens_requested: int = 1) -> bool:
        """
        Check if the requested number of tokens can be consumed
        
        Args:
            state: Current token bucket state
            tokens_requested: Number of tokens to check for
            
        Returns:
            True if tokens can be consumed, False otherwise
        """
        return state.tokens >= tokens_requested
    
    def consume_tokens(self, state: TokenBucketState, tokens_to_consume: int = 1) -> TokenBucketState:
        """
        Consume tokens from the bucket
        
        Args:
            state: Current token bucket state
            tokens_to_consume: Number of tokens to consume
            
        Returns:
            TokenBucketState with reduced token count
            
        Raises:
            ValueError: If insufficient tokens available
        """
        if not self.can_consume_tokens(state, tokens_to_consume):
            raise ValueError(f"Insufficient tokens: requested {tokens_to_consume}, available {state.tokens}")
        
        return TokenBucketState(
            tokens=state.tokens - tokens_to_consume,
            last_refill=state.last_refill,
            rule=state.rule
        )
    
    def process_token_request(
        self, 
        state: TokenBucketState, 
        tokens_requested: int = 1,
        current_time: Optional[float] = None
    ) -> tuple[TokenBucketResult, TokenBucketState]:
        """
        Process a token consumption request with refill and consumption logic
        
        Args:
            state: Current token bucket state
            tokens_requested: Number of tokens to consume
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Tuple of (TokenBucketResult, updated TokenBucketState)
        """
        if current_time is None:
            current_time = time.time()
        
        # First, refill tokens based on elapsed time
        refilled_state = self.refill_tokens(state, current_time)
        
        # Check if we can consume the requested tokens
        if self.can_consume_tokens(refilled_state, tokens_requested):
            # Consume tokens
            final_state = self.consume_tokens(refilled_state, tokens_requested)
            
            # Calculate reset time (when bucket will be full again)
            tokens_until_full = final_state.rule.burst - final_state.tokens
            seconds_until_full = tokens_until_full / final_state.rule.get_refill_rate()
            reset_after_ms = int(seconds_until_full * 1000)
            
            result = TokenBucketResult(
                success=True,
                remaining_tokens=int(final_state.tokens),
                retry_after_ms=None,
                reset_after_ms=reset_after_ms
            )
            
            logger.debug(
                "Token consumption successful",
                client_id=final_state.rule.client_id,
                endpoint=final_state.rule.endpoint,
                remaining_tokens=int(final_state.tokens),
                reset_after_ms=reset_after_ms
            )
            
            return result, final_state
        else:
            # Cannot consume tokens - calculate retry time
            tokens_needed = tokens_requested - refilled_state.tokens
            seconds_until_available = tokens_needed / refilled_state.rule.get_refill_rate()
            retry_after_ms = int(seconds_until_available * 1000)
            
            result = TokenBucketResult(
                success=False,
                remaining_tokens=int(refilled_state.tokens),
                retry_after_ms=retry_after_ms,
                reset_after_ms=None
            )
            
            logger.debug(
                "Token consumption blocked",
                client_id=refilled_state.rule.client_id,
                endpoint=refilled_state.rule.endpoint,
                tokens_available=int(refilled_state.tokens),
                tokens_requested=tokens_requested,
                retry_after_ms=retry_after_ms
            )
            
            return result, refilled_state
    
    def calculate_time_until_tokens_available(self, state: TokenBucketState, tokens_needed: int) -> float:
        """
        Calculate time in seconds until the specified number of tokens will be available
        
        Args:
            state: Current token bucket state
            tokens_needed: Number of tokens needed
            
        Returns:
            Time in seconds until tokens are available (0 if already available)
        """
        if state.tokens >= tokens_needed:
            return 0.0
        
        tokens_to_wait_for = tokens_needed - state.tokens
        return tokens_to_wait_for / state.rule.get_refill_rate()
    
    def calculate_time_until_full(self, state: TokenBucketState) -> float:
        """
        Calculate time in seconds until the bucket is full
        
        Args:
            state: Current token bucket state
            
        Returns:
            Time in seconds until bucket is full (0 if already full)
        """
        if state.tokens >= state.rule.burst:
            return 0.0
        
        tokens_until_full = state.rule.burst - state.tokens
        return tokens_until_full / state.rule.get_refill_rate()
    
    def get_bucket_info(self, state: TokenBucketState, current_time: Optional[float] = None) -> dict:
        """
        Get comprehensive information about the current bucket state
        
        Args:
            state: Current token bucket state
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Dictionary with bucket information
        """
        if current_time is None:
            current_time = time.time()
        
        # Get current state after refill
        current_state = self.refill_tokens(state, current_time)
        
        return {
            "current_tokens": current_state.tokens,
            "max_tokens": current_state.rule.burst,
            "refill_rate": current_state.rule.get_refill_rate(),
            "last_refill": current_state.last_refill,
            "time_until_full": self.calculate_time_until_full(current_state),
            "rule": {
                "client_id": current_state.rule.client_id,
                "endpoint": current_state.rule.endpoint,
                "http_method": current_state.rule.http_method,
                "limit": current_state.rule.limit,
                "window_seconds": current_state.rule.window_seconds,
                "burst": current_state.rule.burst,
            }
        }