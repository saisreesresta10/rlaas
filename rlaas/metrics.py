"""Metrics collection and emission service for RLaaS"""

import time
from typing import Dict, Any, Optional
from contextlib import contextmanager
import structlog

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

logger = structlog.get_logger()


class MetricsService:
    """
    Service for collecting and emitting Prometheus-compatible metrics
    
    Tracks:
    - Total requests processed
    - Blocked vs allowed requests
    - Request processing latency
    - Redis operation latency
    - Error rates by type
    - Circuit breaker statistics
    """
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        Initialize metrics service
        
        Args:
            registry: Optional Prometheus registry (defaults to default registry)
        """
        self.registry = registry or CollectorRegistry()
        
        # Request metrics
        self.requests_total = Counter(
            'rlaas_requests_total',
            'Total number of rate limit check requests',
            ['client_id', 'endpoint', 'http_method', 'result'],
            registry=self.registry
        )
        
        self.requests_blocked_total = Counter(
            'rlaas_requests_blocked_total',
            'Total number of blocked requests',
            ['client_id', 'endpoint', 'http_method'],
            registry=self.registry
        )
        
        self.requests_allowed_total = Counter(
            'rlaas_requests_allowed_total',
            'Total number of allowed requests',
            ['client_id', 'endpoint', 'http_method'],
            registry=self.registry
        )
        
        # Latency metrics
        self.request_duration_seconds = Histogram(
            'rlaas_request_duration_seconds',
            'Request processing duration in seconds',
            ['endpoint', 'result'],
            registry=self.registry,
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
        )
        
        self.redis_operation_duration_seconds = Histogram(
            'rlaas_redis_operation_duration_seconds',
            'Redis operation duration in seconds',
            ['operation', 'result'],
            registry=self.registry,
            buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
        )
        
        # Error metrics
        self.errors_total = Counter(
            'rlaas_errors_total',
            'Total number of errors',
            ['error_type', 'component'],
            registry=self.registry
        )
        
        # Circuit breaker metrics
        self.circuit_breaker_state = Gauge(
            'rlaas_circuit_breaker_state',
            'Circuit breaker state (0=closed, 1=open, 2=half-open)',
            ['component'],
            registry=self.registry
        )
        
        self.circuit_breaker_failures_total = Counter(
            'rlaas_circuit_breaker_failures_total',
            'Total circuit breaker failures',
            ['component'],
            registry=self.registry
        )
        
        # Rule management metrics
        self.rules_total = Gauge(
            'rlaas_rules_total',
            'Total number of configured rules',
            registry=self.registry
        )
        
        self.rule_operations_total = Counter(
            'rlaas_rule_operations_total',
            'Total rule management operations',
            ['operation', 'result'],
            registry=self.registry
        )
        
        # System metrics
        self.active_buckets = Gauge(
            'rlaas_active_buckets_total',
            'Number of active token buckets',
            registry=self.registry
        )
        
        logger.info("Metrics service initialized")
    
    def record_request(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        allowed: bool,
        duration_seconds: float,
        error: Optional[str] = None
    ) -> None:
        """
        Record a rate limit request
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            allowed: Whether request was allowed
            duration_seconds: Request processing duration
            error: Optional error type if request failed
        """
        try:
            # Determine result
            if error:
                result = "error"
            elif allowed:
                result = "allowed"
            else:
                result = "blocked"
            
            # Record total requests
            self.requests_total.labels(
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                result=result
            ).inc()
            
            # Record specific result counters
            if allowed and not error:
                self.requests_allowed_total.labels(
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                ).inc()
            elif not allowed and not error:
                self.requests_blocked_total.labels(
                    client_id=client_id,
                    endpoint=endpoint,
                    http_method=http_method
                ).inc()
            
            # Record request duration
            self.request_duration_seconds.labels(
                endpoint=endpoint,
                result=result
            ).observe(duration_seconds)
            
            # Record error if present
            if error:
                self.record_error(error, "rate_limit_check")
            
            logger.debug(
                "Recorded request metrics",
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                result=result,
                duration_seconds=duration_seconds
            )
            
        except Exception as e:
            logger.error("Failed to record request metrics", error=str(e))
    
    def record_redis_operation(
        self,
        operation: str,
        duration_seconds: float,
        success: bool = True,
        error: Optional[str] = None
    ) -> None:
        """
        Record a Redis operation
        
        Args:
            operation: Type of Redis operation (e.g., 'get', 'set', 'lua_script')
            duration_seconds: Operation duration
            success: Whether operation succeeded
            error: Optional error type if operation failed
        """
        try:
            result = "success" if success else "error"
            
            # Record Redis operation duration
            self.redis_operation_duration_seconds.labels(
                operation=operation,
                result=result
            ).observe(duration_seconds)
            
            # Record error if present
            if error:
                self.record_error(error, "redis")
            
            logger.debug(
                "Recorded Redis operation metrics",
                operation=operation,
                result=result,
                duration_seconds=duration_seconds
            )
            
        except Exception as e:
            logger.error("Failed to record Redis operation metrics", error=str(e))
    
    def record_error(self, error_type: str, component: str) -> None:
        """
        Record an error occurrence
        
        Args:
            error_type: Type of error (e.g., 'validation_error', 'redis_timeout')
            component: Component where error occurred
        """
        try:
            self.errors_total.labels(
                error_type=error_type,
                component=component
            ).inc()
            
            logger.debug(
                "Recorded error metrics",
                error_type=error_type,
                component=component
            )
            
        except Exception as e:
            logger.error("Failed to record error metrics", error=str(e))
    
    def update_circuit_breaker_state(self, component: str, state: str) -> None:
        """
        Update circuit breaker state
        
        Args:
            component: Component name (e.g., 'redis')
            state: Circuit breaker state ('closed', 'open', 'half-open')
        """
        try:
            state_value = {
                'closed': 0,
                'open': 1,
                'half-open': 2
            }.get(state, 0)
            
            self.circuit_breaker_state.labels(component=component).set(state_value)
            
            logger.debug(
                "Updated circuit breaker state metrics",
                component=component,
                state=state,
                state_value=state_value
            )
            
        except Exception as e:
            logger.error("Failed to update circuit breaker state metrics", error=str(e))
    
    def record_circuit_breaker_failure(self, component: str) -> None:
        """
        Record a circuit breaker failure
        
        Args:
            component: Component name
        """
        try:
            self.circuit_breaker_failures_total.labels(component=component).inc()
            
            logger.debug(
                "Recorded circuit breaker failure",
                component=component
            )
            
        except Exception as e:
            logger.error("Failed to record circuit breaker failure metrics", error=str(e))
    
    def record_rule_operation(self, operation: str, success: bool = True) -> None:
        """
        Record a rule management operation
        
        Args:
            operation: Type of operation ('create', 'update', 'delete', 'get', 'list')
            success: Whether operation succeeded
        """
        try:
            result = "success" if success else "error"
            
            self.rule_operations_total.labels(
                operation=operation,
                result=result
            ).inc()
            
            logger.debug(
                "Recorded rule operation metrics",
                operation=operation,
                result=result
            )
            
        except Exception as e:
            logger.error("Failed to record rule operation metrics", error=str(e))
    
    def update_rules_count(self, count: int) -> None:
        """
        Update total number of configured rules
        
        Args:
            count: Number of rules
        """
        try:
            self.rules_total.set(count)
            
            logger.debug("Updated rules count metrics", count=count)
            
        except Exception as e:
            logger.error("Failed to update rules count metrics", error=str(e))
    
    def update_active_buckets_count(self, count: int) -> None:
        """
        Update number of active token buckets
        
        Args:
            count: Number of active buckets
        """
        try:
            self.active_buckets.set(count)
            
            logger.debug("Updated active buckets count metrics", count=count)
            
        except Exception as e:
            logger.error("Failed to update active buckets count metrics", error=str(e))
    
    @contextmanager
    def time_request(self, endpoint: str):
        """
        Context manager to time request processing
        
        Args:
            endpoint: API endpoint being timed
            
        Yields:
            Dict with timing information that will be populated
        """
        start_time = time.time()
        timing_info = {"start_time": start_time, "endpoint": endpoint}
        
        try:
            yield timing_info
        finally:
            duration = time.time() - start_time
            timing_info["duration"] = duration
            
            # Record duration if result is available
            if "result" in timing_info:
                self.request_duration_seconds.labels(
                    endpoint=endpoint,
                    result=timing_info["result"]
                ).observe(duration)
    
    @contextmanager
    def time_redis_operation(self, operation: str):
        """
        Context manager to time Redis operations
        
        Args:
            operation: Type of Redis operation
            
        Yields:
            Dict with timing information that will be populated
        """
        start_time = time.time()
        timing_info = {"start_time": start_time, "operation": operation}
        
        try:
            yield timing_info
        finally:
            duration = time.time() - start_time
            timing_info["duration"] = duration
            
            # Record the operation
            success = timing_info.get("success", True)
            error = timing_info.get("error")
            
            self.record_redis_operation(
                operation=operation,
                duration_seconds=duration,
                success=success,
                error=error
            )
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current metrics
        
        Returns:
            Dict containing metrics summary
        """
        try:
            # This is a simplified summary - in production you'd want to
            # collect actual values from the metrics
            return {
                "service": "rlaas_metrics",
                "timestamp": time.time(),
                "metrics_available": [
                    "rlaas_requests_total",
                    "rlaas_requests_blocked_total", 
                    "rlaas_requests_allowed_total",
                    "rlaas_request_duration_seconds",
                    "rlaas_redis_operation_duration_seconds",
                    "rlaas_errors_total",
                    "rlaas_circuit_breaker_state",
                    "rlaas_circuit_breaker_failures_total",
                    "rlaas_rules_total",
                    "rlaas_rule_operations_total",
                    "rlaas_active_buckets_total"
                ],
                "registry": "prometheus_client"
            }
            
        except Exception as e:
            logger.error("Failed to get metrics summary", error=str(e))
            return {
                "service": "rlaas_metrics",
                "status": "error",
                "error": str(e),
                "timestamp": 0.0  # Use fallback timestamp
            }
    
    def export_prometheus_metrics(self) -> str:
        """
        Export metrics in Prometheus format
        
        Returns:
            Prometheus-formatted metrics string
        """
        try:
            return generate_latest(self.registry).decode('utf-8')
        except Exception as e:
            logger.error("Failed to export Prometheus metrics", error=str(e))
            return f"# Error exporting metrics: {str(e)}\n"
    
    def get_content_type(self) -> str:
        """
        Get the content type for Prometheus metrics
        
        Returns:
            Content type string
        """
        return CONTENT_TYPE_LATEST
    
    def reset_metrics(self) -> None:
        """
        Reset all metrics (useful for testing)
        """
        try:
            # Clear the registry and recreate metrics
            self.registry._collector_to_names.clear()
            self.registry._names_to_collectors.clear()
            
            # Reinitialize metrics
            self.__init__(self.registry)
            
            logger.info("Metrics reset successfully")
            
        except Exception as e:
            logger.error("Failed to reset metrics", error=str(e))


# Global metrics service instance
metrics_service = MetricsService()


def get_metrics_service() -> MetricsService:
    """
    Get the global metrics service instance
    
    Returns:
        MetricsService instance
    """
    return metrics_service