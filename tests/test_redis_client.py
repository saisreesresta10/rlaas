"""Unit tests for Redis client functionality"""

import pytest
import pytest_asyncio
from rlaas.redis_client import RedisConfig, RedisClientManager


class TestRedisConfig:
    """Test Redis configuration"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = RedisConfig()
        
        assert config.host == "localhost"
        assert config.port == 6379
        assert config.db == 0
        assert config.password is None
        assert config.max_connections == 10
        assert config.socket_timeout == 0.1
        assert config.socket_connect_timeout == 0.1
    
    def test_custom_config(self):
        """Test custom configuration values"""
        config = RedisConfig(
            host="redis.example.com",
            port=6380,
            db=2,
            password="secret",
            max_connections=20,
            socket_timeout=0.2,
            socket_connect_timeout=0.3,
        )
        
        assert config.host == "redis.example.com"
        assert config.port == 6380
        assert config.db == 2
        assert config.password == "secret"
        assert config.max_connections == 20
        assert config.socket_timeout == 0.2
        assert config.socket_connect_timeout == 0.3


class TestRedisClientManager:
    """Test Redis client manager functionality"""
    
    @pytest_asyncio.fixture
    async def manager(self, redis_config):
        """Create Redis client manager for testing"""
        manager = RedisClientManager(redis_config)
        yield manager
        if manager._client:
            await manager.close()
    
    async def test_initialization_success(self, manager):
        """Test successful Redis initialization"""
        await manager.initialize()
        
        assert manager._pool is not None
        assert manager._client is not None
        
        # Test that client is accessible
        client = manager.client
        assert client is not None
    
    async def test_client_property_before_init(self, manager):
        """Test client property raises error before initialization"""
        with pytest.raises(RuntimeError, match="Redis client not initialized"):
            _ = manager.client
    
    async def test_health_check_success(self, manager):
        """Test health check with working Redis"""
        await manager.initialize()
        
        health_status = await manager.health_check()
        assert health_status is True
    
    async def test_health_check_before_init(self, manager):
        """Test health check before initialization"""
        health_status = await manager.health_check()
        assert health_status is False
    
    async def test_close_connection(self, manager):
        """Test closing Redis connection"""
        await manager.initialize()
        await manager.close()
        
        # Health check should fail after closing
        health_status = await manager.health_check()
        assert health_status is False