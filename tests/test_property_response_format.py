"""Property-based tests for response format consistency"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, HealthCheck
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
import json

from rlaas.api import app
from rlaas.models import RateLimitResponse, RateLimitRule


class TestPropertyResponseFormat:
    """Property-based tests for API response format consistency"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @given(
        client_id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc'))),
        endpoint=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc', 'Pd', 'Po'))),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        allowed=st.booleans(),
        remaining_tokens=st.floats(min_value=0.0, max_value=1000.0),
        retry_after_ms=st.integers(min_value=0, max_value=3600000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_decision_response_format_consistency_property(self, client, client_id, endpoint, 
                                                         http_method, allowed, remaining_tokens, retry_after_ms):
        """
        Property 4: Response Format Consistency
        All decision API responses should follow a consistent JSON format
        with required fields: allowed, remaining_tokens, retry_after_ms
        **Validates: Requirements 1.2, 1.3, 7.2, 7.3**
        """
        # Make request to decision endpoint
        response = client.post(
            "/v1/rate-limit/check",
            json={
                "client_id": client_id,
                "endpoint": endpoint,
                "http_method": http_method
            }
        )
        
        # Response should be valid JSON regardless of status code
        assert response.status_code in [200, 429, 400, 500, 503]  # Valid status codes
        
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            pytest.fail("Response is not valid JSON")
        
        # For successful responses, verify required fields are present
        if response.status_code in [200, 429]:
            required_fields = ["allowed", "remaining_tokens", "retry_after_ms"]
            for field in required_fields:
                assert field in response_data, f"Required field '{field}' missing from response"
            
            # Verify field types
            assert isinstance(response_data["allowed"], bool), "'allowed' field must be boolean"
            assert isinstance(response_data["remaining_tokens"], (int, float)), "'remaining_tokens' field must be numeric"
            assert isinstance(response_data["retry_after_ms"], (int, float)), "'retry_after_ms' field must be numeric"
            
            # Verify field constraints
            assert response_data["remaining_tokens"] >= 0, "'remaining_tokens' must be non-negative"
            assert response_data["retry_after_ms"] >= 0, "'retry_after_ms' must be non-negative"
            
            # Verify logical consistency
            if response_data["allowed"]:
                # If allowed, retry_after should be 0
                assert response_data["retry_after_ms"] == 0, "When allowed=True, retry_after_ms should be 0"
            else:
                # If not allowed, retry_after should be > 0
                assert response_data["retry_after_ms"] > 0, "When allowed=False, retry_after_ms should be > 0"
        
        # For error responses, verify error structure
        elif response.status_code >= 400:
            # Should have error information
            assert any(key in response_data for key in ["error", "detail", "message"]), "Error response should have error info"
    
    @given(
        client_id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc'))),
        endpoint=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc', 'Pd', 'Po'))),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        limit=st.integers(min_value=1, max_value=1000),
        window_seconds=st.integers(min_value=1, max_value=3600),
        burst=st.integers(min_value=1, max_value=2000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_rule_management_response_format_consistency_property(self, client, client_id, endpoint, 
                                                                http_method, limit, window_seconds, burst):
        """
        Property: Rule Management Response Format Consistency
        All rule management API responses should follow consistent JSON format
        **Validates: Requirements 4.1**
        """
        # Ensure burst >= limit for valid rule
        if burst < limit:
            burst = limit
        
        rule_data = {
            "client_id": client_id,
            "endpoint": endpoint,
            "http_method": http_method,
            "limit": limit,
            "window_seconds": window_seconds,
            "burst": burst
        }
        
        # Test CREATE rule response format
        create_response = client.post("/v1/rate-limit/rules", json=rule_data)
        
        # Should return success response or error
        assert create_response.status_code in [200, 201, 400, 500, 503]
        
        try:
            create_data = create_response.json()
        except json.JSONDecodeError:
            pytest.fail("Create rule response is not valid JSON")
        
        # Verify create response structure
        assert isinstance(create_data, dict), "Response should be JSON object"
        
        if create_response.status_code in [200, 201]:
            # Success response should have success indicator
            assert any(key in create_data for key in ["success", "message", "rule"]), "Success response should have success info"
        else:
            # Error response should have error info
            assert any(key in create_data for key in ["error", "detail", "message"]), "Error response should have error info"
    
    @given(
        error_scenario=st.sampled_from([
            "invalid_json",
            "missing_client_id", 
            "missing_endpoint",
            "missing_http_method",
            "invalid_http_method"
        ])
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_error_response_format_consistency_property(self, client, error_scenario):
        """
        Property: Error Response Format Consistency
        All error responses should follow consistent format with error details
        **Validates: Requirements 8.1**
        """
        if error_scenario == "invalid_json":
            # Send invalid JSON
            response = client.post(
                "/v1/rate-limit/check",
                data="{invalid json}",
                headers={"Content-Type": "application/json"}
            )
        elif error_scenario == "missing_client_id":
            response = client.post(
                "/v1/rate-limit/check",
                json={
                    "endpoint": "/api/test",
                    "http_method": "GET"
                }
            )
        elif error_scenario == "missing_endpoint":
            response = client.post(
                "/v1/rate-limit/check",
                json={
                    "client_id": "test_client",
                    "http_method": "GET"
                }
            )
        elif error_scenario == "missing_http_method":
            response = client.post(
                "/v1/rate-limit/check",
                json={
                    "client_id": "test_client",
                    "endpoint": "/api/test"
                }
            )
        elif error_scenario == "invalid_http_method":
            response = client.post(
                "/v1/rate-limit/check",
                json={
                    "client_id": "test_client",
                    "endpoint": "/api/test",
                    "http_method": "INVALID"
                }
            )
        
        # Should return error status code
        assert response.status_code >= 400
        
        try:
            error_data = response.json()
        except json.JSONDecodeError:
            pytest.fail("Error response is not valid JSON")
        
        # Verify error response has required fields
        assert isinstance(error_data, dict), "Error response should be JSON object"
        assert any(key in error_data for key in ["detail", "message", "error"]), "Error response should have error info"
        
        # If detail field exists, it should be informative
        if "detail" in error_data:
            assert len(str(error_data["detail"])) > 0, "Error detail should not be empty"
    
    @given(
        request_count=st.integers(min_value=1, max_value=5)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_response_format_stability_property(self, client, request_count):
        """
        Property: Response format should be stable across multiple requests
        """
        responses = []
        
        for i in range(request_count):
            response = client.post(
                "/v1/rate-limit/check",
                json={
                    "client_id": f"test_client_{i}",
                    "endpoint": "/api/test",
                    "http_method": "GET"
                }
            )
            
            assert response.status_code in [200, 429, 400, 500, 503]
            
            try:
                response_data = response.json()
                responses.append(response_data)
            except json.JSONDecodeError:
                pytest.fail(f"Response {i} is not valid JSON")
        
        # All responses should be valid JSON objects
        for i, response_data in enumerate(responses):
            assert isinstance(response_data, dict), f"Response {i} should be JSON object"
        
        # If we have successful responses, they should have consistent structure
        successful_responses = [r for r in responses if "allowed" in r]
        if len(successful_responses) > 1:
            first_response_keys = set(successful_responses[0].keys())
            for i, response_data in enumerate(successful_responses[1:], 1):
                response_keys = set(response_data.keys())
                # Allow for some variation in optional fields, but core fields should be consistent
                core_fields = {"allowed", "remaining_tokens", "retry_after_ms"}
                first_core = first_response_keys & core_fields
                response_core = response_keys & core_fields
                assert first_core == response_core, f"Core response structure should be consistent between responses"
                
                # Field types should be consistent for core fields
                for key in first_core:
                    assert type(response_data[key]) == type(successful_responses[0][key]), f"Field '{key}' type should be consistent"
    
    @given(
        concurrent_requests=st.integers(min_value=2, max_value=5)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_concurrent_response_format_consistency_property(self, client, concurrent_requests):
        """
        Property: Response format should be consistent under concurrent load
        """
        import threading
        
        responses = []
        errors = []
        
        def make_request(request_id):
            try:
                response = client.post(
                    "/v1/rate-limit/check",
                    json={
                        "client_id": f"concurrent_client_{request_id}",
                        "endpoint": "/api/concurrent_test",
                        "http_method": "GET"
                    }
                )
                
                response_data = response.json()
                responses.append({
                    "status_code": response.status_code,
                    "data": response_data
                })
            except Exception as e:
                errors.append(str(e))
        
        # Launch concurrent requests
        threads = []
        for i in range(concurrent_requests):
            thread = threading.Thread(target=make_request, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all requests to complete
        for thread in threads:
            thread.join()
        
        # Verify all requests completed successfully
        assert len(errors) == 0, f"Concurrent requests should not fail: {errors}"
        assert len(responses) == concurrent_requests, "All concurrent requests should complete"
        
        # All responses should be valid JSON objects
        for i, response in enumerate(responses):
            assert isinstance(response["data"], dict), f"Response {i} should be JSON object"
            assert response["status_code"] in [200, 429, 400, 500, 503], f"Response {i} should have valid status code"
        
        # Responses should have consistent structure
        successful_responses = [r["data"] for r in responses if r["status_code"] in [200, 429] and "allowed" in r["data"]]
        if len(successful_responses) > 1:
            # All successful responses should have the same core structure
            core_fields = {"allowed", "remaining_tokens", "retry_after_ms"}
            first_core_fields = set(successful_responses[0].keys()) & core_fields
            
            for response_data in successful_responses[1:]:
                response_core_fields = set(response_data.keys()) & core_fields
                assert first_core_fields == response_core_fields, "Concurrent responses should have consistent structure"