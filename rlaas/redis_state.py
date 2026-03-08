"""Redis state management for distributed rate limiting"""

import json
import time
from typing import Optional, Dict, Any, List, Tuple
import structlog
import redis.asyncio as redis

from .models import RateLimitRule, TokenBucketState, TokenBucketResult
from .redis_client import RedisClientManager
from .lua_scripts import TOKEN_BUCKET_REFILL_AND_CONSUME, TOKEN_BUCKET_GET_AND_REFILL

logger = structlog.get_logger()


class RedisStateManager:
    """Manages distributed state for rate limiting using Redis"""
    
    def __init__(self, redis_client_manager: RedisClientManager):
        """
        Initialize Redis state manager
        
        Args:
            redis_client_manager: Redis client manager instance
        """
        self.redis_client_manager = redis_client_manager
    
    def generate_bucket_key(self, client_id: str, endpoint: str, http_method: str) -> str:
        """
        Generate Redis key for token bucket state
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            Redis key following the pattern: rate_limit:{client_id}:{endpoint}:{http_method}
        """
        return f"rate_limit:{client_id}:{endpoint}:{http_method}"
    
    def generate_rule_key(self, client_id: str, endpoint: str, http_method: str) -> str:
        """
        Generate Redis key for rate limit rule storage
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            Redis key for rule storage
        """
        return f"rule:{client_id}:{endpoint}:{http_method}"
    
    def serialize_bucket_state(self, state: TokenBucketState) -> str:
        """
        Serialize token bucket state to JSON string for Redis storage
        
        Args:
            state: Token bucket state to serialize
            
        Returns:
            JSON string representation of the state
        """
        data = {
            "tokens": state.tokens,
            "last_refill": state.last_refill,
            "limit": state.rule.limit,
            "window_seconds": state.rule.window_seconds,
            "burst": state.rule.burst,
            "client_id": state.rule.client_id,
            "endpoint": state.rule.endpoint,
            "http_method": state.rule.http_method
        }
        return json.dumps(data)
    
    def deserialize_bucket_state(self, data: str) -> TokenBucketState:
        """
        Deserialize JSON string from Redis to token bucket state
        
        Args:
            data: JSON string from Redis
            
        Returns:
            TokenBucketState object
            
        Raises:
            ValueError: If data cannot be deserialized
        """
        try:
            parsed = json.loads(data)
            
            # Reconstruct the rule
            rule = RateLimitRule(
                client_id=parsed["client_id"],
                endpoint=parsed["endpoint"],
                http_method=parsed["http_method"],
                limit=parsed["limit"],
                window_seconds=parsed["window_seconds"],
                burst=parsed["burst"]
            )
            
            # Create the state
            return TokenBucketState(
                tokens=parsed["tokens"],
                last_refill=parsed["last_refill"],
                rule=rule
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"Failed to deserialize bucket state: {e}")
    
    def serialize_rule(self, rule: RateLimitRule) -> str:
        """
        Serialize rate limit rule to JSON string for Redis storage
        
        Args:
            rule: Rate limit rule to serialize
            
        Returns:
            JSON string representation of the rule
        """
        data = {
            "client_id": rule.client_id,
            "endpoint": rule.endpoint,
            "http_method": rule.http_method,
            "limit": rule.limit,
            "window_seconds": rule.window_seconds,
            "burst": rule.burst,
            "created_at": time.time()
        }
        return json.dumps(data)
    
    def deserialize_rule(self, data: str) -> RateLimitRule:
        """
        Deserialize JSON string from Redis to rate limit rule
        
        Args:
            data: JSON string from Redis
            
        Returns:
            RateLimitRule object
            
        Raises:
            ValueError: If data cannot be deserialized
        """
        try:
            parsed = json.loads(data)
            
            return RateLimitRule(
                client_id=parsed["client_id"],
                endpoint=parsed["endpoint"],
                http_method=parsed["http_method"],
                limit=parsed["limit"],
                window_seconds=parsed["window_seconds"],
                burst=parsed["burst"]
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"Failed to deserialize rule: {e}")
    
    async def get_bucket_state(self, client_id: str, endpoint: str, http_method: str) -> Optional[TokenBucketState]:
        """
        Retrieve token bucket state from Redis with circuit breaker protection
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            TokenBucketState if found, None otherwise
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            bucket_key = self.generate_bucket_key(client_id, endpoint, http_method)
            
            # Execute Redis operation with circuit breaker protection
            async def redis_operation():
                client = self.redis_client_manager.client
                return await client.get(bucket_key)
            
            data = await self.redis_client_manager.execute_redis_operation(redis_operation)
            
            if data is None:
                logger.debug(
                    "Bucket state not found",
                    bucket_key=bucket_key,
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                return None
            
            state = self.deserialize_bucket_state(data)
            logger.debug(
                "Retrieved bucket state",
                bucket_key=bucket_key,
                tokens=state.tokens,
                last_refill=state.last_refill
            )
            return state
            
        except redis.RedisError as e:
            logger.error(
                "Failed to get bucket state from Redis",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
        except ValueError as e:
            logger.error(
                "Failed to deserialize bucket state",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            # Return None for corrupted data - will be recreated
            return None
    
    async def set_bucket_state(
        self, 
        client_id: str, 
        endpoint: str, 
        http_method: str, 
        state: TokenBucketState,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Store token bucket state in Redis with circuit breaker protection
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            state: Token bucket state to store
            ttl_seconds: Optional TTL for the key (defaults to window_seconds * 2)
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            bucket_key = self.generate_bucket_key(client_id, endpoint, http_method)
            serialized_state = self.serialize_bucket_state(state)
            
            # Set TTL to 2x the window size for auto-cleanup of inactive buckets
            if ttl_seconds is None:
                ttl_seconds = state.rule.window_seconds * 2
            
            # Execute Redis operation with circuit breaker protection
            async def redis_operation():
                client = self.redis_client_manager.client
                return await client.setex(bucket_key, ttl_seconds, serialized_state)
            
            await self.redis_client_manager.execute_redis_operation(redis_operation)
            
            logger.debug(
                "Stored bucket state",
                bucket_key=bucket_key,
                tokens=state.tokens,
                ttl_seconds=ttl_seconds
            )
            
        except redis.RedisError as e:
            logger.error(
                "Failed to set bucket state in Redis",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def get_rule(self, client_id: str, endpoint: str, http_method: str) -> Optional[RateLimitRule]:
        """
        Retrieve rate limit rule from Redis
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            RateLimitRule if found, None otherwise
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            rule_key = self.generate_rule_key(client_id, endpoint, http_method)
            client = self.redis_client_manager.client
            
            data = await client.get(rule_key)
            if data is None:
                logger.debug(
                    "Rule not found",
                    rule_key=rule_key,
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                return None
            
            rule = self.deserialize_rule(data)
            logger.debug(
                "Retrieved rule",
                rule_key=rule_key,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                burst=rule.burst
            )
            return rule
            
        except redis.RedisError as e:
            logger.error(
                "Failed to get rule from Redis",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
        except ValueError as e:
            logger.error(
                "Failed to deserialize rule",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            # Return None for corrupted data
            return None
    
    async def set_rule(self, rule: RateLimitRule) -> None:
        """
        Store rate limit rule in Redis
        
        Args:
            rule: Rate limit rule to store
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            rule_key = self.generate_rule_key(rule.client_id, rule.endpoint, rule.http_method)
            client = self.redis_client_manager.client
            
            serialized_rule = self.serialize_rule(rule)
            
            # Rules don't expire - they persist until explicitly deleted
            await client.set(rule_key, serialized_rule)
            
            logger.info(
                "Stored rule",
                rule_key=rule_key,
                client_id=rule.client_id,
                endpoint=rule.endpoint,
                http_method=rule.http_method,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                burst=rule.burst
            )
            
        except redis.RedisError as e:
            logger.error(
                "Failed to set rule in Redis",
                error=str(e),
                client_id=rule.client_id,
                endpoint=rule.endpoint,
                http_method=rule.http_method
            )
            raise
    
    async def delete_rule(self, client_id: str, endpoint: str, http_method: str) -> bool:
        """
        Delete rate limit rule from Redis
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            True if rule was deleted, False if it didn't exist
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            rule_key = self.generate_rule_key(client_id, endpoint, http_method)
            client = self.redis_client_manager.client
            
            deleted_count = await client.delete(rule_key)
            
            if deleted_count > 0:
                logger.info(
                    "Deleted rule",
                    rule_key=rule_key,
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                return True
            else:
                logger.debug(
                    "Rule not found for deletion",
                    rule_key=rule_key,
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                )
                return False
                
        except redis.RedisError as e:
            logger.error(
                "Failed to delete rule from Redis",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def execute_lua_script(self, script: str, keys: List[str], args: List[str]) -> Any:
        """
        Execute Lua script with circuit breaker protection
        
        Args:
            script: Lua script to execute
            keys: Redis keys for the script
            args: Arguments for the script
            
        Returns:
            Script execution result
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        try:
            # Execute Lua script with circuit breaker protection
            async def redis_operation():
                client = self.redis_client_manager.client
                return await client.eval(script, len(keys), *keys, *args)
            
            result = await self.redis_client_manager.execute_redis_operation(redis_operation)
            
            logger.debug(
                "Executed Lua script",
                keys=keys,
                args=args,
                result=result
            )
            
            return result
            
        except redis.RedisError as e:
            logger.error(
                "Failed to execute Lua script",
                error=str(e),
                keys=keys,
                args=args
            )
            raise
    
    async def health_check(self) -> bool:
        """
        Check Redis connectivity and basic operations with circuit breaker protection
        
        Returns:
            True if Redis is healthy, False otherwise
        """
        try:
            # Use the underlying client manager's health check which includes circuit breaker protection
            return await self.redis_client_manager.health_check()
            
        except Exception as e:
            logger.warning("Redis health check failed", error=str(e))
            return False
    
    async def atomic_refill_and_consume(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        rule: RateLimitRule,
        tokens_to_consume: int = 1,
        current_time: Optional[float] = None
    ) -> TokenBucketResult:
        """
        Atomically refill tokens and attempt consumption using Lua script
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            rule: Rate limiting rule
            tokens_to_consume: Number of tokens to consume
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            TokenBucketResult with operation result
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        if current_time is None:
            current_time = time.time()
        
        try:
            bucket_key = self.generate_bucket_key(client_id, endpoint, http_method)
            ttl_seconds = rule.window_seconds * 2  # Auto-cleanup TTL
            
            # Execute Lua script for atomic operation
            result = await self.execute_lua_script(
                TOKEN_BUCKET_REFILL_AND_CONSUME,
                [bucket_key],
                [
                    str(current_time),
                    str(rule.get_refill_rate()),
                    str(rule.burst),
                    str(tokens_to_consume),
                    str(ttl_seconds)
                ]
            )
            
            # Parse result: [success (0/1), remaining_tokens]
            success = bool(result[0])
            remaining_tokens = int(result[1])
            
            if success:
                # Calculate reset time (when bucket will be full again)
                tokens_until_full = rule.burst - remaining_tokens
                seconds_until_full = tokens_until_full / rule.get_refill_rate()
                reset_after_ms = int(seconds_until_full * 1000)
                
                token_result = TokenBucketResult(
                    success=True,
                    remaining_tokens=remaining_tokens,
                    retry_after_ms=None,
                    reset_after_ms=reset_after_ms
                )
                
                logger.debug(
                    "Atomic token consumption successful",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    remaining_tokens=remaining_tokens,
                    reset_after_ms=reset_after_ms
                )
            else:
                # Calculate retry time
                tokens_needed = tokens_to_consume - remaining_tokens
                seconds_until_available = tokens_needed / rule.get_refill_rate()
                retry_after_ms = int(seconds_until_available * 1000)
                
                token_result = TokenBucketResult(
                    success=False,
                    remaining_tokens=remaining_tokens,
                    retry_after_ms=retry_after_ms,
                    reset_after_ms=None
                )
                
                logger.debug(
                    "Atomic token consumption blocked",
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method,
                    tokens_available=remaining_tokens,
                    tokens_requested=tokens_to_consume,
                    retry_after_ms=retry_after_ms
                )
            
            return token_result
            
        except redis.RedisError as e:
            logger.error(
                "Failed to execute atomic refill and consume",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def atomic_get_and_refill(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        rule: RateLimitRule,
        current_time: Optional[float] = None
    ) -> int:
        """
        Atomically get current token count after refill (no consumption)
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            rule: Rate limiting rule
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Current token count after refill
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        if current_time is None:
            current_time = time.time()
        
        try:
            bucket_key = self.generate_bucket_key(client_id, endpoint, http_method)
            ttl_seconds = rule.window_seconds * 2
            
            # Execute Lua script for atomic get and refill
            result = await self.execute_lua_script(
                TOKEN_BUCKET_GET_AND_REFILL,
                [bucket_key],
                [
                    str(current_time),
                    str(rule.get_refill_rate()),
                    str(rule.burst),
                    str(ttl_seconds)
                ]
            )
            
            current_tokens = int(result)
            
            logger.debug(
                "Atomic get and refill completed",
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                current_tokens=current_tokens
            )
            
            return current_tokens
            
        except redis.RedisError as e:
            logger.error(
                "Failed to execute atomic get and refill",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
    
    async def create_or_update_bucket_with_rule(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        rule: RateLimitRule,
        preserve_tokens: bool = True,
        current_time: Optional[float] = None
    ) -> TokenBucketState:
        """
        Create or update bucket state when rule changes
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            rule: New rate limiting rule
            preserve_tokens: Whether to preserve existing token count
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Updated TokenBucketState
            
        Raises:
            redis.RedisError: If Redis operation fails
        """
        if current_time is None:
            current_time = time.time()
        
        try:
            # Get existing state if preserving tokens
            existing_state = None
            if preserve_tokens:
                existing_state = await self.get_bucket_state(client_id, endpoint, http_method)
            
            if existing_state and preserve_tokens:
                # Preserve existing tokens but cap at new burst capacity
                preserved_tokens = min(existing_state.tokens, float(rule.burst))
                
                new_state = TokenBucketState(
                    tokens=preserved_tokens,
                    last_refill=current_time,
                    rule=rule
                )
            else:
                # Create new state with full burst capacity
                new_state = TokenBucketState(
                    tokens=float(rule.burst),
                    last_refill=current_time,
                    rule=rule
                )
            
            # Store the new state
            await self.set_bucket_state(client_id, endpoint, http_method, new_state)
            
            # Also store the rule
            await self.set_rule(rule)
            
            logger.info(
                "Created/updated bucket with rule",
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                tokens=new_state.tokens,
                rule_limit=rule.limit,
                rule_burst=rule.burst,
                preserved_tokens=preserve_tokens
            )
            
            return new_state
            
        except redis.RedisError as e:
            logger.error(
                "Failed to create/update bucket with rule",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            raise
        """
        Get comprehensive information about a bucket including state and rule
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            Dictionary with bucket information or None if not found
        """
        try:
            # Get both state and rule
            state = await self.get_bucket_state(client_id, endpoint, http_method)
            rule = await self.get_rule(client_id, endpoint, http_method)
            
            if state is None and rule is None:
                return None
            
            info = {
                "bucket_key": self.generate_bucket_key(client_id, endpoint, http_method),
                "rule_key": self.generate_rule_key(client_id, endpoint, http_method),
                "has_state": state is not None,
                "has_rule": rule is not None,
            }
            
            if state:
                info.update({
                    "current_tokens": state.tokens,
                    "last_refill": state.last_refill,
                    "state_rule": {
                        "limit": state.rule.limit,
                        "window_seconds": state.rule.window_seconds,
                        "burst": state.rule.burst,
                    }
                })
            
            if rule:
                info.update({
                    "configured_rule": {
                        "limit": rule.limit,
                        "window_seconds": rule.window_seconds,
                        "burst": rule.burst,
                    }
                })
            
            return info
            
        except Exception as e:
            logger.error(
                "Failed to get bucket info",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            return None
    
    async def get_bucket_info(self, client_id: str, endpoint: str, http_method: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive information about a bucket including state and rule
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            
        Returns:
            Dictionary with bucket information or None if not found
        """
        try:
            # Get both state and rule
            state = await self.get_bucket_state(client_id, endpoint, http_method)
            rule = await self.get_rule(client_id, endpoint, http_method)
            
            if state is None and rule is None:
                return None
            
            info = {
                "bucket_key": self.generate_bucket_key(client_id, endpoint, http_method),
                "rule_key": self.generate_rule_key(client_id, endpoint, http_method),
                "has_state": state is not None,
                "has_rule": rule is not None,
            }
            
            if state:
                info.update({
                    "current_tokens": state.tokens,
                    "last_refill": state.last_refill,
                    "state_rule": {
                        "limit": state.rule.limit,
                        "window_seconds": state.rule.window_seconds,
                        "burst": state.rule.burst,
                    }
                })
            
            if rule:
                info.update({
                    "configured_rule": {
                        "limit": rule.limit,
                        "window_seconds": rule.window_seconds,
                        "burst": rule.burst,
                    }
                })
            
            return info
            
        except Exception as e:
            logger.error(
                "Failed to get bucket info",
                error=str(e),
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method
            )
            return None