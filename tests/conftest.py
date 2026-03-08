"""Pytest configuration and fixtures for RLaaS tests"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from rlaas.redis_client import RedisConfig, RedisClientManager
from rlaas.decision_api import RateLimitDecisionAPI
from rlaas.models import RateLimitResponse


@pytest.fixture
def redis_config():
    """Provide Redis configuration for testing"""
    return RedisConfig(
        host="localhost",
        port=6379,
        db=1,  # Use different DB for tests
        socket_timeout=1.0,  # Longer timeout for tests
        socket_connect_timeout=1.0,
    )


@pytest_asyncio.fixture
async def redis_client_manager(redis_config):
    """Provide Redis client manager for testing"""
    manager = RedisClientManager(redis_config)
    try:
        await manager.initialize()
        yield manager
    except Exception:
        # Redis not available, skip tests that need it
        pytest.skip("Redis not available for testing")
    finally:
        await manager.close()


@pytest.fixture
def mock_decision_api():
    """Provide a mock decision API for testing"""
    mock_api = AsyncMock(spec=RateLimitDecisionAPI)
    
    # Configure default return values
    mock_api.check_rate_limit.return_value = RateLimitResponse(
        allowed=True,
        remaining_tokens=10,
        retry_after_ms=None,
        reset_after_ms=1000
    )
    
    mock_api.get_bucket_info.return_value = {
        "client_id": "test_client",
        "endpoint": "/api/test", 
        "http_method": "GET",
        "tokens": 10.0,
        "last_refill": 1640995200.0,
        "limit": 100,
        "window_seconds": 60,
        "burst": 120
    }
    
    mock_api.health_check.return_value = {
        "service": "rate_limit_decision_api",
        "status": "healthy",
        "components": {
            "rule_management": {"status": "healthy"},
            "redis_state": {"status": "healthy", "connectivity": True}
        }
    }
    
    mock_api.get_stats.return_value = {
        "requests_total": 100,
        "requests_allowed": 90,
        "requests_blocked": 10,
        "circuit_breaker_state": "closed",
        "active_buckets": 5,
        "rules_count": 3
    }
    
    return mock_api