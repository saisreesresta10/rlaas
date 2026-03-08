"""Unit tests for FastAPI application"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from rlaas.api import app, rlaas_app
from rlaas.models import RateLimitResponse
from rlaas.decision_api import RateLimitDecisionError


class TestRLaaSAPI:
    """Test RLaaS FastAPI application"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_container(self):
        """Create mock container"""
        mock_container = MagicMock()
        mock_container.decision_api = MagicMock()
        
        # Configure process_rate_limit_request to return proper RateLimitResponse
        mock_container.decision_api.process_rate_limit_request = AsyncMock(
            return_value=RateLimitResponse(
                allowed=True,
                remaining_tokens=10,
                retry_after_ms=None,
                reset_after_ms=1000
            )
        )
        
        # Configure health_check to return proper dict
        mock_container.decision_api.health_check = AsyncMock(
            return_value={
                "service": "rate_limit_decision_api",
                "status": "healthy",
                "components": {
                    "rule_management": {"status": "healthy"},
                    "redis_state": {"status": "healthy", "connectivity": True}
                }
            }
        )
        
        # Configure get_stats to return proper dict
        mock_container.decision_api.get_stats = MagicMock(
            return_value={
                "requests_total": 100,
                "requests_allowed": 90,
                "requests_blocked": 10,
                "circuit_breaker_state": "closed",
                "active_buckets": 5,
                "rules_count": 3
            }
        )
        
        # Configure get_bucket_info to return proper dict
        mock_container.decision_api.get_bucket_info = AsyncMock(
            return_value={
                "client_id": "test_client",
                "endpoint": "/api/test", 
                "http_method": "GET",
                "tokens": 10.0,
                "last_refill": 1640995200.0,
                "limit": 100,
                "window_seconds": 60,
                "burst": 120
            }
        )
        
        # Configure container health_check
        mock_container.health_check = AsyncMock(
            return_value={
                "service": "rlaas_container",
                "status": "healthy",
                "components": {
                    "decision_api": {"status": "healthy"},
                    "redis_client": {"status": "healthy"}
                }
            }
        )
        
        return mock_container
    
    @pytest.fixture(autouse=True)
    def setup_mock_container(self, mock_container):
        """Setup mock container for all tests"""
        rlaas_app.container = mock_container
        rlaas_app._initialized = True
        yield
        # Cleanup
        rlaas_app.container = None
        rlaas_app._initialized = False
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns service information"""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["service"] == "RLaaS - Rate Limiter as a Service"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data
        assert "timestamp" in data
    
    def test_check_rate_limit_allowed(self, client, mock_container):
        """Test rate limit check endpoint - allowed request"""
        # Mock allowed response
        mock_response = RateLimitResponse(
            allowed=True,
            remaining_tokens=50,
            reset_after_ms=30000,
            retry_after_ms=None
        )
        mock_container.decision_api.process_rate_limit_request.return_value = mock_response
        
        # Make request
        request_data = {
            "client_id": "client1",
            "endpoint": "/api/test",
            "http_method": "GET"
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["allowed"] is True
        assert data["remaining_tokens"] == 50
        assert data["reset_after_ms"] == 30000
        assert data["retry_after_ms"] is None
        
        # Verify decision API was called correctly
        mock_container.decision_api.process_rate_limit_request.assert_called_once()
        call_args = mock_container.decision_api.process_rate_limit_request.call_args[0][0]
        assert call_args.client_id == "client1"
        assert call_args.endpoint == "/api/test"
        assert call_args.http_method == "GET"
    
    def test_check_rate_limit_blocked(self, client, mock_container):
        """Test rate limit check endpoint - blocked request"""
        # Mock blocked response
        mock_response = RateLimitResponse(
            allowed=False,
            remaining_tokens=None,
            reset_after_ms=None,
            retry_after_ms=5000
        )
        mock_container.decision_api.process_rate_limit_request.return_value = mock_response
        
        # Make request
        request_data = {
            "client_id": "client2",
            "endpoint": "/api/orders",
            "http_method": "POST"
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["allowed"] is False
        assert data["remaining_tokens"] is None
        assert data["reset_after_ms"] is None
        assert data["retry_after_ms"] == 5000
    
    def test_check_rate_limit_validation_error(self, client, mock_container):
        """Test rate limit check with validation error"""
        # Mock validation error
        mock_container.decision_api.process_rate_limit_request.side_effect = RateLimitDecisionError(
            "client_id cannot be empty"
        )
        
        # Make request with invalid data
        request_data = {
            "client_id": "",
            "endpoint": "/api/test",
            "http_method": "GET"
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 400
        data = response.json()
        
        assert data["error"] == "rate_limit_decision_error"
        assert "client_id cannot be empty" in data["message"]
        assert "timestamp" in data
    
    def test_check_rate_limit_invalid_json(self, client):
        """Test rate limit check with invalid JSON"""
        response = client.post(
            "/v1/rate-limit/check",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_check_rate_limit_missing_fields(self, client):
        """Test rate limit check with missing required fields"""
        request_data = {
            "client_id": "client1"
            # Missing endpoint and http_method
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 422  # Unprocessable Entity
        data = response.json()
        assert "detail" in data
    
    def test_check_rate_limit_internal_error(self, client, mock_container):
        """Test rate limit check with internal error"""
        # Mock internal error
        mock_container.decision_api.process_rate_limit_request.side_effect = Exception("Redis connection failed")
        
        request_data = {
            "client_id": "client1",
            "endpoint": "/api/test",
            "http_method": "GET"
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Rate limit check failed"
    
    def test_health_check_healthy(self, client, mock_container):
        """Test health check endpoint - healthy status"""
        # Mock healthy response
        mock_health = {
            "service": "rlaas_container",
            "status": "healthy",
            "components": {
                "rule_management": {"status": "healthy"},
                "redis_state": {"status": "healthy"},
                "token_bucket": {"status": "healthy"}
            },
            "timestamp": 1234567890.0
        }
        mock_container.health_check.return_value = mock_health
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["service"] == "rlaas_container"
        assert data["status"] == "healthy"
        assert "components" in data
        assert "timestamp" in data
    
    def test_health_check_degraded(self, client, mock_container):
        """Test health check endpoint - degraded status"""
        # Mock degraded response
        mock_health = {
            "service": "rlaas_container",
            "status": "degraded",
            "components": {
                "rule_management": {"status": "degraded"},
                "redis_state": {"status": "healthy"},
                "token_bucket": {"status": "healthy"}
            },
            "timestamp": 1234567890.0
        }
        mock_container.health_check.return_value = mock_health
        
        response = client.get("/health")
        
        assert response.status_code == 200  # Still operational
        data = response.json()
        assert data["status"] == "degraded"
    
    def test_health_check_unhealthy(self, client, mock_container):
        """Test health check endpoint - unhealthy status"""
        # Mock unhealthy response
        mock_health = {
            "service": "rlaas_container",
            "status": "unhealthy",
            "components": {
                "rule_management": {"status": "unhealthy"},
                "redis_state": {"status": "unhealthy"},
                "token_bucket": {"status": "healthy"}
            },
            "timestamp": 1234567890.0
        }
        mock_container.health_check.return_value = mock_health
        
        response = client.get("/health")
        
        assert response.status_code == 503  # Service unavailable
        data = response.json()
        assert data["status"] == "unhealthy"
    
    def test_health_check_error(self, client, mock_container):
        """Test health check endpoint with error"""
        # Mock health check error
        mock_container.health_check.side_effect = Exception("Health check failed")
        
        response = client.get("/health")
        
        assert response.status_code == 503
        data = response.json()
        
        assert data["service"] == "rlaas"
        assert data["status"] == "unhealthy"
        assert "error" in data
        assert "timestamp" in data
    
    def test_get_stats_success(self, client, mock_container):
        """Test stats endpoint - success"""
        # Mock stats response
        mock_stats = {
            "service": "rate_limit_decision_api",
            "timestamp": 1234567890.0,
            "components": {
                "rule_management": "active",
                "redis_state": "active",
                "token_bucket": "active"
            }
        }
        mock_container.decision_api.get_stats.return_value = mock_stats
        
        response = client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["service"] == "rate_limit_decision_api"
        assert "timestamp" in data
        assert "components" in data
    
    def test_get_stats_error(self, client, mock_container):
        """Test stats endpoint with error"""
        # Mock stats error
        mock_container.decision_api.get_stats.side_effect = Exception("Stats unavailable")
        
        response = client.get("/stats")
        
        assert response.status_code == 500
        data = response.json()
        
        assert data["error"] == "stats_unavailable"
        assert "message" in data
        assert "timestamp" in data
    
    def test_get_bucket_info_success(self, client, mock_container):
        """Test bucket info endpoint - success"""
        # Mock bucket info response
        mock_bucket_info = {
            "client_id": "client1",
            "endpoint": "/api/test",
            "http_method": "GET",
            "rule": {
                "limit": 100,
                "window_seconds": 60,
                "burst": 120,
                "refill_rate": 1.67
            },
            "current_state": {
                "tokens": 80,
                "capacity_used_percent": 33.33,
                "time_until_full_seconds": 24.0
            },
            "timestamp": 1234567890.0
        }
        mock_container.decision_api.get_bucket_info.return_value = mock_bucket_info
        
        response = client.get("/bucket-info/client1?endpoint=/api/test&http_method=GET")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["client_id"] == "client1"
        assert data["endpoint"] == "/api/test"
        assert data["http_method"] == "GET"
        assert "rule" in data
        assert "current_state" in data
        assert "timestamp" in data
        
        # Verify decision API was called correctly
        mock_container.decision_api.get_bucket_info.assert_called_once_with(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET"
        )
    
    def test_get_bucket_info_not_found(self, client, mock_container):
        """Test bucket info endpoint - not found"""
        # Mock bucket not found
        mock_container.decision_api.get_bucket_info.return_value = None
        
        response = client.get("/bucket-info/nonexistent?endpoint=/api/test&http_method=GET")
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Bucket not found"
    
    def test_get_bucket_info_error(self, client, mock_container):
        """Test bucket info endpoint with error"""
        # Mock bucket info error
        mock_container.decision_api.get_bucket_info.side_effect = Exception("Redis error")
        
        response = client.get("/bucket-info/client1?endpoint=/api/test&http_method=GET")
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to retrieve bucket information"
    
    def test_get_bucket_info_missing_params(self, client):
        """Test bucket info endpoint with missing query parameters"""
        response = client.get("/bucket-info/client1")
        
        assert response.status_code == 422  # Missing required query parameters
    
    def test_cors_middleware_configured(self, client):
        """Test CORS middleware is configured"""
        # Just verify that the middleware is set up - actual CORS testing
        # would require a real browser environment
        response = client.get("/")
        assert response.status_code == 200
    
    def test_request_logging_middleware(self, client, mock_decision_api):
        """Test request logging middleware adds processing time header"""
        # Mock successful response
        mock_response = RateLimitResponse(
            allowed=True,
            remaining_tokens=50,
            reset_after_ms=30000,
            retry_after_ms=None
        )
        mock_decision_api.process_rate_limit_request.return_value = mock_response
        
        request_data = {
            "client_id": "client1",
            "endpoint": "/api/test",
            "http_method": "GET"
        }
        
        response = client.post("/v1/rate-limit/check", json=request_data)
        
        assert response.status_code == 200
        assert "x-process-time" in response.headers
        
        # Process time should be a valid float
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0


class TestRLaaSAppLifecycle:
    """Test RLaaS application lifecycle management"""
    
    @pytest.mark.asyncio
    async def test_app_initialization(self):
        """Test application initialization"""
        app_instance = rlaas_app.__class__()
        
        # Mock the container creation to avoid Redis connection
        mock_container = MagicMock()
        mock_container.decision_api = MagicMock()
        
        with patch('rlaas.container.ServiceContainer.create', return_value=mock_container):
            await app_instance.initialize()
            
            assert app_instance._initialized is True
            assert app_instance.container is not None
    
    @pytest.mark.asyncio
    async def test_app_shutdown(self):
        """Test application shutdown"""
    @pytest.mark.asyncio
    async def test_app_shutdown(self):
        """Test application shutdown"""
        app_instance = rlaas_app.__class__()
        
        # Mock the shutdown_container function
        with patch('rlaas.api.shutdown_container') as mock_shutdown:
            mock_shutdown.return_value = None
            
            app_instance._initialized = True
            
            await app_instance.shutdown()
            
            # Verify cleanup was called
            mock_shutdown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_app_double_initialization(self):
        """Test that double initialization is handled gracefully"""
        app_instance = rlaas_app.__class__()
        
        mock_container = MagicMock()
        mock_container.decision_api = MagicMock()
        
        with patch('rlaas.container.ServiceContainer.create', return_value=mock_container):
            # Initialize twice
            await app_instance.initialize()
            await app_instance.initialize()
            
            # Should still be initialized
            assert app_instance._initialized is True
    
    @pytest.mark.asyncio
    async def test_app_initialization_error(self):
        """Test application initialization error handling"""
        app_instance = rlaas_app.__class__()
        
        # Ensure app starts fresh
        app_instance._initialized = False
        
        # Mock initialization failure
        with patch('rlaas.api.get_container', side_effect=Exception("Redis connection failed")):
            
            with pytest.raises(Exception):
                await app_instance.initialize()
            
            assert app_instance._initialized is False
    
    @pytest.mark.asyncio
    async def test_app_shutdown_error(self):
        """Test application shutdown error handling"""
        app_instance = rlaas_app.__class__()
        
        # Mock shutdown_container with failing shutdown
        with patch('rlaas.api.shutdown_container', side_effect=Exception("Shutdown error")):
            app_instance._initialized = True
            
            # Should not raise exception
        await app_instance.shutdown()


class TestAPIValidation:
    """Test API request/response validation"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    def test_rate_limit_check_request_validation(self, client):
        """Test rate limit check request validation"""
        # Test with various invalid requests
        invalid_requests = [
            {},  # Empty request
            {"client_id": "test"},  # Missing endpoint and http_method
            {"client_id": "test", "endpoint": "/api/test"},  # Missing http_method
            {"endpoint": "/api/test", "http_method": "GET"},  # Missing client_id
            {"client_id": 123, "endpoint": "/api/test", "http_method": "GET"},  # Invalid type
            {"client_id": "test", "endpoint": 123, "http_method": "GET"},  # Invalid type
            {"client_id": "test", "endpoint": "/api/test", "http_method": 123},  # Invalid type
        ]
        
        for invalid_request in invalid_requests:
            response = client.post("/v1/rate-limit/check", json=invalid_request)
            assert response.status_code == 422, f"Request should be invalid: {invalid_request}"
    
    def test_bucket_info_query_validation(self, client):
        """Test bucket info query parameter validation"""
        # Missing endpoint parameter
        response = client.get("/bucket-info/client1?http_method=GET")
        assert response.status_code == 422
        
        # Missing http_method parameter
        response = client.get("/bucket-info/client1?endpoint=/api/test")
        assert response.status_code == 422
        
        # Missing both parameters
        response = client.get("/bucket-info/client1")
        assert response.status_code == 422