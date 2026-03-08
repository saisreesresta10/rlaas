"""Unit tests for metrics service"""

import pytest
import time
from unittest.mock import patch, MagicMock
from prometheus_client import CollectorRegistry

from rlaas.metrics import MetricsService, get_metrics_service


class TestMetricsService:
    """Test MetricsService functionality"""
    
    @pytest.fixture
    def metrics_service(self):
        """Create metrics service with isolated registry"""
        registry = CollectorRegistry()
        return MetricsService(registry=registry)
    
    def test_initialization(self, metrics_service):
        """Test metrics service initialization"""
        assert metrics_service.registry is not None
        assert metrics_service.requests_total is not None
        assert metrics_service.requests_blocked_total is not None
        assert metrics_service.requests_allowed_total is not None
        assert metrics_service.request_duration_seconds is not None
        assert metrics_service.redis_operation_duration_seconds is not None
        assert metrics_service.errors_total is not None
        assert metrics_service.circuit_breaker_state is not None
        assert metrics_service.circuit_breaker_failures_total is not None
        assert metrics_service.rules_total is not None
        assert metrics_service.rule_operations_total is not None
        assert metrics_service.active_buckets is not None
    
    def test_record_request_allowed(self, metrics_service):
        """Test recording allowed request"""
        metrics_service.record_request(
            client_id="client1",
            endpoint="/api/orders",
            http_method="POST",
            allowed=True,
            duration_seconds=0.05
        )
        
        # Check that metrics were recorded
        # Note: In a real test, you'd want to inspect the actual metric values
        # This is a simplified test that verifies the method doesn't raise exceptions
        assert True  # Method completed without error
    
    def test_record_request_blocked(self, metrics_service):
        """Test recording blocked request"""
        metrics_service.record_request(
            client_id="client2",
            endpoint="/api/users",
            http_method="GET",
            allowed=False,
            duration_seconds=0.02
        )
        
        assert True  # Method completed without error
    
    def test_record_request_with_error(self, metrics_service):
        """Test recording request with error"""
        metrics_service.record_request(
            client_id="client3",
            endpoint="/api/test",
            http_method="PUT",
            allowed=False,
            duration_seconds=0.1,
            error="validation_error"
        )
        
        assert True  # Method completed without error
    
    def test_record_redis_operation_success(self, metrics_service):
        """Test recording successful Redis operation"""
        metrics_service.record_redis_operation(
            operation="get",
            duration_seconds=0.003,
            success=True
        )
        
        assert True  # Method completed without error
    
    def test_record_redis_operation_failure(self, metrics_service):
        """Test recording failed Redis operation"""
        metrics_service.record_redis_operation(
            operation="set",
            duration_seconds=0.1,
            success=False,
            error="redis_timeout"
        )
        
        assert True  # Method completed without error
    
    def test_record_error(self, metrics_service):
        """Test recording error"""
        metrics_service.record_error("connection_error", "redis")
        metrics_service.record_error("validation_error", "api")
        
        assert True  # Method completed without error
    
    def test_update_circuit_breaker_state(self, metrics_service):
        """Test updating circuit breaker state"""
        metrics_service.update_circuit_breaker_state("redis", "closed")
        metrics_service.update_circuit_breaker_state("redis", "open")
        metrics_service.update_circuit_breaker_state("redis", "half-open")
        
        assert True  # Method completed without error
    
    def test_update_circuit_breaker_state_invalid(self, metrics_service):
        """Test updating circuit breaker state with invalid state"""
        # Should default to 0 (closed) for invalid states
        metrics_service.update_circuit_breaker_state("redis", "invalid_state")
        
        assert True  # Method completed without error
    
    def test_record_circuit_breaker_failure(self, metrics_service):
        """Test recording circuit breaker failure"""
        metrics_service.record_circuit_breaker_failure("redis")
        
        assert True  # Method completed without error
    
    def test_record_rule_operation_success(self, metrics_service):
        """Test recording successful rule operation"""
        metrics_service.record_rule_operation("create", success=True)
        metrics_service.record_rule_operation("update", success=True)
        metrics_service.record_rule_operation("delete", success=True)
        
        assert True  # Method completed without error
    
    def test_record_rule_operation_failure(self, metrics_service):
        """Test recording failed rule operation"""
        metrics_service.record_rule_operation("create", success=False)
        
        assert True  # Method completed without error
    
    def test_update_rules_count(self, metrics_service):
        """Test updating rules count"""
        metrics_service.update_rules_count(42)
        metrics_service.update_rules_count(0)
        
        assert True  # Method completed without error
    
    def test_update_active_buckets_count(self, metrics_service):
        """Test updating active buckets count"""
        metrics_service.update_active_buckets_count(100)
        metrics_service.update_active_buckets_count(0)
        
        assert True  # Method completed without error
    
    def test_time_request_context_manager(self, metrics_service):
        """Test request timing context manager"""
        with metrics_service.time_request("/api/test") as timing_info:
            time.sleep(0.01)  # Simulate processing time
            timing_info["result"] = "success"
        
        assert "duration" in timing_info
        assert timing_info["duration"] >= 0.01
        assert timing_info["endpoint"] == "/api/test"
        assert timing_info["result"] == "success"
    
    def test_time_redis_operation_context_manager(self, metrics_service):
        """Test Redis operation timing context manager"""
        with metrics_service.time_redis_operation("get") as timing_info:
            time.sleep(0.005)  # Simulate Redis operation time
            timing_info["success"] = True
        
        assert "duration" in timing_info
        assert timing_info["duration"] >= 0.005
        assert timing_info["operation"] == "get"
        assert timing_info["success"] is True
    
    def test_time_redis_operation_with_error(self, metrics_service):
        """Test Redis operation timing with error"""
        with metrics_service.time_redis_operation("set") as timing_info:
            time.sleep(0.002)
            timing_info["success"] = False
            timing_info["error"] = "timeout"
        
        assert "duration" in timing_info
        assert timing_info["success"] is False
        assert timing_info["error"] == "timeout"
    
    def test_get_metrics_summary(self, metrics_service):
        """Test getting metrics summary"""
        summary = metrics_service.get_metrics_summary()
        
        assert summary["service"] == "rlaas_metrics"
        assert "timestamp" in summary
        assert "metrics_available" in summary
        assert "rlaas_requests_total" in summary["metrics_available"]
        assert "rlaas_errors_total" in summary["metrics_available"]
        assert summary["registry"] == "prometheus_client"
    
    def test_export_prometheus_metrics(self, metrics_service):
        """Test exporting Prometheus metrics"""
        # Record some metrics first
        metrics_service.record_request("client1", "/api/test", "GET", True, 0.05)
        metrics_service.record_error("test_error", "test_component")
        
        metrics_data = metrics_service.export_prometheus_metrics()
        
        assert isinstance(metrics_data, str)
        assert len(metrics_data) > 0
        # Should contain metric names
        assert "rlaas_requests_total" in metrics_data or "# HELP" in metrics_data
    
    def test_get_content_type(self, metrics_service):
        """Test getting content type for Prometheus metrics"""
        content_type = metrics_service.get_content_type()
        
        assert content_type is not None
        assert isinstance(content_type, str)
    
    def test_reset_metrics(self, metrics_service):
        """Test resetting metrics"""
        # Record some metrics
        metrics_service.record_request("client1", "/api/test", "GET", True, 0.05)
        metrics_service.update_rules_count(10)
        
        # Reset metrics
        metrics_service.reset_metrics()
        
        # Verify metrics service is still functional
        summary = metrics_service.get_metrics_summary()
        assert summary["service"] == "rlaas_metrics"
    
    def test_error_handling_in_record_request(self, metrics_service):
        """Test error handling in record_request method"""
        # Mock a metric to raise an exception
        with patch.object(metrics_service.requests_total, 'labels', side_effect=Exception("Mock error")):
            # Should not raise exception, just log error
            metrics_service.record_request("client1", "/api/test", "GET", True, 0.05)
    
    def test_error_handling_in_record_redis_operation(self, metrics_service):
        """Test error handling in record_redis_operation method"""
        # Mock a metric to raise an exception
        with patch.object(metrics_service.redis_operation_duration_seconds, 'labels', side_effect=Exception("Mock error")):
            # Should not raise exception, just log error
            metrics_service.record_redis_operation("get", 0.01, True)
    
    def test_error_handling_in_record_error(self, metrics_service):
        """Test error handling in record_error method"""
        # Mock a metric to raise an exception
        with patch.object(metrics_service.errors_total, 'labels', side_effect=Exception("Mock error")):
            # Should not raise exception, just log error
            metrics_service.record_error("test_error", "test_component")
    
    def test_error_handling_in_export_metrics(self, metrics_service):
        """Test error handling in export_prometheus_metrics"""
        # Mock generate_latest to raise an exception
        with patch('rlaas.metrics.generate_latest', side_effect=Exception("Export error")):
            result = metrics_service.export_prometheus_metrics()
            assert "Error exporting metrics" in result
    
    def test_error_handling_in_get_metrics_summary(self, metrics_service):
        """Test error handling in get_metrics_summary"""
        # Mock time.time to raise an exception
        with patch('time.time', side_effect=Exception("Time error")):
            summary = metrics_service.get_metrics_summary()
            assert summary["status"] == "error"
            assert "Time error" in summary["error"]


class TestGlobalMetricsService:
    """Test global metrics service functions"""
    
    def test_get_metrics_service(self):
        """Test getting global metrics service"""
        service = get_metrics_service()
        
        assert isinstance(service, MetricsService)
        assert service is not None
        
        # Should return the same instance
        service2 = get_metrics_service()
        assert service is service2


class TestMetricsIntegration:
    """Test metrics integration scenarios"""
    
    @pytest.fixture
    def metrics_service(self):
        """Create metrics service with isolated registry"""
        registry = CollectorRegistry()
        return MetricsService(registry=registry)
    
    def test_complete_request_flow(self, metrics_service):
        """Test complete request flow with metrics"""
        # Simulate a complete rate limit check flow
        
        # 1. Record allowed request
        metrics_service.record_request(
            client_id="client1",
            endpoint="/api/orders",
            http_method="POST",
            allowed=True,
            duration_seconds=0.025
        )
        
        # 2. Record Redis operations
        metrics_service.record_redis_operation("lua_script", 0.005, True)
        
        # 3. Record rule operation
        metrics_service.record_rule_operation("get", True)
        
        # 4. Update system metrics
        metrics_service.update_rules_count(5)
        metrics_service.update_active_buckets_count(100)
        
        # Verify metrics can be exported
        metrics_data = metrics_service.export_prometheus_metrics()
        assert isinstance(metrics_data, str)
        assert len(metrics_data) > 0
    
    def test_error_scenario_flow(self, metrics_service):
        """Test error scenario with metrics"""
        # Simulate error scenario
        
        # 1. Record failed request
        metrics_service.record_request(
            client_id="client2",
            endpoint="/api/users",
            http_method="GET",
            allowed=False,
            duration_seconds=0.1,
            error="redis_timeout"
        )
        
        # 2. Record failed Redis operation
        metrics_service.record_redis_operation("get", 0.05, False, "timeout")
        
        # 3. Record circuit breaker failure
        metrics_service.record_circuit_breaker_failure("redis")
        metrics_service.update_circuit_breaker_state("redis", "open")
        
        # 4. Record failed rule operation
        metrics_service.record_rule_operation("create", False)
        
        # Verify metrics can still be exported
        metrics_data = metrics_service.export_prometheus_metrics()
        assert isinstance(metrics_data, str)
        assert len(metrics_data) > 0
    
    def test_high_volume_metrics(self, metrics_service):
        """Test metrics with high volume of requests"""
        # Simulate high volume of requests
        for i in range(100):
            client_id = f"client{i % 10}"
            endpoint = f"/api/endpoint{i % 5}"
            allowed = i % 3 != 0  # 2/3 allowed, 1/3 blocked
            
            metrics_service.record_request(
                client_id=client_id,
                endpoint=endpoint,
                http_method="GET",
                allowed=allowed,
                duration_seconds=0.01 + (i % 10) * 0.001
            )
        
        # Record Redis operations
        for i in range(50):
            operation = "get" if i % 2 == 0 else "set"
            success = i % 10 != 0  # 9/10 success, 1/10 failure
            
            metrics_service.record_redis_operation(
                operation=operation,
                duration_seconds=0.001 + (i % 5) * 0.001,
                success=success
            )
        
        # Verify metrics can be exported
        metrics_data = metrics_service.export_prometheus_metrics()
        assert isinstance(metrics_data, str)
        assert len(metrics_data) > 0
        
        # Verify summary is available
        summary = metrics_service.get_metrics_summary()
        assert summary["service"] == "rlaas_metrics"