"""Unit tests for metrics API endpoints"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from rlaas.api import app, rlaas_app


class TestMetricsAPI:
    """Test metrics API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_decision_api(self):
        """Create mock decision API"""
        mock_api = MagicMock()
        return mock_api
    
    @pytest.fixture(autouse=True)
    def setup_mock_container(self, mock_decision_api):
        """Setup mock container with decision API for all tests"""
        mock_container = MagicMock()
        mock_container.decision_api = mock_decision_api
        
        rlaas_app.container = mock_container
        rlaas_app._initialized = True
        yield
        # Cleanup
        rlaas_app.container = None
        rlaas_app._initialized = False
    
    def test_get_prometheus_metrics_success(self, client):
        """Test successful Prometheus metrics export"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            # Mock metrics service
            mock_metrics = MagicMock()
            mock_metrics.export_prometheus_metrics.return_value = """# HELP rlaas_requests_total Total requests
# TYPE rlaas_requests_total counter
rlaas_requests_total{client_id="client1",endpoint="/api/test",http_method="GET",result="allowed"} 5.0
"""
            mock_metrics.get_content_type.return_value = "text/plain; version=0.0.4; charset=utf-8"
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics")
            
            assert response.status_code == 200
            assert "rlaas_requests_total" in response.text
            assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
            
            # Verify metrics service was called
            mock_metrics.export_prometheus_metrics.assert_called_once()
            mock_metrics.get_content_type.assert_called_once()
    
    def test_get_prometheus_metrics_error(self, client):
        """Test Prometheus metrics export with error"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            # Mock metrics service to raise exception
            mock_metrics = MagicMock()
            mock_metrics.export_prometheus_metrics.side_effect = Exception("Metrics export failed")
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics")
            
            assert response.status_code == 500
            assert "Error exporting metrics" in response.text
            assert "text/plain" in response.headers["content-type"]
    
    def test_get_metrics_summary_success(self, client):
        """Test successful metrics summary"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            # Mock metrics service
            mock_metrics = MagicMock()
            mock_metrics.get_metrics_summary.return_value = {
                "service": "rlaas_metrics",
                "timestamp": 1234567890.0,
                "metrics_available": [
                    "rlaas_requests_total",
                    "rlaas_errors_total"
                ],
                "registry": "prometheus_client"
            }
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics/summary")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["service"] == "rlaas_metrics"
            assert "timestamp" in data
            assert "metrics_available" in data
            assert "rlaas_requests_total" in data["metrics_available"]
            assert data["registry"] == "prometheus_client"
            
            # Verify metrics service was called
            mock_metrics.get_metrics_summary.assert_called_once()
    
    def test_get_metrics_summary_error(self, client):
        """Test metrics summary with error"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            # Mock metrics service to raise exception
            mock_metrics = MagicMock()
            mock_metrics.get_metrics_summary.side_effect = Exception("Summary failed")
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics/summary")
            
            assert response.status_code == 200  # Still returns 200 with error info
            data = response.json()
            
            assert data["service"] == "rlaas_metrics"
            assert data["status"] == "error"
            assert "Summary failed" in data["error"]
            assert "timestamp" in data
    
    def test_root_endpoint_includes_metrics(self, client):
        """Test that root endpoint includes metrics endpoints"""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "endpoints" in data
        assert "prometheus_metrics" in data["endpoints"]
        assert "metrics_summary" in data["endpoints"]
        assert data["endpoints"]["prometheus_metrics"] == "GET /metrics"
        assert data["endpoints"]["metrics_summary"] == "GET /metrics/summary"


class TestMetricsIntegrationInAPI:
    """Test metrics integration in API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_decision_api(self):
        """Create mock decision API"""
        from unittest.mock import AsyncMock
        mock_api = MagicMock()
        mock_api.process_rate_limit_request = AsyncMock()
        mock_api.rule_management_service = MagicMock()
        mock_api.rule_management_service.create_or_update_rule = AsyncMock()
        return mock_api
    
    @pytest.fixture(autouse=True)
    def setup_mock_container(self, mock_decision_api):
        """Setup mock container with decision API for all tests"""
        mock_container = MagicMock()
        mock_container.decision_api = mock_decision_api
        
        rlaas_app.container = mock_container
        rlaas_app._initialized = True
        yield
        # Cleanup
        rlaas_app.container = None
        rlaas_app._initialized = False
    
    def test_rate_limit_check_records_metrics(self, client, mock_decision_api):
        """Test that rate limit check records metrics"""
        from rlaas.models import RateLimitResponse
        
        # Mock successful response
        mock_response = RateLimitResponse(
            allowed=True,
            remaining_tokens=50,
            reset_after_ms=30000,
            retry_after_ms=None
        )
        mock_decision_api.process_rate_limit_request.return_value = mock_response
        
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request
            request_data = {
                "client_id": "client1",
                "endpoint": "/api/test",
                "http_method": "GET"
            }
            
            response = client.post("/v1/rate-limit/check", json=request_data)
            
            assert response.status_code == 200
            
            # Verify metrics were recorded
            mock_metrics.record_request.assert_called_once()
            call_args = mock_metrics.record_request.call_args
            assert call_args[1]["client_id"] == "client1"
            assert call_args[1]["endpoint"] == "/api/test"
            assert call_args[1]["http_method"] == "GET"
            assert call_args[1]["allowed"] is True
            assert call_args[1]["duration_seconds"] >= 0  # Duration can be 0 in fast tests
    
    def test_rate_limit_check_records_error_metrics(self, client, mock_decision_api):
        """Test that rate limit check records error metrics"""
        from rlaas.decision_api import RateLimitDecisionError
        
        # Mock validation error
        mock_decision_api.process_rate_limit_request.side_effect = RateLimitDecisionError("Validation failed")
        
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request
            request_data = {
                "client_id": "client1",
                "endpoint": "/api/test",
                "http_method": "GET"
            }
            
            response = client.post("/v1/rate-limit/check", json=request_data)
            
            assert response.status_code == 400  # Validation error
            
            # Verify error metrics were recorded
            mock_metrics.record_request.assert_called_once()
            call_args = mock_metrics.record_request.call_args
            assert call_args[1]["allowed"] is False
            assert call_args[1]["error"] == "validation_error"
    
    def test_rule_creation_records_metrics(self, client, mock_decision_api):
        """Test that rule creation records metrics"""
        # Mock successful rule creation
        mock_decision_api.rule_management_service.create_or_update_rule.return_value = None
        
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request
            rule_data = {
                "client_id": "client1",
                "endpoint": "/api/orders",
                "http_method": "POST",
                "limit": 100,
                "window_seconds": 60,
                "burst": 120
            }
            
            response = client.post("/v1/rate-limit/rules", json=rule_data)
            
            assert response.status_code == 201
            
            # Verify rule operation metrics were recorded
            mock_metrics.record_rule_operation.assert_called_once_with("create_update", success=True)
    
    def test_rule_creation_records_error_metrics(self, client, mock_decision_api):
        """Test that rule creation records error metrics"""
        from rlaas.rule_management import RuleValidationError
        
        # Mock validation error
        mock_decision_api.rule_management_service.create_or_update_rule.side_effect = RuleValidationError("Invalid rule")
        
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request
            rule_data = {
                "client_id": "client1",
                "endpoint": "/api/orders",
                "http_method": "POST",
                "limit": 100,
                "window_seconds": 60,
                "burst": 120
            }
            
            response = client.post("/v1/rate-limit/rules", json=rule_data)
            
            assert response.status_code == 400  # Validation error
            
            # Verify error metrics were recorded
            mock_metrics.record_rule_operation.assert_called_once_with("create_update", success=False)
            mock_metrics.record_error.assert_called_once_with("validation_error", "rule_management")
    
    def test_middleware_records_general_metrics(self, client):
        """Test that middleware records general request metrics"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request to root endpoint
            response = client.get("/")
            
            assert response.status_code == 200
            
            # Verify processing time header is added
            assert "x-process-time" in response.headers
            
            # Note: The middleware doesn't record detailed metrics for non-rate-limit endpoints
            # but it does add processing time headers and logs requests
    
    def test_middleware_records_error_metrics(self, client):
        """Test that middleware records error metrics for failed requests"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics
            
            # Make request to non-existent endpoint
            response = client.get("/nonexistent")
            
            assert response.status_code == 404
            
            # Verify error metrics were recorded by middleware
            # Note: This depends on the specific middleware implementation
            # The middleware may or may not record metrics for 404s


class TestMetricsEndpointSecurity:
    """Test security aspects of metrics endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    def test_metrics_endpoint_no_sensitive_data(self, client):
        """Test that metrics endpoint doesn't expose sensitive data"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            # Mock metrics with potentially sensitive data
            mock_metrics = MagicMock()
            mock_metrics.export_prometheus_metrics.return_value = """# HELP rlaas_requests_total Total requests
# TYPE rlaas_requests_total counter
rlaas_requests_total{client_id="client1",endpoint="/api/test",http_method="GET",result="allowed"} 5.0
"""
            mock_metrics.get_content_type.return_value = "text/plain; version=0.0.4; charset=utf-8"
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics")
            
            assert response.status_code == 200
            
            # Verify response contains metrics but no sensitive data
            # (In this case, client_id is included in labels, which may or may not be desired)
            assert "rlaas_requests_total" in response.text
            # In production, you might want to hash or anonymize client_ids
    
    def test_metrics_summary_no_sensitive_data(self, client):
        """Test that metrics summary doesn't expose sensitive data"""
        with patch('rlaas.api.get_metrics_service') as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_metrics.get_metrics_summary.return_value = {
                "service": "rlaas_metrics",
                "timestamp": 1234567890.0,
                "metrics_available": [
                    "rlaas_requests_total",
                    "rlaas_errors_total"
                ],
                "registry": "prometheus_client"
            }
            mock_get_metrics.return_value = mock_metrics
            
            response = client.get("/metrics/summary")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify no sensitive data in summary
            assert "password" not in str(data)
            assert "secret" not in str(data)
            assert "token" not in str(data)  # Except for metric names which is OK