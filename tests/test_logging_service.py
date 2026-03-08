"""Unit tests for structured logging service"""

import pytest
import json
import uuid
from unittest.mock import patch, MagicMock
from io import StringIO

from rlaas.logging_service import (
    StructuredLogger,
    get_structured_logger,
    configure_structured_logging,
    with_correlation_id,
    with_async_correlation_id,
    correlation_id_var,
    CorrelationIDProcessor,
    TimestampProcessor,
    ServiceContextProcessor
)


class TestCorrelationIDProcessor:
    """Test correlation ID processor"""
    
    def test_processor_adds_correlation_id(self):
        """Test that processor adds correlation ID when available"""
        processor = CorrelationIDProcessor()
        
        # Set correlation ID
        correlation_id_var.set("test-correlation-id")
        
        event_dict = {"message": "test"}
        result = processor(None, "info", event_dict)
        
        assert result["correlation_id"] == "test-correlation-id"
        assert result["message"] == "test"
    
    def test_processor_no_correlation_id(self):
        """Test that processor doesn't add correlation ID when not available"""
        processor = CorrelationIDProcessor()
        
        # Clear correlation ID
        correlation_id_var.set(None)
        
        event_dict = {"message": "test"}
        result = processor(None, "info", event_dict)
        
        assert "correlation_id" not in result
        assert result["message"] == "test"


class TestTimestampProcessor:
    """Test timestamp processor"""
    
    def test_processor_adds_timestamps(self):
        """Test that processor adds timestamps"""
        processor = TimestampProcessor()
        
        event_dict = {"message": "test"}
        result = processor(None, "info", event_dict)
        
        assert "timestamp" in result
        assert "timestamp_iso" in result
        assert isinstance(result["timestamp"], float)
        assert isinstance(result["timestamp_iso"], str)
        assert result["message"] == "test"


class TestServiceContextProcessor:
    """Test service context processor"""
    
    def test_processor_adds_service_context(self):
        """Test that processor adds service context"""
        processor = ServiceContextProcessor("test-service", "2.0.0")
        
        event_dict = {"message": "test"}
        result = processor(None, "info", event_dict)
        
        assert result["service"] == "test-service"
        assert result["version"] == "2.0.0"
        assert result["log_level"] == "INFO"
        assert result["message"] == "test"
    
    def test_processor_default_values(self):
        """Test processor with default values"""
        processor = ServiceContextProcessor()
        
        event_dict = {"message": "test"}
        result = processor(None, "error", event_dict)
        
        assert result["service"] == "rlaas"
        assert result["version"] == "1.0.0"
        assert result["log_level"] == "ERROR"


class TestStructuredLogger:
    """Test StructuredLogger functionality"""
    
    @pytest.fixture
    def logger(self):
        """Create structured logger instance"""
        return StructuredLogger("test")
    
    def test_initialization(self, logger):
        """Test logger initialization"""
        assert logger.logger is not None
    
    def test_set_correlation_id_with_value(self, logger):
        """Test setting correlation ID with provided value"""
        correlation_id = "test-correlation-123"
        result = logger.set_correlation_id(correlation_id)
        
        assert result == correlation_id
        assert logger.get_correlation_id() == correlation_id
    
    def test_set_correlation_id_generate(self, logger):
        """Test setting correlation ID with generated value"""
        result = logger.set_correlation_id()
        
        assert result is not None
        assert len(result) > 0
        assert logger.get_correlation_id() == result
        
        # Should be a valid UUID
        uuid.UUID(result)  # Will raise exception if not valid UUID
    
    def test_get_correlation_id_none(self, logger):
        """Test getting correlation ID when none is set"""
        logger.clear_correlation_id()
        assert logger.get_correlation_id() is None
    
    def test_clear_correlation_id(self, logger):
        """Test clearing correlation ID"""
        logger.set_correlation_id("test-id")
        assert logger.get_correlation_id() == "test-id"
        
        logger.clear_correlation_id()
        assert logger.get_correlation_id() is None
    
    def test_log_rate_limit_decision_allowed(self, logger):
        """Test logging allowed rate limit decision"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_rate_limit_decision(
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                allowed=True,
                remaining_tokens=50,
                reset_after_ms=30000,
                duration_ms=25.5
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["event_type"] == "rate_limit_decision"
            assert call_args["client_id"] == "client1"
            assert call_args["endpoint"] == "/api/test"
            assert call_args["http_method"] == "GET"
            assert call_args["result"] == "allowed"
            assert call_args["allowed"] is True
            assert call_args["remaining_tokens"] == 50
            assert call_args["reset_after_ms"] == 30000
            assert call_args["duration_ms"] == 25.5
    
    def test_log_rate_limit_decision_blocked(self, logger):
        """Test logging blocked rate limit decision"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_rate_limit_decision(
                client_id="client2",
                endpoint="/api/orders",
                http_method="POST",
                allowed=False,
                retry_after_ms=5000,
                used_default_rule=True
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["result"] == "blocked"
            assert call_args["allowed"] is False
            assert call_args["retry_after_ms"] == 5000
            assert call_args["used_default_rule"] is True
    
    def test_log_rate_limit_decision_error(self, logger):
        """Test logging rate limit decision with error"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_rate_limit_decision(
                client_id="client3",
                endpoint="/api/users",
                http_method="DELETE",
                allowed=False,
                error="validation_error"
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["error"] == "validation_error"
            assert call_args["allowed"] is False
    
    def test_log_rule_operation_success(self, logger):
        """Test logging successful rule operation"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_rule_operation(
                operation="create",
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                success=True,
                rule_data={"limit": 100, "burst": 120},
                duration_ms=15.2
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["event_type"] == "rule_operation"
            assert call_args["operation"] == "create"
            assert call_args["result"] == "success"
            assert call_args["success"] is True
            assert call_args["rule"] == {"limit": 100, "burst": 120}
            assert call_args["duration_ms"] == 15.2
    
    def test_log_rule_operation_error(self, logger):
        """Test logging failed rule operation"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_rule_operation(
                operation="delete",
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                success=False,
                error="rule_not_found"
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["result"] == "error"
            assert call_args["success"] is False
            assert call_args["error"] == "rule_not_found"
    
    def test_log_redis_operation_success(self, logger):
        """Test logging successful Redis operation"""
        with patch.object(logger.logger, 'debug') as mock_debug:
            logger.log_redis_operation(
                operation="get",
                success=True,
                duration_ms=2.5,
                key="rate_limit:client1:/api/test:GET"
            )
            
            mock_debug.assert_called_once()
            call_args = mock_debug.call_args[1]
            
            assert call_args["event_type"] == "redis_operation"
            assert call_args["operation"] == "get"
            assert call_args["result"] == "success"
            assert call_args["duration_ms"] == 2.5
            assert call_args["redis_key"] == "rate_limit:client1:/api/test:GET"
    
    def test_log_redis_operation_error(self, logger):
        """Test logging failed Redis operation"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_redis_operation(
                operation="set",
                success=False,
                error="connection_timeout",
                duration_ms=100.0
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["result"] == "error"
            assert call_args["error"] == "connection_timeout"
            assert call_args["duration_ms"] == 100.0
    
    def test_log_circuit_breaker_event(self, logger):
        """Test logging circuit breaker event"""
        with patch.object(logger.logger, 'warning') as mock_warning:
            logger.log_circuit_breaker_event(
                component="redis",
                event="failure",
                state="open",
                failure_count=5,
                error="timeout"
            )
            
            mock_warning.assert_called_once()
            call_args = mock_warning.call_args[1]
            
            assert call_args["event_type"] == "circuit_breaker_event"
            assert call_args["component"] == "redis"
            assert call_args["circuit_breaker_event"] == "failure"
            assert call_args["state"] == "open"
            assert call_args["failure_count"] == 5
            assert call_args["error"] == "timeout"
    
    def test_log_api_request_success(self, logger):
        """Test logging successful API request"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_api_request(
                method="POST",
                path="/v1/rate-limit/check",
                status_code=200,
                duration_ms=25.5,
                client_ip="192.168.1.1",
                user_agent="test-agent"
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["event_type"] == "api_request"
            assert call_args["http_method"] == "POST"
            assert call_args["path"] == "/v1/rate-limit/check"
            assert call_args["status_code"] == 200
            assert call_args["result"] == "success"
            assert call_args["client_ip"] == "192.168.1.1"
            assert call_args["user_agent"] == "test-agent"
    
    def test_log_api_request_client_error(self, logger):
        """Test logging API request with client error"""
        with patch.object(logger.logger, 'warning') as mock_warning:
            logger.log_api_request(
                method="POST",
                path="/v1/rate-limit/check",
                status_code=400,
                duration_ms=10.0
            )
            
            mock_warning.assert_called_once()
            call_args = mock_warning.call_args[1]
            
            assert call_args["status_code"] == 400
            assert call_args["result"] == "error"
    
    def test_log_api_request_server_error(self, logger):
        """Test logging API request with server error"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_api_request(
                method="POST",
                path="/v1/rate-limit/check",
                status_code=500,
                duration_ms=50.0
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["status_code"] == 500
            assert call_args["result"] == "error"
    
    def test_log_error(self, logger):
        """Test logging error"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_error(
                error_type="validation_error",
                component="api",
                message="Invalid request",
                error_details={"field": "client_id", "value": ""},
                stack_trace="Traceback..."
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["event_type"] == "error"
            assert call_args["error_type"] == "validation_error"
            assert call_args["component"] == "api"
            assert call_args["message"] == "Invalid request"
            assert call_args["error_details"] == {"field": "client_id", "value": ""}
            assert call_args["stack_trace"] == "Traceback..."
    
    def test_log_health_check_healthy(self, logger):
        """Test logging healthy health check"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_health_check(
                component="redis",
                status="healthy",
                duration_ms=5.0,
                details={"connection": "ok"}
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["event_type"] == "health_check"
            assert call_args["component"] == "redis"
            assert call_args["status"] == "healthy"
            assert call_args["duration_ms"] == 5.0
            assert call_args["details"] == {"connection": "ok"}
    
    def test_log_health_check_unhealthy(self, logger):
        """Test logging unhealthy health check"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_health_check(
                component="redis",
                status="unhealthy"
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["status"] == "unhealthy"
    
    def test_log_startup_event_success(self, logger):
        """Test logging successful startup event"""
        with patch.object(logger.logger, 'info') as mock_info:
            logger.log_startup_event(
                startup_event="initialization",
                component="api",
                success=True,
                duration_ms=100.0,
                details={"port": 8000}
            )
            
            mock_info.assert_called_once()
            call_args = mock_info.call_args[1]
            
            assert call_args["event_type"] == "startup_event"
            assert call_args["startup_event"] == "initialization"
            assert call_args["component"] == "api"
            assert call_args["result"] == "success"
            assert call_args["success"] is True
            assert call_args["duration_ms"] == 100.0
            assert call_args["details"] == {"port": 8000}
    
    def test_log_startup_event_failure(self, logger):
        """Test logging failed startup event"""
        with patch.object(logger.logger, 'error') as mock_error:
            logger.log_startup_event(
                startup_event="redis_connection",
                component="redis",
                success=False
            )
            
            mock_error.assert_called_once()
            call_args = mock_error.call_args[1]
            
            assert call_args["result"] == "error"
            assert call_args["success"] is False


class TestGlobalStructuredLogger:
    """Test global structured logger functions"""
    
    def test_get_structured_logger(self):
        """Test getting global structured logger"""
        logger = get_structured_logger()
        
        assert isinstance(logger, StructuredLogger)
        
        # Should return the same instance
        logger2 = get_structured_logger()
        assert logger is logger2
    
    def test_configure_structured_logging(self):
        """Test configuring structured logging"""
        # This should not raise an exception
        configure_structured_logging()


class TestCorrelationIDDecorators:
    """Test correlation ID decorators"""
    
    def test_with_correlation_id_decorator(self):
        """Test correlation ID decorator"""
        logger = get_structured_logger()
        
        @with_correlation_id("test-correlation-id")
        def test_function():
            return logger.get_correlation_id()
        
        # Clear any existing correlation ID
        logger.clear_correlation_id()
        
        # Call decorated function
        result = test_function()
        
        assert result == "test-correlation-id"
        
        # Correlation ID should be cleared after function
        assert logger.get_correlation_id() is None
    
    def test_with_correlation_id_decorator_generate(self):
        """Test correlation ID decorator with generated ID"""
        logger = get_structured_logger()
        
        @with_correlation_id()
        def test_function():
            return logger.get_correlation_id()
        
        # Clear any existing correlation ID
        logger.clear_correlation_id()
        
        # Call decorated function
        result = test_function()
        
        assert result is not None
        assert len(result) > 0
        
        # Should be a valid UUID
        uuid.UUID(result)
    
    @pytest.mark.asyncio
    async def test_with_async_correlation_id_decorator(self):
        """Test async correlation ID decorator"""
        logger = get_structured_logger()
        
        @with_async_correlation_id("async-test-id")
        async def test_async_function():
            return logger.get_correlation_id()
        
        # Clear any existing correlation ID
        logger.clear_correlation_id()
        
        # Call decorated async function
        result = await test_async_function()
        
        assert result == "async-test-id"
        
        # Correlation ID should be cleared after function
        assert logger.get_correlation_id() is None
    
    def test_with_correlation_id_decorator_preserves_existing(self):
        """Test that decorator preserves existing correlation ID"""
        logger = get_structured_logger()
        
        # Set initial correlation ID
        logger.set_correlation_id("original-id")
        
        @with_correlation_id("temporary-id")
        def test_function():
            return logger.get_correlation_id()
        
        # Call decorated function
        result = test_function()
        
        assert result == "temporary-id"
        
        # Original correlation ID should be restored
        assert logger.get_correlation_id() == "original-id"


class TestStructuredLoggingIntegration:
    """Test structured logging integration scenarios"""
    
    def test_complete_request_flow_logging(self):
        """Test complete request flow with structured logging"""
        logger = get_structured_logger()
        
        # Set correlation ID
        correlation_id = logger.set_correlation_id()
        
        with patch.object(logger.logger, 'info') as mock_info, \
             patch.object(logger.logger, 'error') as mock_error:
            
            # Log API request
            logger.log_api_request(
                method="POST",
                path="/v1/rate-limit/check",
                status_code=200,
                duration_ms=25.0
            )
            
            # Log rate limit decision
            logger.log_rate_limit_decision(
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                allowed=True,
                remaining_tokens=50
            )
            
            # Log Redis operation
            logger.log_redis_operation(
                operation="lua_script",
                success=True,
                duration_ms=3.0
            )
            
            # Verify all logs were called
            assert mock_info.call_count >= 2  # API request and rate limit decision
    
    def test_error_scenario_logging(self):
        """Test error scenario with structured logging"""
        logger = get_structured_logger()
        
        with patch.object(logger.logger, 'error') as mock_error, \
             patch.object(logger.logger, 'warning') as mock_warning:
            
            # Log rate limit decision error
            logger.log_rate_limit_decision(
                client_id="client1",
                endpoint="/api/test",
                http_method="GET",
                allowed=False,
                error="redis_timeout"
            )
            
            # Log circuit breaker failure
            logger.log_circuit_breaker_event(
                component="redis",
                event="failure",
                state="open",
                error="timeout"
            )
            
            # Log general error
            logger.log_error(
                error_type="redis_timeout",
                component="redis",
                message="Connection timeout"
            )
            
            # Verify error logs were called (2 errors + 1 warning)
            assert mock_error.call_count >= 2
            assert mock_warning.call_count >= 1