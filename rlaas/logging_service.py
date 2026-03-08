"""Enhanced structured logging service for RLaaS"""

import time
import uuid
from typing import Dict, Any, Optional
from contextvars import ContextVar
import structlog

# Context variable for request correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIDProcessor:
    """Processor to add correlation ID to all log entries"""
    
    def __call__(self, logger, method_name, event_dict):
        """Add correlation ID to log entry if available"""
        correlation_id = correlation_id_var.get()
        if correlation_id:
            event_dict['correlation_id'] = correlation_id
        return event_dict


class TimestampProcessor:
    """Processor to add consistent timestamps to log entries"""
    
    def __call__(self, logger, method_name, event_dict):
        """Add timestamp to log entry"""
        timestamp = time.time()
        event_dict['timestamp'] = timestamp
        # Format timestamp with microseconds manually since strftime doesn't support %f
        dt = time.gmtime(timestamp)
        microseconds = int((timestamp % 1) * 1000000)
        event_dict['timestamp_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S', dt) + f'.{microseconds:06d}Z'
        return event_dict


class ServiceContextProcessor:
    """Processor to add service context to log entries"""
    
    def __init__(self, service_name: str = "rlaas", version: str = "1.0.0"):
        self.service_name = service_name
        self.version = version
    
    def __call__(self, logger, method_name, event_dict):
        """Add service context to log entry"""
        event_dict['service'] = self.service_name
        event_dict['version'] = self.version
        event_dict['log_level'] = method_name.upper()
        return event_dict


def configure_structured_logging():
    """Configure structured logging for the application"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            CorrelationIDProcessor(),
            TimestampProcessor(),
            ServiceContextProcessor(),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(30),  # INFO level
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class StructuredLogger:
    """Enhanced structured logger for RLaaS with correlation IDs and standardized fields"""
    
    def __init__(self, name: str = "rlaas"):
        """
        Initialize structured logger
        
        Args:
            name: Logger name
        """
        self.logger = structlog.get_logger(name)
    
    def set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """
        Set correlation ID for request tracking
        
        Args:
            correlation_id: Optional correlation ID (generates one if not provided)
            
        Returns:
            The correlation ID that was set
        """
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        
        correlation_id_var.set(correlation_id)
        return correlation_id
    
    def get_correlation_id(self) -> Optional[str]:
        """
        Get current correlation ID
        
        Returns:
            Current correlation ID or None
        """
        return correlation_id_var.get()
    
    def clear_correlation_id(self):
        """Clear correlation ID"""
        correlation_id_var.set(None)
    
    def log_rate_limit_decision(
        self,
        client_id: str,
        endpoint: str,
        http_method: str,
        allowed: bool,
        remaining_tokens: Optional[int] = None,
        retry_after_ms: Optional[int] = None,
        reset_after_ms: Optional[int] = None,
        rule_applied: Optional[Dict[str, Any]] = None,
        used_default_rule: bool = False,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None
    ):
        """
        Log rate limit decision with all required fields
        
        Args:
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            allowed: Whether request was allowed
            remaining_tokens: Tokens remaining after decision
            retry_after_ms: Time to wait before retry (if blocked)
            reset_after_ms: Time until bucket refills (if allowed)
            rule_applied: Rule that was applied
            used_default_rule: Whether default rule was used
            duration_ms: Processing duration in milliseconds
            error: Error message if decision failed
        """
        log_data = {
            "event_type": "rate_limit_decision",
            "client_id": client_id,
            "endpoint": endpoint,
            "http_method": http_method,
            "result": "allowed" if allowed else "blocked",
            "allowed": allowed,
            "used_default_rule": used_default_rule
        }
        
        # Add optional fields
        if remaining_tokens is not None:
            log_data["remaining_tokens"] = remaining_tokens
        if retry_after_ms is not None:
            log_data["retry_after_ms"] = retry_after_ms
        if reset_after_ms is not None:
            log_data["reset_after_ms"] = reset_after_ms
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        if error:
            log_data["error"] = error
        
        # Add rule information
        if rule_applied:
            log_data["rule"] = {
                "limit": rule_applied.get("limit"),
                "window_seconds": rule_applied.get("window_seconds"),
                "burst": rule_applied.get("burst")
            }
        
        # Log at appropriate level
        if error:
            self.logger.error("Rate limit decision failed", **log_data)
        elif allowed:
            self.logger.info("Rate limit decision: ALLOWED", **log_data)
        else:
            self.logger.info("Rate limit decision: BLOCKED", **log_data)
    
    def log_rule_operation(
        self,
        operation: str,
        client_id: str,
        endpoint: str,
        http_method: str,
        success: bool,
        rule_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None
    ):
        """
        Log rule management operation
        
        Args:
            operation: Type of operation (create, update, delete, get, list)
            client_id: Client identifier
            endpoint: API endpoint
            http_method: HTTP method
            success: Whether operation succeeded
            rule_data: Rule data involved in operation
            error: Error message if operation failed
            duration_ms: Processing duration in milliseconds
        """
        log_data = {
            "event_type": "rule_operation",
            "operation": operation,
            "client_id": client_id,
            "endpoint": endpoint,
            "http_method": http_method,
            "result": "success" if success else "error",
            "success": success
        }
        
        # Add optional fields
        if rule_data:
            log_data["rule"] = rule_data
        if error:
            log_data["error"] = error
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        
        # Log at appropriate level
        if error:
            self.logger.error(f"Rule operation failed: {operation}", **log_data)
        else:
            self.logger.info(f"Rule operation completed: {operation}", **log_data)
    
    def log_redis_operation(
        self,
        operation: str,
        success: bool,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        key: Optional[str] = None,
        result_size: Optional[int] = None
    ):
        """
        Log Redis operation
        
        Args:
            operation: Type of Redis operation
            success: Whether operation succeeded
            duration_ms: Operation duration in milliseconds
            error: Error message if operation failed
            key: Redis key involved (optional, for debugging)
            result_size: Size of result (optional)
        """
        log_data = {
            "event_type": "redis_operation",
            "operation": operation,
            "result": "success" if success else "error",
            "success": success
        }
        
        # Add optional fields
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        if error:
            log_data["error"] = error
        if key:
            log_data["redis_key"] = key
        if result_size is not None:
            log_data["result_size"] = result_size
        
        # Log at appropriate level
        if error:
            self.logger.error(f"Redis operation failed: {operation}", **log_data)
        else:
            self.logger.debug(f"Redis operation completed: {operation}", **log_data)
    
    def log_circuit_breaker_event(
        self,
        component: str,
        event: str,
        state: str,
        failure_count: Optional[int] = None,
        error: Optional[str] = None
    ):
        """
        Log circuit breaker event
        
        Args:
            component: Component name (e.g., 'redis')
            event: Event type (state_change, failure, recovery)
            state: Current circuit breaker state
            failure_count: Current failure count
            error: Error that triggered the event (if applicable)
        """
        log_data = {
            "event_type": "circuit_breaker_event",
            "component": component,
            "circuit_breaker_event": event,
            "state": state
        }
        
        # Add optional fields
        if failure_count is not None:
            log_data["failure_count"] = failure_count
        if error:
            log_data["error"] = error
        
        # Log at appropriate level
        if event == "failure" or error:
            self.logger.warning("Circuit breaker event occurred", **log_data)
        else:
            self.logger.info("Circuit breaker event occurred", **log_data)
    
    def log_api_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_size: Optional[int] = None,
        response_size: Optional[int] = None
    ):
        """
        Log API request
        
        Args:
            method: HTTP method
            path: Request path
            status_code: HTTP status code
            duration_ms: Request duration in milliseconds
            client_ip: Client IP address
            user_agent: User agent string
            request_size: Request body size in bytes
            response_size: Response body size in bytes
        """
        log_data = {
            "event_type": "api_request",
            "http_method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "result": "success" if status_code < 400 else "error"
        }
        
        # Add optional fields
        if client_ip:
            log_data["client_ip"] = client_ip
        if user_agent:
            log_data["user_agent"] = user_agent
        if request_size is not None:
            log_data["request_size"] = request_size
        if response_size is not None:
            log_data["response_size"] = response_size
        
        # Log at appropriate level based on status code
        if status_code >= 500:
            self.logger.error("API request completed with server error", **log_data)
        elif status_code >= 400:
            self.logger.warning("API request completed with client error", **log_data)
        else:
            self.logger.info("API request completed successfully", **log_data)
    
    def log_error(
        self,
        error_type: str,
        component: str,
        message: str,
        error_details: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None
    ):
        """
        Log error with standardized format
        
        Args:
            error_type: Type of error (validation_error, redis_timeout, etc.)
            component: Component where error occurred
            message: Error message
            error_details: Additional error details
            stack_trace: Stack trace if available
        """
        log_data = {
            "event_type": "error",
            "error_type": error_type,
            "component": component,
            "message": message
        }
        
        # Add optional fields
        if error_details:
            log_data["error_details"] = error_details
        if stack_trace:
            log_data["stack_trace"] = stack_trace
        
        self.logger.error("Error occurred", **log_data)
    
    def log_health_check(
        self,
        component: str,
        status: str,
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log health check result
        
        Args:
            component: Component being checked
            status: Health status (healthy, degraded, unhealthy)
            duration_ms: Health check duration
            details: Additional health check details
        """
        log_data = {
            "event_type": "health_check",
            "component": component,
            "status": status
        }
        
        # Add optional fields
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        if details:
            log_data["details"] = details
        
        # Log at appropriate level
        if status == "unhealthy":
            self.logger.error(f"Health check failed: {component}", **log_data)
        elif status == "degraded":
            self.logger.warning(f"Health check degraded: {component}", **log_data)
        else:
            self.logger.info(f"Health check passed: {component}", **log_data)
    
    def log_startup_event(
        self,
        startup_event: str,
        component: str,
        success: bool,
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Log application startup event
        
        Args:
            startup_event: Startup event (initialization, configuration, etc.)
            component: Component being started
            success: Whether startup succeeded
            duration_ms: Startup duration
            details: Additional startup details
        """
        log_data = {
            "event_type": "startup_event",
            "startup_event": startup_event,
            "component": component,
            "result": "success" if success else "error",
            "success": success
        }
        
        # Add optional fields
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        if details:
            log_data["details"] = details
        
        # Log at appropriate level
        if success:
            self.logger.info("Startup event completed", **log_data)
        else:
            self.logger.error("Startup event failed", **log_data)


# Global structured logger instance
_structured_logger = None


def get_structured_logger() -> StructuredLogger:
    """
    Get the global structured logger instance
    
    Returns:
        StructuredLogger instance
    """
    global _structured_logger
    if _structured_logger is None:
        configure_structured_logging()
        _structured_logger = StructuredLogger()
    return _structured_logger


def with_correlation_id(correlation_id: Optional[str] = None):
    """
    Decorator to set correlation ID for a function
    
    Args:
        correlation_id: Optional correlation ID (generates one if not provided)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_structured_logger()
            old_correlation_id = logger.get_correlation_id()
            
            # Set new correlation ID
            actual_correlation_id = logger.set_correlation_id(correlation_id)
            
            try:
                return func(*args, **kwargs)
            finally:
                # Restore previous correlation ID
                if old_correlation_id is not None:
                    logger.set_correlation_id(old_correlation_id)
                else:
                    logger.clear_correlation_id()
        
        return wrapper
    return decorator


def with_async_correlation_id(correlation_id: Optional[str] = None):
    """
    Async decorator to set correlation ID for an async function
    
    Args:
        correlation_id: Optional correlation ID (generates one if not provided)
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            logger = get_structured_logger()
            old_correlation_id = logger.get_correlation_id()
            
            # Set new correlation ID
            actual_correlation_id = logger.set_correlation_id(correlation_id)
            
            try:
                return await func(*args, **kwargs)
            finally:
                # Restore previous correlation ID
                if old_correlation_id is not None:
                    logger.set_correlation_id(old_correlation_id)
                else:
                    logger.clear_correlation_id()
        
        return wrapper
    return decorator