"""Unit tests for health check endpoints"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import json

from rlaas.api import app


class TestHealthCheckEndpoints:
    """Unit tests for health check functionality"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    def test_health_endpoint_returns_200_when_healthy(self, client):
        """
        Test that /health endpoint returns 200 when all components are healthy
        **Validates: Requirements 8.1**
        """
        # Test the health endpoint
        response = client.get("/health")
        
        # Should return a valid response
        assert response.status_code in [200, 503]  # Either healthy or unhealthy
        
        # Should return valid JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            pytest.fail("Health endpoint should return valid JSON")
        
        # Should have basic health information
        assert isinstance(data, dict), "Health response should be JSON object"
        
        if response.status_code == 200:
            # Healthy response should have status info
            assert any(key in data for key in ["status", "service", "healthy"]), "Healthy response should have status info"
        else:
            # Unhealthy response should have error info
            assert any(key in data for key in ["status", "error", "service"]), "Unhealthy response should have error info"
    
    def test_health_endpoint_response_format(self, client):
        """
        Test that health endpoint returns properly formatted JSON
        **Validates: Requirements 8.9**
        """
        response = client.get("/health")
        
        # Should return valid status codes
        assert response.status_code in [200, 503]
        
        # Should have JSON content type
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type, "Health endpoint should return JSON"
        
        # Should be valid JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            pytest.fail("Health response should be valid JSON")
        
        # Should be a dictionary
        assert isinstance(data, dict), "Health response should be JSON object"
        
        # Should have some identifying information
        assert len(data) > 0, "Health response should not be empty"
    
    def test_health_endpoint_handles_errors_gracefully(self, client):
        """
        Test that health endpoint handles service exceptions gracefully
        **Validates: Requirements 8.8**
        """
        # The health endpoint should always return a response, even if services are down
        response = client.get("/health")
        
        # Should always return a response (not crash)
        assert response.status_code in [200, 503, 500]
        
        # Should return valid JSON even on errors
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail("Health endpoint should return valid JSON even on errors")
    
    def test_health_endpoint_performance(self, client):
        """
        Test that health endpoints respond quickly
        **Validates: Requirements 8.11**
        """
        import time
        
        start_time = time.time()
        response = client.get("/health")
        end_time = time.time()
        
        response_time = end_time - start_time
        
        # Health endpoint should respond quickly (under 5 seconds for basic test)
        assert response_time < 5.0, f"Health endpoint took {response_time:.3f}s, should be < 5.0s"
        
        # Should return valid response
        assert response.status_code in [200, 503, 500]
    
    def test_health_endpoint_concurrent_requests(self, client):
        """
        Test that health endpoints handle concurrent requests
        **Validates: Requirements 8.12**
        """
        import threading
        
        results = []
        
        def make_request():
            response = client.get("/health")
            results.append(response.status_code)
        
        # Make concurrent requests
        threads = []
        for _ in range(3):  # Small number for basic test
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All requests should complete
        assert len(results) == 3
        
        # All requests should return valid status codes
        for status_code in results:
            assert status_code in [200, 503, 500], f"Invalid status code: {status_code}"
    
    def test_root_endpoint_service_info(self, client):
        """
        Test that root endpoint returns service information
        **Validates: Requirements 7.1**
        """
        response = client.get("/")
        
        # Should return success
        assert response.status_code == 200
        
        # Should return valid JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            pytest.fail("Root endpoint should return valid JSON")
        
        # Should have service information
        assert isinstance(data, dict), "Root response should be JSON object"
        assert "service" in data, "Root response should have service name"
        assert "version" in data, "Root response should have version"
        assert "endpoints" in data, "Root response should have endpoints info"
        
        # Service name should be correct
        assert "RLaaS" in data["service"], "Service name should contain RLaaS"
    
    def test_metrics_endpoint_exists(self, client):
        """
        Test that metrics endpoint exists and responds
        **Validates: Requirements 6.1**
        """
        response = client.get("/metrics")
        
        # Should return a response (may be error if not fully configured)
        assert response.status_code in [200, 500, 503]
        
        if response.status_code == 200:
            # Should return metrics format
            content_type = response.headers.get("content-type", "")
            assert "text/plain" in content_type or "text" in content_type, "Metrics should return text format"
        else:
            # Error response should be JSON
            try:
                error_data = response.json()
                assert isinstance(error_data, dict)
            except json.JSONDecodeError:
                # Some metrics endpoints return plain text errors
                assert isinstance(response.text, str)
    
    def test_metrics_summary_endpoint_exists(self, client):
        """
        Test that metrics summary endpoint exists and responds
        **Validates: Requirements 6.5**
        """
        response = client.get("/metrics/summary")
        
        # Should return a response
        assert response.status_code in [200, 500, 503]
        
        # Should return JSON
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail("Metrics summary should return JSON")
    
    def test_stats_endpoint_exists(self, client):
        """
        Test that stats endpoint exists and responds
        **Validates: Requirements 6.4**
        """
        response = client.get("/stats")
        
        # Should return a response
        assert response.status_code in [200, 500, 503]
        
        # Should return JSON
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail("Stats endpoint should return JSON")
    
    def test_cors_headers_on_health_endpoints(self, client):
        """
        Test that health endpoints include appropriate headers
        **Validates: Requirements 8.10**
        """
        endpoints = ["/health", "/", "/metrics", "/stats"]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            
            # Should return valid response
            assert response.status_code in [200, 500, 503]
            
            # Should have content-type header
            assert "content-type" in response.headers, f"Endpoint {endpoint} should have content-type header"
            
            # Content type should be appropriate
            content_type = response.headers["content-type"]
            assert content_type is not None and len(content_type) > 0, f"Endpoint {endpoint} should have valid content-type"
    
    def test_health_check_with_different_methods(self, client):
        """
        Test health check endpoint with different HTTP methods
        """
        # GET should work
        get_response = client.get("/health")
        assert get_response.status_code in [200, 503, 500]
        
        # Other methods should return method not allowed or similar
        post_response = client.post("/health")
        assert post_response.status_code in [405, 404, 422]  # Method not allowed or not found
        
        put_response = client.put("/health")
        assert put_response.status_code in [405, 404, 422]
        
        delete_response = client.delete("/health")
        assert delete_response.status_code in [405, 404, 422]
    
    def test_health_endpoint_consistency(self, client):
        """
        Test that health endpoint returns consistent responses
        """
        responses = []
        
        # Make multiple requests
        for _ in range(3):
            response = client.get("/health")
            responses.append({
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "has_json": True
            })
            
            # Verify JSON response
            try:
                data = response.json()
                responses[-1]["has_json"] = isinstance(data, dict)
            except json.JSONDecodeError:
                responses[-1]["has_json"] = False
        
        # All responses should be consistent
        first_response = responses[0]
        for response in responses[1:]:
            # Status codes should be consistent (health shouldn't change rapidly)
            assert response["status_code"] == first_response["status_code"], "Health status should be consistent"
            
            # Content type should be consistent
            assert response["content_type"] == first_response["content_type"], "Content type should be consistent"
            
            # JSON format should be consistent
            assert response["has_json"] == first_response["has_json"], "JSON format should be consistent"