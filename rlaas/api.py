"""FastAPI application for RLaaS rate limiting service"""

import time
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import structlog

from .models import RateLimitCheckRequest, RateLimitResponse, RateLimitRule
from .decision_api import RateLimitDecisionAPI, RateLimitDecisionError
from .rule_management import RuleManagementService, RuleValidationError
from .redis_state import RedisStateManager
from .redis_client import RedisClientManager
from .token_bucket import TokenBucketService
from .circuit_breaker import CircuitBreakerConfig
from .metrics import get_metrics_service
from .logging_service import get_structured_logger
from .config import get_config
from .container import get_container, shutdown_container

logger = structlog.get_logger()


class RLaaSApp:
    """RLaaS FastAPI application wrapper"""
    
    def __init__(self):
        """Initialize RLaaS application"""
        self.app: FastAPI = None
        self.container = None
        self.config = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize all services and dependencies"""
        if self._initialized:
            return
        
        try:
            # Load configuration
            self.config = get_config()
            
            # Initialize service container with dependency injection
            self.container = await get_container(self.config)
            
            # Set decision API reference for backward compatibility
            self.decision_api = self.container.decision_api
            
            self._initialized = True
            
            logger.info("RLaaS application initialized successfully")
            
        except Exception as e:
            # Log failed initialization
            structured_logger = get_structured_logger()
            structured_logger.log_startup_event(
                startup_event="application_initialization_failed",
                component="api",
                success=False,
                details={"error": str(e)}
            )
            
            logger.error("Failed to initialize RLaaS application", error=str(e))
            raise
    
    async def shutdown(self):
        """Cleanup resources on shutdown"""
        try:
            structured_logger = get_structured_logger()
            structured_logger.log_startup_event(
                startup_event="application_shutdown",
                component="api",
                success=True
            )
            
            logger.info("Shutting down RLaaS application")
            
            # Shutdown container
            await shutdown_container()
            
            logger.info("RLaaS application shutdown complete")
            
        except Exception as e:
            logger.error("Error during RLaaS application shutdown", error=str(e))


# Global application instance
rlaas_app = RLaaSApp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager"""
    # Startup
    await rlaas_app.initialize()
    yield
    # Shutdown
    await rlaas_app.shutdown()


# Create FastAPI application
app = FastAPI(
    title="RLaaS - Rate Limiter as a Service",
    description="Distributed rate limiting service providing centralized ALLOW/BLOCK decisions",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS middleware at app creation time
try:
    config = get_config()
    if config.security.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.security.cors_origins,
            allow_credentials=True,
            allow_methods=config.security.cors_methods,
            allow_headers=config.security.cors_headers,
        )
except Exception:
    # If config loading fails, use default CORS settings for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def logging_and_metrics_middleware(request: Request, call_next):
    """Log all requests and responses, collect metrics"""
    start_time = time.time()
    metrics = get_metrics_service()
    structured_logger = get_structured_logger()
    
    # Generate correlation ID for request tracking
    correlation_id = structured_logger.set_correlation_id()
    
    # Extract endpoint for metrics (normalize path parameters)
    endpoint = request.url.path
    method = request.method
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    # Log request start
    logger.info(
        "Request received",
        method=method,
        url=str(request.url),
        client_ip=client_ip,
        correlation_id=correlation_id
    )
    
    try:
        response = await call_next(request)
        
        # Calculate processing time
        process_time = time.time() - start_time
        process_time_ms = round(process_time * 1000, 2)
        
        # Log structured API request
        structured_logger.log_api_request(
            method=method,
            path=endpoint,
            status_code=response.status_code,
            duration_ms=process_time_ms,
            client_ip=client_ip,
            user_agent=user_agent
        )
        
        # Log response
        logger.info(
            "Request completed",
            method=method,
            url=str(request.url),
            status_code=response.status_code,
            process_time_ms=process_time_ms,
            correlation_id=correlation_id
        )
        
        # Record metrics for rate limit check endpoint
        if endpoint == "/v1/rate-limit/check" and method == "POST":
            result = "success" if response.status_code < 400 else "error"
            metrics.request_duration_seconds.labels(
                endpoint=endpoint,
                result=result
            ).observe(process_time)
        
        # Add processing time and correlation ID headers
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response
        
    except Exception as e:
        # Calculate processing time for errors
        process_time = time.time() - start_time
        process_time_ms = round(process_time * 1000, 2)
        
        # Log structured error
        structured_logger.log_error(
            error_type="request_processing_error",
            component="api",
            message=str(e),
            error_details={
                "method": method,
                "path": endpoint,
                "client_ip": client_ip
            }
        )
        
        # Log error
        logger.error(
            "Request failed",
            method=method,
            url=str(request.url),
            error=str(e),
            process_time_ms=process_time_ms,
            correlation_id=correlation_id
        )
        
        # Record error metrics
        metrics.record_error("request_processing_error", "api")
        metrics.request_duration_seconds.labels(
            endpoint=endpoint,
            result="error"
        ).observe(process_time)
        
        raise
    finally:
        # Clear correlation ID
        structured_logger.clear_correlation_id()


@app.exception_handler(RuleValidationError)
async def rule_validation_error_handler(request: Request, exc: RuleValidationError):
    """Handle rule validation errors"""
    logger.warning(
        "Rule validation error",
        error=str(exc),
        method=request.method,
        url=str(request.url)
    )
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "rule_validation_error",
            "message": str(exc),
            "timestamp": time.time()
        }
    )


@app.exception_handler(RateLimitDecisionError)
async def rate_limit_decision_error_handler(request: Request, exc: RateLimitDecisionError):
    """Handle rate limit decision errors"""
    logger.warning(
        "Rate limit decision error",
        error=str(exc),
        method=request.method,
        url=str(request.url)
    )
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "rate_limit_decision_error",
            "message": str(exc),
            "timestamp": time.time()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(
        "Unhandled exception",
        error=str(exc),
        method=request.method,
        url=str(request.url)
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An internal error occurred",
            "timestamp": time.time()
        }
    )


@app.post(
    "/v1/rate-limit/check",
    response_model=RateLimitResponse,
    status_code=status.HTTP_200_OK,
    summary="Check rate limit for a request",
    description="Determine if a request should be allowed or blocked based on rate limiting rules"
)
async def check_rate_limit(request: RateLimitCheckRequest) -> RateLimitResponse:
    """
    Check rate limit for a request
    
    This endpoint evaluates whether a request should be allowed or blocked
    based on the configured rate limiting rules for the client, endpoint,
    and HTTP method combination.
    
    Args:
        request: Rate limit check request containing client_id, endpoint, and http_method
        
    Returns:
        RateLimitResponse: Decision result with remaining tokens or retry information
        
    Raises:
        HTTPException: If request validation fails or internal error occurs
    """
    start_time = time.time()
    metrics = get_metrics_service()
    structured_logger = get_structured_logger()
    
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Process rate limit request
        response = await rlaas_app.container.decision_api.process_rate_limit_request(request)
        
        # Calculate processing time
        duration = time.time() - start_time
        duration_ms = round(duration * 1000, 2)
        
        # Record detailed metrics
        metrics.record_request(
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=response.allowed,
            duration_seconds=duration
        )
        
        # Log structured rate limit decision
        structured_logger.log_rate_limit_decision(
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=response.allowed,
            remaining_tokens=response.remaining_tokens,
            retry_after_ms=response.retry_after_ms,
            reset_after_ms=response.reset_after_ms,
            duration_ms=duration_ms
        )
        
        # Log decision outcome (legacy format for compatibility)
        logger.info(
            "Rate limit decision",
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=response.allowed,
            remaining_tokens=response.remaining_tokens,
            retry_after_ms=response.retry_after_ms,
            reset_after_ms=response.reset_after_ms,
            duration_ms=duration_ms
        )
        
        return response
        
    except RateLimitDecisionError as e:
        # Record validation error metrics
        duration = time.time() - start_time
        duration_ms = round(duration * 1000, 2)
        
        metrics.record_request(
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=False,
            duration_seconds=duration,
            error="validation_error"
        )
        
        # Log structured error
        structured_logger.log_rate_limit_decision(
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=False,
            duration_ms=duration_ms,
            error=str(e)
        )
        
        # Re-raise to be handled by exception handler
        raise
    except Exception as e:
        # Record internal error metrics
        duration = time.time() - start_time
        duration_ms = round(duration * 1000, 2)
        
        metrics.record_request(
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            allowed=False,
            duration_seconds=duration,
            error="internal_error"
        )
        
        # Log structured error
        structured_logger.log_error(
            error_type="internal_error",
            component="rate_limit_check",
            message=str(e),
            error_details={
                "client_id": request.client_id,
                "endpoint": request.endpoint,
                "http_method": request.http_method,
                "duration_ms": duration_ms
            }
        )
        
        logger.error(
            "Rate limit check failed",
            error=str(e),
            client_id=request.client_id,
            endpoint=request.endpoint,
            http_method=request.http_method,
            duration_ms=duration_ms
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rate limit check failed"
        )


@app.post(
    "/v1/rate-limit/rules",
    status_code=status.HTTP_201_CREATED,
    summary="Create or update rate limiting rule",
    description="Create or update a rate limiting rule for a specific client, endpoint, and HTTP method"
)
async def create_or_update_rule(rule: RateLimitRule) -> Dict[str, Any]:
    """
    Create or update a rate limiting rule
    
    This endpoint allows creating or updating rate limiting rules for specific
    client, endpoint, and HTTP method combinations. Rules are applied immediately
    and affect all subsequent rate limit checks.
    
    Args:
        rule: Rate limiting rule configuration
        
    Returns:
        Dict containing the created/updated rule and operation status
        
    Raises:
        HTTPException: If rule validation fails or internal error occurs
    """
    start_time = time.time()
    metrics = get_metrics_service()
    structured_logger = get_structured_logger()
    
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Create or update the rule
        await rlaas_app.container.decision_api.rule_management_service.create_or_update_rule(rule)
        
        # Calculate processing time
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        # Record successful rule operation
        metrics.record_rule_operation("create_update", success=True)
        
        # Log structured rule operation
        structured_logger.log_rule_operation(
            operation="create_update",
            client_id=rule.client_id,
            endpoint=rule.endpoint,
            http_method=rule.http_method,
            success=True,
            rule_data={
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "burst": rule.burst,
                "refill_rate": rule.get_refill_rate()
            },
            duration_ms=duration_ms
        )
        
        # Log rule creation/update (legacy format for compatibility)
        logger.info(
            "Rate limiting rule created/updated",
            client_id=rule.client_id,
            endpoint=rule.endpoint,
            http_method=rule.http_method,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            burst=rule.burst,
            duration_ms=duration_ms
        )
        
        return {
            "message": "Rule created/updated successfully",
            "rule": {
                "client_id": rule.client_id,
                "endpoint": rule.endpoint,
                "http_method": rule.http_method,
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "burst": rule.burst,
                "refill_rate": rule.get_refill_rate()
            },
            "timestamp": time.time()
        }
        
    except RuleValidationError as e:
        # Calculate processing time
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        # Record validation error
        metrics.record_rule_operation("create_update", success=False)
        metrics.record_error("validation_error", "rule_management")
        
        # Log structured rule operation error
        structured_logger.log_rule_operation(
            operation="create_update",
            client_id=rule.client_id,
            endpoint=rule.endpoint,
            http_method=rule.http_method,
            success=False,
            error=str(e),
            duration_ms=duration_ms
        )
        
        # Re-raise to be handled by exception handler
        raise
    except Exception as e:
        # Calculate processing time
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        # Record internal error
        metrics.record_rule_operation("create_update", success=False)
        metrics.record_error("internal_error", "rule_management")
        
        # Log structured error
        structured_logger.log_error(
            error_type="internal_error",
            component="rule_management",
            message=str(e),
            error_details={
                "operation": "create_update",
                "client_id": rule.client_id,
                "endpoint": rule.endpoint,
                "http_method": rule.http_method,
                "duration_ms": duration_ms
            }
        )
        
        logger.error(
            "Failed to create/update rule",
            error=str(e),
            client_id=rule.client_id,
            endpoint=rule.endpoint,
            http_method=rule.http_method,
            duration_ms=duration_ms
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create/update rule"
        )


@app.get(
    "/v1/rate-limit/rules/{client_id}",
    status_code=status.HTTP_200_OK,
    summary="Get rate limiting rule",
    description="Retrieve a rate limiting rule for a specific client, endpoint, and HTTP method"
)
async def get_rule(
    client_id: str,
    endpoint: str,
    http_method: str,
    use_default_fallback: bool = True
) -> Dict[str, Any]:
    """
    Get a rate limiting rule
    
    Retrieves the rate limiting rule for a specific client, endpoint, and HTTP method.
    If no specific rule exists and use_default_fallback is True, returns the default rule.
    
    Args:
        client_id: Client identifier
        endpoint: API endpoint
        http_method: HTTP method
        use_default_fallback: Whether to fallback to default rule if specific rule not found
        
    Returns:
        Dict containing the rule information
        
    Raises:
        HTTPException: If rule not found or internal error occurs
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Get the rule
        rule = await rlaas_app.container.decision_api.rule_management_service.get_rule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            use_default_fallback=use_default_fallback
        )
        
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found"
            )
        
        # Determine if this is a default rule
        try:
            specific_rule = await rlaas_app.container.decision_api.rule_management_service.get_rule(
                client_id=client_id,
                endpoint=endpoint,
                http_method=http_method,
                use_default_fallback=False
            )
            is_default_rule = specific_rule is None
        except:
            is_default_rule = True
        
        return {
            "rule": {
                "client_id": rule.client_id,
                "endpoint": rule.endpoint,
                "http_method": rule.http_method,
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "burst": rule.burst,
                "refill_rate": rule.get_refill_rate()
            },
            "is_default_rule": is_default_rule,
            "timestamp": time.time()
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Failed to get rule",
            error=str(e),
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve rule"
        )


@app.delete(
    "/v1/rate-limit/rules/{client_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete rate limiting rule",
    description="Delete a specific rate limiting rule"
)
async def delete_rule(
    client_id: str,
    endpoint: str,
    http_method: str
) -> Dict[str, Any]:
    """
    Delete a rate limiting rule
    
    Deletes a specific rate limiting rule. After deletion, requests will fall back
    to the default rule if available.
    
    Args:
        client_id: Client identifier
        endpoint: API endpoint
        http_method: HTTP method
        
    Returns:
        Dict containing deletion confirmation
        
    Raises:
        HTTPException: If rule not found or internal error occurs
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Check if rule exists
        existing_rule = await rlaas_app.container.decision_api.rule_management_service.get_rule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            use_default_fallback=False
        )
        
        if existing_rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found"
            )
        
        # Delete the rule
        await rlaas_app.container.decision_api.rule_management_service.delete_rule(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        # Log rule deletion
        logger.info(
            "Rate limiting rule deleted",
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        return {
            "message": "Rule deleted successfully",
            "deleted_rule": {
                "client_id": client_id,
                "endpoint": endpoint,
                "http_method": http_method
            },
            "timestamp": time.time()
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Failed to delete rule",
            error=str(e),
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete rule"
        )


@app.get(
    "/v1/rate-limit/rules",
    status_code=status.HTTP_200_OK,
    summary="List all rate limiting rules",
    description="Retrieve all configured rate limiting rules"
)
async def list_rules(
    client_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    http_method: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List rate limiting rules
    
    Retrieves all configured rate limiting rules with optional filtering.
    Supports pagination through limit and offset parameters.
    
    Args:
        client_id: Optional client ID filter
        endpoint: Optional endpoint filter
        http_method: Optional HTTP method filter
        limit: Maximum number of rules to return (default: 100)
        offset: Number of rules to skip (default: 0)
        
    Returns:
        Dict containing list of rules and pagination info
        
    Raises:
        HTTPException: If internal error occurs
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Get all rules (this is a simplified implementation)
        # In a real system, you'd want proper pagination and filtering in the service layer
        all_rules = await rlaas_app.container.decision_api.rule_management_service.list_rules(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            limit=limit,
            offset=offset
        )
        
        # Format rules for response
        formatted_rules = []
        for rule in all_rules:
            formatted_rules.append({
                "client_id": rule.client_id,
                "endpoint": rule.endpoint,
                "http_method": rule.http_method,
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "burst": rule.burst,
                "refill_rate": rule.get_refill_rate()
            })
        
        return {
            "rules": formatted_rules,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": len(formatted_rules),
                "has_more": len(formatted_rules) == limit  # Simplified check
            },
            "filters": {
                "client_id": client_id,
                "endpoint": endpoint,
                "http_method": http_method
            },
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(
            "Failed to list rules",
            error=str(e),
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list rules"
        )


@app.get(
    "/metrics",
    status_code=status.HTTP_200_OK,
    summary="Prometheus metrics endpoint",
    description="Export metrics in Prometheus format for monitoring and alerting"
)
async def get_prometheus_metrics() -> Response:
    """
    Export metrics in Prometheus format
    
    Returns metrics in Prometheus exposition format for scraping by
    monitoring systems like Prometheus, Grafana, etc.
    
    Returns:
        Response with Prometheus-formatted metrics
    """
    try:
        metrics = get_metrics_service()
        
        # Export metrics in Prometheus format
        metrics_data = metrics.export_prometheus_metrics()
        
        return Response(
            content=metrics_data,
            media_type=metrics.get_content_type()
        )
        
    except Exception as e:
        logger.error("Failed to export Prometheus metrics", error=str(e))
        
        # Return error in Prometheus comment format
        error_response = f"# Error exporting metrics: {str(e)}\n"
        return Response(
            content=error_response,
            media_type="text/plain",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@app.get(
    "/metrics/summary",
    status_code=status.HTTP_200_OK,
    summary="Metrics summary",
    description="Get a summary of available metrics and current values"
)
async def get_metrics_summary() -> Dict[str, Any]:
    """
    Get metrics summary
    
    Returns a summary of available metrics, their descriptions,
    and current values in JSON format.
    
    Returns:
        Dict containing metrics summary
    """
    try:
        metrics = get_metrics_service()
        
        # Get metrics summary
        summary = metrics.get_metrics_summary()
        
        return summary
        
    except Exception as e:
        logger.error("Failed to get metrics summary", error=str(e))
        
        return {
            "service": "rlaas_metrics",
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
    description="Check the health status of the RLaaS service and its dependencies"
)
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint
    
    Returns the health status of the RLaaS service and all its dependencies
    including Redis connectivity, circuit breaker status, and component health.
    
    Returns:
        Dict containing health status information
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Perform comprehensive health check through container
        health_info = await rlaas_app.container.health_check()
        
        # Determine HTTP status code based on health
        if health_info.get("status") == "healthy":
            status_code = status.HTTP_200_OK
        elif health_info.get("status") == "degraded":
            status_code = status.HTTP_200_OK  # Still operational
        else:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=health_info
        )
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "service": "rlaas",
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }
        )


@app.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    summary="Service statistics",
    description="Get operational statistics for the RLaaS service"
)
async def get_stats() -> Dict[str, Any]:
    """
    Get service statistics
    
    Returns operational statistics including component status,
    circuit breaker information, and performance metrics.
    
    Returns:
        Dict containing service statistics
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Get service statistics
        stats = rlaas_app.container.decision_api.get_stats()
        
        return stats
        
    except Exception as e:
        logger.error("Failed to get stats", error=str(e))
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "stats_unavailable",
                "message": str(e),
                "timestamp": time.time()
            }
        )


@app.get(
    "/bucket-info/{client_id}",
    status_code=status.HTTP_200_OK,
    summary="Get bucket information",
    description="Get detailed information about a specific rate limiting bucket"
)
async def get_bucket_info(
    client_id: str,
    endpoint: str,
    http_method: str
) -> Dict[str, Any]:
    """
    Get detailed bucket information
    
    Returns detailed information about a rate limiting bucket including
    current token count, capacity utilization, and refill timing.
    
    Args:
        client_id: Client identifier
        endpoint: API endpoint
        http_method: HTTP method
        
    Returns:
        Dict containing bucket information or 404 if not found
    """
    try:
        # Ensure application is initialized
        if not rlaas_app._initialized:
            await rlaas_app.initialize()
        
        # Get bucket information
        bucket_info = await rlaas_app.container.decision_api.get_bucket_info(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        if bucket_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bucket not found"
            )
        
        return bucket_info
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Failed to get bucket info",
            error=str(e),
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve bucket information"
        )


@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Service information",
    description="Get basic information about the RLaaS service"
)
async def root() -> Dict[str, Any]:
    """
    Root endpoint with service information
    
    Returns basic information about the RLaaS service including
    version, description, and available endpoints.
    
    Returns:
        Dict containing service information
    """
    return {
        "service": "RLaaS - Rate Limiter as a Service",
        "version": "1.0.0",
        "description": "Distributed rate limiting service providing centralized ALLOW/BLOCK decisions",
        "endpoints": {
            "rate_limit_check": "POST /v1/rate-limit/check",
            "create_rule": "POST /v1/rate-limit/rules",
            "get_rule": "GET /v1/rate-limit/rules/{client_id}?endpoint=...&http_method=...",
            "delete_rule": "DELETE /v1/rate-limit/rules/{client_id}?endpoint=...&http_method=...",
            "list_rules": "GET /v1/rate-limit/rules",
            "health_check": "GET /health",
            "statistics": "GET /stats",
            "bucket_info": "GET /bucket-info/{client_id}?endpoint=...&http_method=...",
            "prometheus_metrics": "GET /metrics",
            "metrics_summary": "GET /metrics/summary"
        },
        "timestamp": time.time()
    }


# Export the FastAPI app for ASGI servers
__all__ = ["app"]