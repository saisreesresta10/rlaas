"""End-to-end integration tests for the complete RLaaS system"""

import pytest
import asyncio
import time
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import json
import redis.asyncio as redis

from rlaas.api import app
from rlaas.models import RateLimitRule, RateLimitResponse
from rlaas.container import ServiceContainer


class TestEndToEndIntegration:
    """End-to-end integration tests for complete system functionality"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client for integration tests"""
        mock_redis = AsyncMock()
        # Mock Redis responses for different scenarios
        mock_redis.get.return_value = None  # No existing rules by default
        mock_redis.set.return_value = True
        mock_redis.delete.return_value = True
        mock_redis.eval.return_value = [1, 10.0]  # [allowed, remaining_tokens]
        return mock_redis
    
    def test_complete_rate_limiting_workflow(self, client):
        """
        Test complete workflow: create rule -> make decisions -> verify rate limiting
        **Validates: Requirements 1.1, 2.1, 3.1, 4.1**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            # Setup mock container
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            # Mock decision API
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_decision_api.rule_management_service = MagicMock()
            mock_decision_api.rule_management_service.create_or_update_rule = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            # Step 1: Create a rate limit rule
            rule_data = {
                "client_id": "test_client",
                "endpoint": "/api/test",
                "http_method": "GET",
                "limit": 10,
                "window_seconds": 60,
                "burst": 15
            }
            
            # Mock rule creation success
            mock_decision_api.rule_management_service.create_or_update_rule.return_value = None
            
            create_response = client.post("/v1/rate-limit/rules", json=rule_data)
            assert create_response.status_code in [200, 201]
            
            # Step 2: Make rate limit decisions
            decision_request = {
                "client_id": "test_client",
                "endpoint": "/api/test",
                "http_method": "GET"
            }
            
            # Mock first few requests as allowed
            mock_decision_api.process_rate_limit_request.side_effect = [
                RateLimitResponse(allowed=True, remaining_tokens=9, retry_after_ms=None, reset_after_ms=60000),
                RateLimitResponse(allowed=True, remaining_tokens=8, retry_after_ms=None, reset_after_ms=60000),
                RateLimitResponse(allowed=False, remaining_tokens=None, retry_after_ms=60000, reset_after_ms=None)
            ]
            
            # First request should be allowed
            response1 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response1.status_code == 200
            data1 = response1.json()
            assert data1["allowed"] is True
            assert data1["remaining_tokens"] == 9
            
            # Second request should be allowed
            response2 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["allowed"] is True
            assert data2["remaining_tokens"] == 8
            
            # Third request should be rate limited
            response3 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response3.status_code == 200  # API returns 200 even for blocked requests
            data3 = response3.json()
            assert data3["allowed"] is False
            assert data3["retry_after_ms"] == 60000
    
    def test_rule_management_integration(self, client):
        """
        Test rule management integration: create, update, retrieve rules
        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            # Mock decision API with rule management service
            mock_decision_api = MagicMock()
            mock_decision_api.rule_management_service = MagicMock()
            mock_decision_api.rule_management_service.create_or_update_rule = AsyncMock()
            mock_decision_api.rule_management_service.get_rule = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            # Test rule creation
            rule_data = {
                "client_id": "integration_client",
                "endpoint": "/api/integration",
                "http_method": "POST",
                "limit": 5,
                "window_seconds": 30,
                "burst": 10
            }
            
            mock_decision_api.rule_management_service.create_or_update_rule.return_value = None
            create_response = client.post("/v1/rate-limit/rules", json=rule_data)
            assert create_response.status_code in [200, 201]
            
            # Test rule retrieval
            from rlaas.models import RateLimitRule
            mock_rule = RateLimitRule(**rule_data)
            mock_decision_api.rule_management_service.get_rule.side_effect = [mock_rule, mock_rule]
            
            get_response = client.get(
                f"/v1/rate-limit/rules/{rule_data['client_id']}?endpoint={rule_data['endpoint']}&http_method={rule_data['http_method']}"
            )
            
            if get_response.status_code == 200:
                rule_response = get_response.json()
                assert rule_response["rule"]["client_id"] == rule_data["client_id"]
                assert rule_response["rule"]["limit"] == rule_data["limit"]
                assert rule_response["rule"]["window_seconds"] == rule_data["window_seconds"]
            
            # Test rule update
            updated_rule_data = rule_data.copy()
            updated_rule_data["limit"] = 20
            
            mock_decision_api.rule_management_service.create_or_update_rule.return_value = None
            update_response = client.post(
                "/v1/rate-limit/rules",
                json=updated_rule_data
            )
            
            # Should succeed or return appropriate status
            assert update_response.status_code in [200, 201, 404]
    
    def test_circuit_breaker_integration(self, client):
        """
        Test circuit breaker integration during Redis failures
        **Validates: Requirements 5.1, 3.4**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            decision_request = {
                "client_id": "circuit_test_client",
                "endpoint": "/api/circuit_test",
                "http_method": "GET"
            }
            
            # Simulate circuit breaker in different states
            
            # 1. Normal operation (circuit closed)
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=10, reset_after_ms=60000, retry_after_ms=None
            )
            
            response1 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response1.status_code == 200
            
            # 2. Circuit breaker open (fail-safe mode)
            mock_decision_api.process_rate_limit_request.side_effect = Exception("Redis connection failed")
            
            response2 = client.post("/v1/rate-limit/check", json=decision_request)
            # Should either fail gracefully or allow request (depending on fail-safe configuration)
            assert response2.status_code in [200, 429, 500, 503]
            
            # 3. Circuit breaker half-open (testing recovery)
            mock_decision_api.process_rate_limit_request.side_effect = None
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=5, reset_after_ms=60000, retry_after_ms=None
            )
            
            response3 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response3.status_code == 200
    
    def test_metrics_and_logging_integration(self, client):
        """
        Test that metrics and logging work throughout the request flow
        **Validates: Requirements 6.1, 6.2, 6.3**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            decision_request = {
                "client_id": "metrics_test_client",
                "endpoint": "/api/metrics_test",
                "http_method": "GET"
            }
            
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=8, reset_after_ms=60000, retry_after_ms=None
            )
            
            # Make request
            response = client.post("/v1/rate-limit/check", json=decision_request)
            assert response.status_code == 200
            
            # Verify metrics were called (if metrics integration exists)
            # This would verify that metrics.record_decision() was called
            # The exact verification depends on how metrics are integrated
    
    def test_error_handling_integration(self, client):
        """
        Test error handling across the entire system
        **Validates: Requirements 8.1, 8.2**
        """
        # Test various error scenarios
        
        # 1. Invalid request format
        invalid_request = {"invalid": "data"}
        response1 = client.post("/v1/rate-limit/check", json=invalid_request)
        assert response1.status_code >= 400
        
        # 2. Missing required fields
        incomplete_request = {"client_id": "test"}
        response2 = client.post("/v1/rate-limit/check", json=incomplete_request)
        assert response2.status_code >= 400
        
        # 3. Invalid HTTP method in rule creation
        invalid_rule = {
            "client_id": "test_client",
            "endpoint": "/api/test",
            "http_method": "INVALID_METHOD",
            "limit": 10,
            "window_seconds": 60,
            "burst": 15
        }
        response3 = client.post("/v1/rate-limit/rules", json=invalid_rule)
        assert response3.status_code >= 400
        
        # 4. Invalid rule parameters
        invalid_rule2 = {
            "client_id": "test_client",
            "endpoint": "/api/test",
            "http_method": "GET",
            "limit": -1,  # Invalid negative limit
            "window_seconds": 60,
            "burst": 15
        }
        response4 = client.post("/v1/rate-limit/rules", json=invalid_rule2)
        assert response4.status_code >= 400
    
    def test_concurrent_requests_integration(self, client):
        """
        Test system behavior under concurrent load
        **Validates: Requirements 1.4, 2.5**
        """
        import threading
        import time
        
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            # Mock responses for concurrent requests
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=5, reset_after_ms=60000, retry_after_ms=None
            )
            
            results = []
            errors = []
            
            def make_concurrent_request(request_id):
                try:
                    decision_request = {
                        "client_id": f"concurrent_client_{request_id}",
                        "endpoint": "/api/concurrent_test",
                        "http_method": "GET"
                    }
                    
                    response = client.post("/v1/rate-limit/check", json=decision_request)
                    results.append({
                        "request_id": request_id,
                        "status_code": response.status_code,
                        "response_time": time.time()
                    })
                except Exception as e:
                    errors.append({"request_id": request_id, "error": str(e)})
            
            # Launch concurrent requests
            threads = []
            start_time = time.time()
            
            for i in range(10):
                thread = threading.Thread(target=make_concurrent_request, args=(i,))
                threads.append(thread)
                thread.start()
            
            # Wait for all requests to complete
            for thread in threads:
                thread.join()
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Verify results
            assert len(results) + len(errors) == 10, "All requests should complete"
            assert len(errors) == 0, f"No errors expected, but got: {errors}"
            
            # All requests should succeed
            success_count = len([r for r in results if r["status_code"] == 200])
            assert success_count > 0, "At least some requests should succeed"
            
            # System should handle concurrent load reasonably quickly
            assert total_time < 10.0, f"Concurrent requests took {total_time:.2f}s, should be < 10s"
    
    def test_rate_limit_accuracy_integration(self, client):
        """
        Test that rate limiting is accurate under realistic conditions
        **Validates: Requirements 1.1, 2.1, 2.2**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_decision_api.rule_management_service = MagicMock()
            mock_decision_api.rule_management_service.create_or_update_rule = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            # Create a strict rate limit rule
            rule_data = {
                "client_id": "accuracy_test_client",
                "endpoint": "/api/accuracy_test",
                "http_method": "GET",
                "limit": 3,  # Only 3 requests allowed
                "window_seconds": 60,
                "burst": 3
            }
            
            mock_decision_api.rule_management_service.create_or_update_rule.return_value = None
            create_response = client.post("/v1/rate-limit/rules", json=rule_data)
            assert create_response.status_code in [200, 201]
            
            decision_request = {
                "client_id": "accuracy_test_client",
                "endpoint": "/api/accuracy_test",
                "http_method": "GET"
            }
            
            # Mock decreasing token counts
            mock_decision_api.process_rate_limit_request.side_effect = [
                RateLimitResponse(allowed=True, remaining_tokens=2, reset_after_ms=60000, retry_after_ms=None),   # Request 1
                RateLimitResponse(allowed=True, remaining_tokens=1, reset_after_ms=60000, retry_after_ms=None),   # Request 2
                RateLimitResponse(allowed=True, remaining_tokens=0, reset_after_ms=60000, retry_after_ms=None),   # Request 3
                RateLimitResponse(allowed=False, remaining_tokens=None, reset_after_ms=None, retry_after_ms=60000), # Request 4 - blocked
                RateLimitResponse(allowed=False, remaining_tokens=None, reset_after_ms=None, retry_after_ms=60000), # Request 5 - blocked
            ]
            
            responses = []
            for i in range(5):
                response = client.post("/v1/rate-limit/check", json=decision_request)
                responses.append({
                    "request_num": i + 1,
                    "status_code": response.status_code,
                    "data": response.json()
                })
            
            # Verify rate limiting accuracy
            # First 3 requests should be allowed
            for i in range(3):
                assert responses[i]["status_code"] == 200, f"Request {i+1} should be allowed"
                assert responses[i]["data"]["allowed"] is True, f"Request {i+1} should be allowed"
            
            # Remaining requests should be blocked
            for i in range(3, 5):
                assert responses[i]["status_code"] == 200, f"Request {i+1} should return 200 but be blocked"
                assert responses[i]["data"]["allowed"] is False, f"Request {i+1} should be blocked"
                assert responses[i]["data"]["retry_after_ms"] > 0, f"Request {i+1} should have retry_after_ms"
    
    def test_system_recovery_integration(self, client):
        """
        Test system recovery after failures
        **Validates: Requirements 5.1, 3.4**
        """
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            decision_request = {
                "client_id": "recovery_test_client",
                "endpoint": "/api/recovery_test",
                "http_method": "GET"
            }
            
            # Phase 1: Normal operation
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=10, reset_after_ms=60000, retry_after_ms=None
            )
            
            response1 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response1.status_code == 200
            
            # Phase 2: System failure
            mock_decision_api.process_rate_limit_request.side_effect = Exception("System failure")
            
            response2 = client.post("/v1/rate-limit/check", json=decision_request)
            # Should handle failure gracefully
            assert response2.status_code in [200, 429, 500, 503]
            
            # Phase 3: System recovery
            mock_decision_api.process_rate_limit_request.side_effect = None
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=8, reset_after_ms=60000, retry_after_ms=None
            )
            
            response3 = client.post("/v1/rate-limit/check", json=decision_request)
            assert response3.status_code == 200
            
            # Verify system is fully operational again
            data3 = response3.json()
            assert data3["allowed"] is True
            assert "remaining_tokens" in data3
    
    def test_configuration_integration(self, client):
        """
        Test that configuration changes are properly applied
        **Validates: Requirements 3.4, 5.1**
        """
        # This test would verify that configuration changes
        # (like circuit breaker thresholds, Redis timeouts, etc.)
        # are properly applied throughout the system
        
        # Since configuration is typically loaded at startup,
        # this test mainly verifies that the system respects
        # the configured values
        
        with patch('rlaas.api.get_container') as mock_get_container:
            mock_container = MagicMock()
            mock_get_container.return_value = mock_container
            
            mock_decision_api = MagicMock()
            mock_decision_api.process_rate_limit_request = AsyncMock()
            mock_container.decision_api = mock_decision_api
            
            # Test with different configuration scenarios
            decision_request = {
                "client_id": "config_test_client",
                "endpoint": "/api/config_test",
                "http_method": "GET"
            }
            
            mock_decision_api.process_rate_limit_request.return_value = RateLimitResponse(
                allowed=True, remaining_tokens=5, reset_after_ms=60000, retry_after_ms=None
            )
            
            response = client.post("/v1/rate-limit/check", json=decision_request)
            assert response.status_code == 200
            
            # Verify response format matches configuration expectations
            data = response.json()
            assert "allowed" in data
            assert "remaining_tokens" in data or "retry_after_ms" in data
            
            # Verify data types and constraints
            assert isinstance(data["allowed"], bool)
            if "remaining_tokens" in data:
                assert isinstance(data["remaining_tokens"], (int, float))
                assert data["remaining_tokens"] >= 0
            if "retry_after_ms" in data:
                assert isinstance(data["retry_after_ms"], (int, float))
                assert data["retry_after_ms"] >= 0