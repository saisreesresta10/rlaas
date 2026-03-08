"""Unit tests for dependency injection container"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rlaas.container import ServiceContainer, get_container, shutdown_container, set_container
from rlaas.config import RLaaSConfig


class TestServiceContainer:
    """Test ServiceContainer functionality"""
    
    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return RLaaSConfig()
    
    @pytest.mark.asyncio
    async def test_create_container(self, config):
        """Test creating service container"""
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager, \
             patch('rlaas.container.RedisStateManager') as mock_redis_state, \
             patch('rlaas.container.TokenBucketService') as mock_token_bucket, \
             patch('rlaas.container.RuleManagementService') as mock_rule_mgmt, \
             patch('rlaas.container.RateLimitDecisionAPI') as mock_decision_api:
            
            # Mock Redis client manager initialization
            mock_redis_instance = AsyncMock()
            mock_redis_manager.return_value = mock_redis_instance
            mock_redis_instance.initialize = AsyncMock()
            
            # Create container
            container = await ServiceContainer.create(config)
            
            # Verify all services are initialized
            assert container.config == config
            assert container.redis_client_manager == mock_redis_instance
            assert container.redis_state_manager is not None
            assert container.token_bucket_service is not None
            assert container.rule_management_service is not None
            assert container.decision_api is not None
            assert container.metrics_service is not None
            assert container.structured_logger is not None
            
            # Verify Redis client was initialized
            mock_redis_instance.initialize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_container_initialization_error(self, config):
        """Test container creation with initialization error"""
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager:
            # Mock Redis client manager to raise exception
            mock_redis_manager.side_effect = Exception("Redis connection failed")
            
            with pytest.raises(Exception, match="Redis connection failed"):
                await ServiceContainer.create(config)
    
    @pytest.mark.asyncio
    async def test_container_health_check(self, config):
        """Test container health check"""
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager, \
             patch('rlaas.container.RateLimitDecisionAPI') as mock_decision_api:
            
            # Mock Redis client manager
            mock_redis_instance = AsyncMock()
            mock_redis_manager.return_value = mock_redis_instance
            mock_redis_instance.initialize = AsyncMock()
            
            # Mock decision API health check
            mock_decision_instance = MagicMock()
            mock_decision_api.return_value = mock_decision_instance
            mock_decision_instance.health_check = AsyncMock(return_value={
                "status": "healthy",
                "components": {
                    "redis_state": {"status": "healthy"},
                    "rule_management": {"status": "healthy"}
                },
                "timestamp": 1234567890.0
            })
            
            # Create container
            container = await ServiceContainer.create(config)
            
            # Perform health check
            health_info = await container.health_check()
            
            # Verify health check results
            assert health_info["service"] == "rlaas_container"
            assert health_info["status"] == "healthy"
            assert "components" in health_info
            assert "container" in health_info
            assert health_info["container"]["config_loaded"] is True
            assert health_info["container"]["services_initialized"] is True
    
    @pytest.mark.asyncio
    async def test_container_health_check_with_metrics(self, config):
        """Test container health check with metrics enabled"""
        # Enable metrics in config
        config.metrics.enabled = True
        
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager, \
             patch('rlaas.container.RateLimitDecisionAPI') as mock_decision_api, \
             patch('rlaas.container.get_metrics_service') as mock_get_metrics:
            
            # Mock Redis client manager
            mock_redis_instance = AsyncMock()
            mock_redis_manager.return_value = mock_redis_instance
            mock_redis_instance.initialize = AsyncMock()
            
            # Mock decision API health check
            mock_decision_instance = MagicMock()
            mock_decision_api.return_value = mock_decision_instance
            mock_decision_instance.health_check = AsyncMock(return_value={
                "status": "healthy",
                "components": {},
                "timestamp": 1234567890.0
            })
            
            # Mock metrics service
            mock_metrics_instance = MagicMock()
            mock_get_metrics.return_value = mock_metrics_instance
            mock_metrics_instance.get_metrics_summary.return_value = {
                "counters": {"test_counter": 1},
                "histograms": {"test_histogram": []},
                "gauges": {"test_gauge": 0}
            }
            
            # Create container
            container = await ServiceContainer.create(config)
            
            # Perform health check
            health_info = await container.health_check()
            
            # Verify metrics component is included
            assert "metrics" in health_info["components"]
            assert health_info["components"]["metrics"]["status"] == "healthy"
            assert health_info["components"]["metrics"]["enabled"] is True
            assert health_info["components"]["metrics"]["total_metrics"] == 3
    
    @pytest.mark.asyncio
    async def test_container_health_check_error(self, config):
        """Test container health check with error"""
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager, \
             patch('rlaas.container.RateLimitDecisionAPI') as mock_decision_api:
            
            # Mock Redis client manager
            mock_redis_instance = AsyncMock()
            mock_redis_manager.return_value = mock_redis_instance
            mock_redis_instance.initialize = AsyncMock()
            
            # Mock decision API to raise exception
            mock_decision_instance = MagicMock()
            mock_decision_api.return_value = mock_decision_instance
            mock_decision_instance.health_check = AsyncMock(side_effect=Exception("Health check failed"))
            
            # Create container
            container = await ServiceContainer.create(config)
            
            # Perform health check
            health_info = await container.health_check()
            
            # Verify error handling
            assert health_info["service"] == "rlaas_container"
            assert health_info["status"] == "unhealthy"
            assert "error" in health_info
    
    @pytest.mark.asyncio
    async def test_container_shutdown(self, config):
        """Test container shutdown"""
        with patch('rlaas.container.RedisClientManager') as mock_redis_manager, \
             patch('rlaas.container.get_metrics_service') as mock_get_metrics:
            
            # Mock Redis client manager
            mock_redis_instance = AsyncMock()
            mock_redis_manager.return_value = mock_redis_instance
            mock_redis_instance.initialize = AsyncMock()
            mock_redis_instance.close = AsyncMock()
            
            # Mock metrics service
            mock_metrics_instance = MagicMock()
            mock_get_metrics.return_value = mock_metrics_instance
            mock_metrics_instance.reset_metrics = MagicMock()
            
            # Create container
            container = await ServiceContainer.create(config)
            
            # Shutdown container
            await container.shutdown()
            
            # Verify cleanup was called
            mock_redis_instance.close.assert_called_once()
            mock_metrics_instance.reset_metrics.assert_called_once()


class TestGlobalContainerFunctions:
    """Test global container management functions"""
    
    @pytest.mark.asyncio
    async def test_get_container(self):
        """Test getting global container"""
        # Clear any existing container
        import rlaas.container
        rlaas.container._container = None
        
        with patch('rlaas.container.ServiceContainer.create') as mock_create:
            mock_container = MagicMock()
            mock_create.return_value = mock_container
            
            # Get container
            container = await get_container()
            
            assert container == mock_container
            mock_create.assert_called_once()
            
            # Should return same instance on second call
            container2 = await get_container()
            assert container2 == mock_container
            assert mock_create.call_count == 1  # Not called again
    
    @pytest.mark.asyncio
    async def test_get_container_with_config(self):
        """Test getting container with custom config"""
        # Clear any existing container
        import rlaas.container
        rlaas.container._container = None
        
        custom_config = RLaaSConfig()
        custom_config.server.port = 9999
        
        with patch('rlaas.container.ServiceContainer.create') as mock_create:
            mock_container = MagicMock()
            mock_create.return_value = mock_container
            
            # Get container with custom config
            container = await get_container(custom_config)
            
            assert container == mock_container
            mock_create.assert_called_once_with(custom_config)
    
    @pytest.mark.asyncio
    async def test_shutdown_container(self):
        """Test shutting down global container"""
        # Set up mock container
        mock_container = AsyncMock()
        set_container(mock_container)
        
        # Shutdown container
        await shutdown_container()
        
        # Verify shutdown was called
        mock_container.shutdown.assert_called_once()
        
        # Verify container is cleared
        import rlaas.container
        assert rlaas.container._container is None
    
    def test_set_container(self):
        """Test setting global container"""
        mock_container = MagicMock()
        
        set_container(mock_container)
        
        import rlaas.container
        assert rlaas.container._container == mock_container