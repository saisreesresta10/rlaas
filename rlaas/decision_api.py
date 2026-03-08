"""Rate limit decision API that integrates all components"""

import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
import structlog

from .models import RateLimitCheckRequest, RateLimitResponse, RateLimitRule, TokenBucketResult
from .rule_management import RuleManagementService, RuleValidationError
from .redis_state import RedisStateManager
from .token_bucket import TokenBucketService
from .circuit_breaker import CircuitBreakerError

logger = structlog.get_logger()


@dataclass
class RateLimitDecisionResult:
    """Result of rate limit decision with detailed information"""
    allowed: bool
    remaining_tokens: Optional[int] = None
    retry_after_ms: Optional[int] = None
    reset_after_ms: Optional[int] = None
    rule_applied: Optional[RateLimitRule] = None
    used_default_rule: bool = False
    error_message: Optional[str] = None


class RateLimitDecisionError(Exception):
    """Exception raised when rate limit decision fails"""
    pass


class RateLimitDecisionAPI:
    """
    Core rate limiting decision service that integrates all components
    
    This service orchestrates:
    - Rule retrieval and management
    - Token bucket operations
    - Redis state management
    - Circuit breaker fault tolerance
    - Response formatting
    """
    
    def __init__(
        self,
        rule_management_service: RuleManagementService,
        redis_state_manager: RedisStateManager,
        token_bucket_service: TokenBucketService
    ):
        """
        Initialize rate limit decision API
        
        Args:
            rule_management_service: Service for managing rate limiting rules
            redis_state_manager: Redis state manager for distributed state
            token_bucket_service: Token bucket service for rate limiting logic
        """
        self.rule_management_service = rule_management_service
        self.redis_state_manager = redis_state_manager
        self.token_bucket_service = token_bucket_service
        
        logger.info("Rate limit decision API initialized")
    
    def validate_request(self, request: RateLimitCheckRequest) -> None:
        """
        Validate rate limit check request
        
        Args:
            request: Rate limit check request to validate
            
        Raises:
            RateLimitDecisionError: If request is invalid
        """
        errors = []
        
        # Validate client_id
        if not request.client_id or not request.client_id.strip():
            errors.append("client_id cannot be empty")
        
        # Validate endpoint
        if not request.endpoint or not request.endpoint.strip():
            errors.append("endpoint cannot be empty")
        
        # Validate http_method
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if request.http_method not in valid_methods:
            errors.append(f"http_method must be one of {valid_methods}")
        
        if errors:
            error_msg = "; ".join(errors)
            logger.warning(
                "Request validation failed",
                client_id=request.client_id,
                endpoint=request.endpoint,
                http_method=request.http_method,
                errors=errors
            )
            raise RateLimitDecisionError(f"Request validation failed: {error_msg}")
    
    async def check_rate_limit(
        self,
        request: RateLimitCheckRequest,
        tokens_to_consume: int = 1,
        current_time: Optional[float] = None
    ) -> RateLimitDecisionResult:
        """
        Check if request should be allowed based on rate limiting rules
        
        Args:
            request: Rate limit check request
            tokens_to_consume: Number of tokens to consume (default: 1)
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Rate limit decision result
            
        Raises:
            RateLimitDecisionError: If decision cannot be made due to validation errors
        """
        if current_time is None:
            current_time = time.time()
        
        # Validate request
        self.validate_request(request)
        
        try:
            # Get applicable rule (with fallback to default)
            rule = await self.rule_management_service.get_rule(
                request.client_id,
                request.endpoint,
                request.http_method,
                use_default_fallback=True
            )
            
            # Determine if default rule was used
            try:
                configured_rule = await self.rule_management_service.get_rule(
                    request.client_id,
                    request.endpoint,
                    request.http_method,
                    use_default_fallback=False
                )
                used_default_rule = configured_rule is None
            except:
                used_default_rule = True
            
            logger.debug(
                "Retrieved rule for rate limit check",
                client_id=request.client_id,
                endpoint=request.endpoint,
                http_method=request.http_method,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                burst=rule.burst,
                used_default_rule=used_default_rule
            )
            
            # Perform atomic token bucket operation
            try:
                result = await self.redis_state_manager.atomic_refill_and_consume(
                    client_id=request.client_id,
                    endpoint=request.endpoint,
                    http_method=request.http_method,
                    rule=rule,
                    tokens_to_consume=tokens_to_consume,
                    current_time=current_time
                )
                
                if result.success:
                    # Request allowed
                    decision_result = RateLimitDecisionResult(
                        allowed=True,
                        remaining_tokens=result.remaining_tokens,
                        reset_after_ms=result.reset_after_ms,
                        rule_applied=rule,
                        used_default_rule=used_default_rule
                    )
                    
                    logger.info(
                        "Rate limit check: ALLOWED",
                        client_id=request.client_id,
                        endpoint=request.endpoint,
                        http_method=request.http_method,
                        remaining_tokens=result.remaining_tokens,
                        reset_after_ms=result.reset_after_ms,
                        used_default_rule=used_default_rule
                    )
                else:
                    # Request blocked
                    decision_result = RateLimitDecisionResult(
                        allowed=False,
                        retry_after_ms=result.retry_after_ms,
                        rule_applied=rule,
                        used_default_rule=used_default_rule
                    )
                    
                    logger.info(
                        "Rate limit check: BLOCKED",
                        client_id=request.client_id,
                        endpoint=request.endpoint,
                        http_method=request.http_method,
                        retry_after_ms=result.retry_after_ms,
                        used_default_rule=used_default_rule
                    )
                
                return decision_result
                
            except CircuitBreakerError as e:
                # Circuit breaker is open - handle based on configuration
                logger.warning(
                    "Rate limit check failed due to circuit breaker",
                    error=str(e),
                    client_id=request.client_id,
                    endpoint=request.endpoint,
                    http_method=request.http_method
                )
                
                # For now, fail open (allow request) when circuit breaker is open
                # This could be configurable based on business requirements
                return RateLimitDecisionResult(
                    allowed=True,
                    remaining_tokens=None,
                    rule_applied=rule,
                    used_default_rule=used_default_rule,
                    error_message="Circuit breaker open - failing open"
                )
            
        except Exception as e:
            logger.error(
                "Rate limit check failed",
                error=str(e),
                client_id=request.client_id,
                endpoint=request.endpoint,
                http_method=request.http_method
            )
            
            # For critical errors, fail closed (block request) for safety
            return RateLimitDecisionResult(
                allowed=False,
                error_message=f"Rate limit check failed: {str(e)}"
            )
    
    def format_response(self, decision_result: RateLimitDecisionResult) -> RateLimitResponse:
        """
        Format decision result into API response
        
        Args:
            decision_result: Rate limit decision result
            
        Returns:
            Formatted API response
        """
        if decision_result.allowed:
            # Allowed response
            response = RateLimitResponse(
                allowed=True,
                remaining_tokens=decision_result.remaining_tokens,
                reset_after_ms=decision_result.reset_after_ms,
                retry_after_ms=None
            )
        else:
            # Blocked response
            response = RateLimitResponse(
                allowed=False,
                remaining_tokens=None,
                reset_after_ms=None,
                retry_after_ms=decision_result.retry_after_ms
            )
        
        return response
    
    async def process_rate_limit_request(
        self,
        request: RateLimitCheckRequest,
        tokens_to_consume: int = 1
    ) -> RateLimitResponse:
        """
        Complete rate limit processing: check + format response
        
        Args:
            request: Rate limit check request
            tokens_to_consume: Number of tokens to consume
            
        Returns:
            Formatted rate limit response
            
        Raises:
            RateLimitDecisionError: If request validation fails
        """
        # Perform rate limit check
        decision_result = await self.check_rate_limit(request, tokens_to_consume)
        
        # Format and return response
        return self.format_response(decision_result)
    
    async def get_bucket_info(
        self,
        client_id: str,
        endpoint: str,
        http_method: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a rate limiting bucket
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            Bucket information or None if not found
        """
        try:
            # Get rule information
            rule = await self.rule_management_service.get_rule(
                client_id, endpoint, http_method, use_default_fallback=True
            )
            
            # Get current bucket state
            current_tokens = await self.redis_state_manager.atomic_get_and_refill(
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                rule=rule
            )
            
            # Calculate additional metrics
            refill_rate = rule.get_refill_rate()
            time_until_full = (rule.burst - current_tokens) / refill_rate if current_tokens < rule.burst else 0
            
            bucket_info = {
                "client_id": client_id,
                "endpoint": endpoint,
                "http_method": http_method,
                "rule": {
                    "limit": rule.limit,
                    "window_seconds": rule.window_seconds,
                    "burst": rule.burst,
                    "refill_rate": refill_rate
                },
                "current_state": {
                    "tokens": current_tokens,
                    "capacity_used_percent": ((rule.burst - current_tokens) / rule.burst) * 100,
                    "time_until_full_seconds": time_until_full
                },
                "timestamp": time.time()
            }
            
            return bucket_info
            
        except Exception as e:
            logger.error(
                "Failed to get bucket info",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            return None
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive health check of all components
        
        Returns:
            Health check results
        """
        try:
            # Check rule management service
            rule_health = await self.rule_management_service.health_check()
            
            # Check Redis state manager
            redis_healthy = await self.redis_state_manager.health_check()
            
            # Overall health status
            overall_healthy = (
                rule_health.get("status") in ["healthy", "degraded"] and
                redis_healthy
            )
            
            health_info = {
                "service": "rate_limit_decision_api",
                "status": "healthy" if overall_healthy else "unhealthy",
                "components": {
                    "rule_management": rule_health,
                    "redis_state": {
                        "status": "healthy" if redis_healthy else "unhealthy",
                        "connectivity": redis_healthy
                    },
                    "token_bucket": {
                        "status": "healthy"  # Token bucket service is stateless
                    }
                },
                "timestamp": time.time()
            }
            
            # Add circuit breaker stats if available
            if hasattr(self.redis_state_manager.redis_client_manager, 'get_circuit_breaker_stats'):
                cb_stats = self.redis_state_manager.redis_client_manager.get_circuit_breaker_stats()
                if cb_stats:
                    health_info["components"]["circuit_breaker"] = cb_stats
            
            return health_info
            
        except Exception as e:
            logger.error("Decision API health check failed", error=str(e))
            return {
                "service": "rate_limit_decision_api",
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get operational statistics
        
        Returns:
            Statistics dictionary
        """
        # This is a basic implementation
        # In production, you'd want to track metrics like:
        # - Total requests processed
        # - Allowed vs blocked requests
        # - Average response time
        # - Error rates
        # - Circuit breaker statistics
        
        stats = {
            "service": "rate_limit_decision_api",
            "timestamp": time.time(),
            "components": {
                "rule_management": "active",
                "redis_state": "active", 
                "token_bucket": "active"
            }
        }
        
        # Add circuit breaker stats if available
        try:
            if hasattr(self.redis_state_manager.redis_client_manager, 'get_circuit_breaker_stats'):
                cb_stats = self.redis_state_manager.redis_client_manager.get_circuit_breaker_stats()
                if cb_stats:
                    stats["circuit_breaker"] = cb_stats
        except:
            pass
        
        return stats