"""Rule management service for dynamic rate limiting configuration"""

import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import structlog

from .models import RateLimitRule
from .redis_state import RedisStateManager
from .circuit_breaker import CircuitBreakerError

logger = structlog.get_logger()


@dataclass
class DefaultRuleConfig:
    """Configuration for default rate limiting rules"""
    limit: int = 100                    # Default requests per window
    window_seconds: int = 60            # Default window size (1 minute)
    burst: int = 120                    # Default burst capacity (20% above limit)
    
    def to_rule(self, client_id: str, endpoint: str, http_method: str) -> RateLimitRule:
        """Convert to RateLimitRule"""
        return RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=self.limit,
            window_seconds=self.window_seconds,
            burst=self.burst
        )


class RuleValidationError(Exception):
    """Exception raised when rule validation fails"""
    pass


class RuleManagementService:
    """
    Service for managing rate limiting rules with dynamic updates and fallback behavior
    
    Features:
    - Dynamic rule creation and updates
    - Rule retrieval with fallback to defaults
    - Rule validation and error handling
    - State preservation during updates
    """
    
    def __init__(
        self, 
        redis_state_manager: RedisStateManager,
        default_rule_config: Optional[DefaultRuleConfig] = None
    ):
        """
        Initialize rule management service
        
        Args:
            redis_state_manager: Redis state manager for rule persistence
            default_rule_config: Default rule configuration for fallback
        """
        self.redis_state_manager = redis_state_manager
        self.default_rule_config = default_rule_config or DefaultRuleConfig()
        
        logger.info(
            "Rule management service initialized",
            default_limit=self.default_rule_config.limit,
            default_window=self.default_rule_config.window_seconds,
            default_burst=self.default_rule_config.burst
        )
    
    def validate_rule(self, rule: RateLimitRule) -> None:
        """
        Validate rate limiting rule parameters
        
        Args:
            rule: Rule to validate
            
        Raises:
            RuleValidationError: If rule parameters are invalid
        """
        errors = []
        
        # Validate client_id
        if not rule.client_id or not rule.client_id.strip():
            errors.append("client_id cannot be empty")
        
        # Validate endpoint
        if not rule.endpoint or not rule.endpoint.strip():
            errors.append("endpoint cannot be empty")
        
        # Validate http_method
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if rule.http_method not in valid_methods:
            errors.append(f"http_method must be one of {valid_methods}")
        
        # Validate limit
        if rule.limit <= 0:
            errors.append("limit must be positive")
        
        # Validate window_seconds
        if rule.window_seconds <= 0:
            errors.append("window_seconds must be positive")
        
        # Validate burst
        if rule.burst <= 0:
            errors.append("burst must be positive")
        
        # Validate burst >= limit
        if rule.burst < rule.limit:
            errors.append("burst must be greater than or equal to limit")
        
        # Check reasonable limits to prevent abuse
        if rule.limit > 100000:  # 100k requests per window
            errors.append("limit exceeds maximum allowed value (100,000)")
        
        if rule.window_seconds > 86400:  # 24 hours
            errors.append("window_seconds exceeds maximum allowed value (86,400)")
        
        if rule.burst > 200000:  # 200k burst capacity
            errors.append("burst exceeds maximum allowed value (200,000)")
        
        if errors:
            error_msg = "; ".join(errors)
            logger.warning(
                "Rule validation failed",
                client_id=rule.client_id,
                endpoint=rule.endpoint,
                http_method=rule.http_method,
                errors=errors
            )
            raise RuleValidationError(f"Rule validation failed: {error_msg}")
        
        logger.debug(
            "Rule validation passed",
            client_id=rule.client_id,
            endpoint=rule.endpoint,
            http_method=rule.http_method,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            burst=rule.burst
        )
    
    async def create_rule(
        self, 
        client_id: str, 
        endpoint: str, 
        http_method: str,
        limit: int,
        window_seconds: int,
        burst: int,
        preserve_existing_tokens: bool = True
    ) -> RateLimitRule:
        """
        Create or update a rate limiting rule
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            limit: Requests per window
            window_seconds: Window size in seconds
            burst: Burst capacity
            preserve_existing_tokens: Whether to preserve existing token count
            
        Returns:
            Created/updated rule
            
        Raises:
            RuleValidationError: If rule parameters are invalid
            Exception: If Redis operation fails
        """
        # Create rule object
        rule = RateLimitRule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            window_seconds=window_seconds,
            burst=burst
        )
        
        # Validate rule
        self.validate_rule(rule)
        
        try:
            # Check if rule already exists
            existing_rule = await self.redis_state_manager.get_rule(
                client_id, endpoint, http_method
            )
            
            # Store the rule in Redis
            await self.redis_state_manager.set_rule(rule)
            
            # Update bucket state with new rule if needed
            if existing_rule or not preserve_existing_tokens:
                await self.redis_state_manager.create_or_update_bucket_with_rule(
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    rule=rule,
                    preserve_tokens=preserve_existing_tokens
                )
            
            if existing_rule:
                logger.info(
                    "Rule updated successfully",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    old_limit=existing_rule.limit,
                    new_limit=rule.limit,
                    old_burst=existing_rule.burst,
                    new_burst=rule.burst,
                    preserve_tokens=preserve_existing_tokens
                )
            else:
                logger.info(
                    "Rule created successfully",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    limit=rule.limit,
                    window_seconds=rule.window_seconds,
                    burst=rule.burst
                )
            
            return rule
            
        except CircuitBreakerError as e:
            logger.error(
                "Failed to create/update rule due to circuit breaker",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to create/update rule",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def get_rule(
        self, 
        client_id: str, 
        endpoint: str, 
        http_method: str,
        use_default_fallback: bool = True
    ) -> RateLimitRule:
        """
        Retrieve rate limiting rule with fallback to default
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            use_default_fallback: Whether to fallback to default rule if not found
            
        Returns:
            Rate limiting rule (configured or default)
            
        Raises:
            Exception: If Redis operation fails and no fallback is available
        """
        try:
            # Try to get configured rule from Redis
            rule = await self.redis_state_manager.get_rule(
                client_id, endpoint, http_method
            )
            
            if rule:
                logger.debug(
                    "Retrieved configured rule",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    limit=rule.limit,
                    window_seconds=rule.window_seconds,
                    burst=rule.burst
                )
                return rule
            
            # Rule not found, use default if fallback is enabled
            if use_default_fallback:
                default_rule = self.default_rule_config.to_rule(
                    client_id, endpoint, http_method
                )
                
                logger.debug(
                    "Using default rule fallback",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    limit=default_rule.limit,
                    window_seconds=default_rule.window_seconds,
                    burst=default_rule.burst
                )
                
                return default_rule
            
            # No fallback, raise exception
            raise ValueError(f"No rule found for {client_id}:{endpoint}:{http_method}")
            
        except CircuitBreakerError as e:
            # Circuit breaker is open, use default rule if fallback enabled
            if use_default_fallback:
                default_rule = self.default_rule_config.to_rule(
                    client_id, endpoint, http_method
                )
                
                logger.warning(
                    "Using default rule due to circuit breaker",
                    error=str(e),
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                
                return default_rule
            
            logger.error(
                "Failed to get rule due to circuit breaker",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
        except Exception as e:
            # Other Redis errors, use default rule if fallback enabled
            if use_default_fallback:
                default_rule = self.default_rule_config.to_rule(
                    client_id, endpoint, http_method
                )
                
                logger.warning(
                    "Using default rule due to Redis error",
                    error=str(e),
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                
                return default_rule
            
            logger.error(
                "Failed to get rule from Redis",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def update_rule(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        burst: Optional[int] = None,
        preserve_existing_tokens: bool = True
    ) -> RateLimitRule:
        """
        Update specific fields of an existing rule
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            limit: New limit (optional)
            window_seconds: New window size (optional)
            burst: New burst capacity (optional)
            preserve_existing_tokens: Whether to preserve existing token count
            
        Returns:
            Updated rule
            
        Raises:
            ValueError: If rule doesn't exist
            RuleValidationError: If updated parameters are invalid
        """
        # Get existing rule
        existing_rule = await self.get_rule(
            client_id, endpoint, http_method, use_default_fallback=False
        )
        
        # Update fields if provided
        updated_limit = limit if limit is not None else existing_rule.limit
        updated_window = window_seconds if window_seconds is not None else existing_rule.window_seconds
        updated_burst = burst if burst is not None else existing_rule.burst
        
        # Create updated rule
        return await self.create_rule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=updated_limit,
            window_seconds=updated_window,
            burst=updated_burst,
            preserve_existing_tokens=preserve_existing_tokens
        )
    
    async def delete_rule(
        self, 
        client_id: str, 
        endpoint: str, 
        http_method: str
    ) -> bool:
        """
        Delete a rate limiting rule
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            True if rule was deleted, False if it didn't exist
            
        Raises:
            Exception: If Redis operation fails
        """
        try:
            deleted = await self.redis_state_manager.delete_rule(
                client_id, endpoint, http_method
            )
            
            if deleted:
                logger.info(
                    "Rule deleted successfully",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
            else:
                logger.debug(
                    "Rule not found for deletion",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
            
            return deleted
            
        except Exception as e:
            logger.error(
                "Failed to delete rule",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def list_rules(
        self, 
        client_id: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List configured rules (basic implementation)
        
        Note: This is a basic implementation. In production, you might want
        to use Redis SCAN or maintain a separate index for efficient listing.
        
        Args:
            client_id: Filter by client ID (optional)
            endpoint: Filter by endpoint (optional)
            
        Returns:
            List of rule information dictionaries
        """
        # This is a placeholder implementation
        # In a real system, you'd need to maintain an index of rules
        # or use Redis SCAN to find all rule keys
        
        logger.warning(
            "list_rules called - basic implementation only",
            client_id=client_id,
            endpoint=endpoint
        )
        
        # Return empty list for now
        # TODO: Implement proper rule listing with Redis SCAN
        return []
    
    def get_default_rule_config(self) -> DefaultRuleConfig:
        """
        Get current default rule configuration
        
        Returns:
            Default rule configuration
        """
        return self.default_rule_config
    
    def update_default_rule_config(
        self,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        burst: Optional[int] = None
    ) -> DefaultRuleConfig:
        """
        Update default rule configuration
        
        Args:
            limit: New default limit (optional)
            window_seconds: New default window size (optional)
            burst: New default burst capacity (optional)
            
        Returns:
            Updated default configuration
        """
        if limit is not None:
            self.default_rule_config.limit = limit
        if window_seconds is not None:
            self.default_rule_config.window_seconds = window_seconds
        if burst is not None:
            self.default_rule_config.burst = burst
        
        logger.info(
            "Default rule configuration updated",
            limit=self.default_rule_config.limit,
            window_seconds=self.default_rule_config.window_seconds,
            burst=self.default_rule_config.burst
        )
        
        return self.default_rule_config
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check for rule management service
        
        Returns:
            Health check results
        """
        try:
            # Check Redis connectivity through state manager
            redis_healthy = await self.redis_state_manager.health_check()
            
            health_info = {
                "service": "rule_management",
                "status": "healthy" if redis_healthy else "degraded",
                "redis_connectivity": redis_healthy,
                "default_config": {
                    "limit": self.default_rule_config.limit,
                    "window_seconds": self.default_rule_config.window_seconds,
                    "burst": self.default_rule_config.burst
                },
                "timestamp": time.time()
            }
            
            if not redis_healthy:
                health_info["message"] = "Redis connectivity issues - using default rules only"
            
            return health_info
            
        except Exception as e:
            logger.error("Rule management health check failed", error=str(e))
            return {
                "service": "rule_management",
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }