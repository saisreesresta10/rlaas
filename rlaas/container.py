"""Dependency injection container for RLaaS services"""

from typing import Optional
from dataclasses import dataclass

from .config import RLaaSConfig
from .redis_client import RedisClientManager
from .redis_state import RedisStateManager
from .token_bucket import TokenBucketService
from .rule_management import RuleManagementService
from .decision_api import RateLimitDecisionAPI
from .metrics import MetricsService, get_metrics_service
from .logging_service import StructuredLogger, get_structured_logger


@dataclass
class ServiceContainer:
    """Container for all RLaaS services with dependency injection"""
    
    # Configuration
    config: RLaaSConfig
    
    # Core services
    redis_client_manager: RedisClientManager
    redis_state_manager: RedisStateManager
    token_bucket_service: TokenBucketService
    rule_management_service: RuleManagementService
    decision_api: RateLimitDecisionAPI
    
    # Observability services
    metrics_service: MetricsService
    structured_logger: StructuredLogger
    
    @classmethod
    async def create(cls, config: RLaaSConfig) -> 'ServiceContainer':
        """
        Create and initialize all services with proper dependency injection
        
        Args:
            config: Application configuration
            
        Returns:
            Initialized service container
        """
        structured_logger = get_structured_logger()
        
        try:
            # Log container initialization start
            structured_logger.log_startup_event(
                startup_event="container_initialization_start",
                component="container",
                success=True,
                details={"services": [
                    "redis_client_manager",
                    "redis_state_manager", 
                    "token_bucket_service",
                    "rule_management_service",
                    "decision_api",
                    "metrics_service"
                ]}
            )
            
            # Initialize Redis client manager
            redis_config = config.redis.to_redis_config()
            redis_client_manager = RedisClientManager(redis_config)
            
            # Initialize Redis client connection
            await redis_client_manager.initialize()
            
            # Initialize Redis state manager (depends on Redis client)
            redis_state_manager = RedisStateManager(redis_client_manager)
            
            # Initialize token bucket service (stateless)
            token_bucket_service = TokenBucketService()
            
            # Initialize rule management service (depends on Redis state and default config)
            default_rule_config = config.default_rules.to_default_rule_config()
            rule_management_service = RuleManagementService(
                redis_state_manager=redis_state_manager,
                default_rule_config=default_rule_config
            )
            
            # Initialize decision API (depends on all core services)
            decision_api = RateLimitDecisionAPI(
                rule_management_service=rule_management_service,
                redis_state_manager=redis_state_manager,
                token_bucket_service=token_bucket_service
            )
            
            # Get observability services
            metrics_service = get_metrics_service()
            
            # Create container
            container = cls(
                config=config,
                redis_client_manager=redis_client_manager,
                redis_state_manager=redis_state_manager,
                token_bucket_service=token_bucket_service,
                rule_management_service=rule_management_service,
                decision_api=decision_api,
                metrics_service=metrics_service,
                structured_logger=structured_logger
            )
            
            # Log successful initialization
            structured_logger.log_startup_event(
                startup_event="container_initialization_complete",
                component="container",
                success=True,
                details={
                    "redis_host": config.redis.host,
                    "redis_port": config.redis.port,
                    "circuit_breaker_enabled": config.redis.enable_circuit_breaker,
                    "default_limit": config.default_rules.limit,
                    "metrics_enabled": config.metrics.enabled
                }
            )
            
            return container
            
        except Exception as e:
            # Log initialization failure
            structured_logger.log_startup_event(
                startup_event="container_initialization_failed",
                component="container",
                success=False,
                details={"error": str(e)}
            )
            
            structured_logger.log_error(
                error_type="initialization_error",
                component="container",
                message=f"Failed to initialize service container: {str(e)}"
            )
            
            raise
    
    async def health_check(self) -> dict:
        """
        Perform comprehensive health check of all services
        
        Returns:
            Health check results
        """
        try:
            # Get health from decision API (which checks all core services)
            decision_health = await self.decision_api.health_check()
            
            # Add container-level information
            health_info = {
                "service": "rlaas_container",
                "status": decision_health.get("status", "unknown"),
                "components": decision_health.get("components", {}),
                "container": {
                    "config_loaded": self.config is not None,
                    "services_initialized": True
                },
                "timestamp": decision_health.get("timestamp")
            }
            
            # Add metrics service health if enabled
            if self.config.metrics.enabled:
                try:
                    metrics_summary = self.metrics_service.get_metrics_summary()
                    health_info["components"]["metrics"] = {
                        "status": "healthy",
                        "enabled": True,
                        "total_metrics": len(metrics_summary.get("counters", {})) + 
                                       len(metrics_summary.get("histograms", {})) + 
                                       len(metrics_summary.get("gauges", {}))
                    }
                except Exception as e:
                    health_info["components"]["metrics"] = {
                        "status": "unhealthy",
                        "enabled": True,
                        "error": str(e)
                    }
            else:
                health_info["components"]["metrics"] = {
                    "status": "disabled",
                    "enabled": False
                }
            
            return health_info
            
        except Exception as e:
            self.structured_logger.log_error(
                error_type="health_check_error",
                component="container",
                message=f"Container health check failed: {str(e)}"
            )
            
            return {
                "service": "rlaas_container",
                "status": "unhealthy",
                "error": str(e),
                "timestamp": None
            }
    
    async def shutdown(self):
        """
        Gracefully shutdown all services
        """
        try:
            self.structured_logger.log_startup_event(
                startup_event="container_shutdown_start",
                component="container",
                success=True
            )
            
            # Shutdown Redis client manager
            if self.redis_client_manager:
                await self.redis_client_manager.close()
            
            # Reset metrics if needed
            if self.config.metrics.enabled:
                self.metrics_service.reset_metrics()
            
            self.structured_logger.log_startup_event(
                startup_event="container_shutdown_complete",
                component="container",
                success=True
            )
            
        except Exception as e:
            self.structured_logger.log_startup_event(
                startup_event="container_shutdown_failed",
                component="container",
                success=False,
                details={"error": str(e)}
            )
            
            self.structured_logger.log_error(
                error_type="shutdown_error",
                component="container",
                message=f"Container shutdown failed: {str(e)}"
            )


# Global container instance
_container: Optional[ServiceContainer] = None


async def get_container(config: Optional[RLaaSConfig] = None) -> ServiceContainer:
    """
    Get or create the global service container
    
    Args:
        config: Optional configuration (uses default if not provided)
        
    Returns:
        Service container instance
    """
    global _container
    
    if _container is None:
        if config is None:
            from .config import get_config
            config = get_config()
        
        _container = await ServiceContainer.create(config)
    
    return _container


async def shutdown_container():
    """Shutdown the global service container"""
    global _container
    
    if _container is not None:
        await _container.shutdown()
        _container = None


def set_container(container: ServiceContainer):
    """Set the global container (for testing)"""
    global _container
    _container = container