"""Unit tests for RateLimitDecisionAPI"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from rlaas.decision_api import (
    RateLimitDecisionAPI,
    RateLimitDecisionResult,
    RateLimitDecisionError
)
from rlaas.models import (
    RateLimitCheckRequest,
    RateLimitResponse,
    RateLimitRule,
    TokenBucketResult
)
from rlaas.circuit_breaker import CircuitBreakerError


class TestRateLimitDecisionAPI:
    """Test RateLimitDecisionAPI functionality"""
    
    @pytest.fixture
    def mock_rule_service(self):
        """Create mock rule management service"""
        service = MagicMock()
        service.get_rule = AsyncMock()
        service.health_check = AsyncMock(return_value={"status": "healthy"})
        return service
    
    @pytest.fixture
    def mock_redis_state_manager(self):
        """Create mock Redis state manager"""
        manager = MagicMock()
        manager.atomic_refill_and_consume = AsyncMock()
        manager.atomic_get_and_refill = AsyncMock()
        manager.health_check = AsyncMock(return_value=True)
        manager.redis_client_manager = MagicMock()
        manager.redis_client_manager.get_circuit_breaker_stats = MagicMock(return_value=None)
        return manager
    
    @pytest.fixture
    def mock_token_bucket_service(self):
        """Create mock token bucket service"""
        return MagicMock()
    
    @pytest.fixture
    def decision_api(self, mock_rule_service, mock_redis_state_manager, mock_token_bucket_service):
        """Create RateLimitDecisionAPI instance"""
        return RateLimitDecisionAPI(
            mock_rule_service,
            mock_redis_state_manager,
            mock_token_bucket_service
        )
    
    @pytest.fixture
    def valid_request(self):
        """Create valid rate limit check request"""
        return RateLimitCheckRequest(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET"
        )
    
    @pytest.fixture
    def test_rule(self):
        """Create test rate limiting rule"""
        return RateLimitRule(
            client_id="client1",
            endpoint="/api/test",
            http_method="GET",
            limit=100,
            window_seconds=60,
            burst=120
        )
    
    def test_initialization(self, decision_api):
        """Test decision API initialization"""
        assert decision_api.rule_management_service is not None
        assert decision_api.redis_state_manager is not None
        assert decision_api.token_bucket_service is not None
    
    def test_validate_request_success(self, decision_api, valid_request):
        """Test successful request validation"""
        # Should not raise exception
        decision_api.validate_request(valid_request)
    
    def test_validate_request_empty_client_id(self, decision_api):
        """Test request validation with empty client_id"""
        request = RateLimitCheckRequest(
            client_id="",
            endpoint="/api/test",
            http_method="GET"
        )
        
        with pytest.raises(RateLimitDecisionError, match="client_id cannot be empty"):
            decision_api.validate_request(request)
    
    def test_validate_request_empty_endpoint(self, decision_api):
        """Test request validation with empty endpoint"""
        request = RateLimitCheckRequest(
            client_id="client1",
            endpoint="",
            http_method="GET"
        )
        
        with pytest.raises(RateLimitDecisionError, match="endpoint cannot be empty"):
            decision_api.validate_request(request)
    
    def test_validate_request_invalid_http_method(self, decision_api):
        """Test request validation with invalid HTTP method"""
        request = RateLimitCheckRequest(
            client_id="client1",
            endpoint="/api/test",
            http_method="INVALID"
        )
        
        with pytest.raises(RateLimitDecisionError, match="http_method must be one of"):
            decision_api.validate_request(request)
    
    def test_validate_request_multiple_errors(self, decision_api):
        """Test request validation with multiple errors"""
        request = RateLimitCheckRequest(
            client_id="",
            endpoint="",
            http_method="INVALID"
        )
        
        with pytest.raises(RateLimitDecisionError) as exc_info:
            decision_api.validate_request(request)
        
        error_message = str(exc_info.value)
        assert "client_id cannot be empty" in error_message
        assert "endpoint cannot be empty" in error_message
        assert "http_method must be one of" in error_message
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, decision_api, mock_rule_service, 
                                          mock_redis_state_manager, valid_request, test_rule):
        """Test rate limit check when request is allowed"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock successful token consumption
        token_result = TokenBucketResult(
            success=True,
            remaining_tokens=50,
            retry_after_ms=None,
            reset_after_ms=30000
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        result = await decision_api.check_rate_limit(valid_request)
        
        assert result.allowed is True
        assert result.remaining_tokens == 50
        assert result.reset_after_ms == 30000
        assert result.rule_applied == test_rule
        assert result.error_message is None
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_blocked(self, decision_api, mock_rule_service,
                                          mock_redis_state_manager, valid_request, test_rule):
        """Test rate limit check when request is blocked"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock blocked token consumption
        token_result = TokenBucketResult(
            success=False,
            remaining_tokens=0,
            retry_after_ms=5000,
            reset_after_ms=None
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        result = await decision_api.check_rate_limit(valid_request)
        
        assert result.allowed is False
        assert result.remaining_tokens is None
        assert result.retry_after_ms == 5000
        assert result.rule_applied == test_rule
        assert result.error_message is None
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_default_rule(self, decision_api, mock_rule_service,
                                                mock_redis_state_manager, valid_request, test_rule):
        """Test rate limit check using default rule"""
        # Mock rule retrieval - configured rule call fails, fallback succeeds
        mock_rule_service.get_rule.side_effect = [
            test_rule,  # First call (with fallback) succeeds
            Exception("No configured rule")  # Second call (without fallback) fails
        ]
        
        # Mock successful token consumption
        token_result = TokenBucketResult(
            success=True,
            remaining_tokens=80,
            retry_after_ms=None,
            reset_after_ms=25000
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        result = await decision_api.check_rate_limit(valid_request)
        
        assert result.allowed is True
        assert result.used_default_rule is True
        assert result.rule_applied == test_rule
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_circuit_breaker_error(self, decision_api, mock_rule_service,
                                                         mock_redis_state_manager, valid_request, test_rule):
        """Test rate limit check with circuit breaker error"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock circuit breaker error
        mock_redis_state_manager.atomic_refill_and_consume.side_effect = CircuitBreakerError("Circuit breaker open")
        
        result = await decision_api.check_rate_limit(valid_request)
        
        # Should fail open (allow request) when circuit breaker is open
        assert result.allowed is True
        assert result.remaining_tokens is None
        assert result.error_message == "Circuit breaker open - failing open"
        assert result.rule_applied == test_rule
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_general_error(self, decision_api, mock_rule_service,
                                                 valid_request):
        """Test rate limit check with general error"""
        # Mock rule retrieval failure
        mock_rule_service.get_rule.side_effect = Exception("Redis connection failed")
        
        result = await decision_api.check_rate_limit(valid_request)
        
        # Should fail closed (block request) for safety
        assert result.allowed is False
        assert result.error_message is not None
        assert "Rate limit check failed" in result.error_message
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_validation_error(self, decision_api):
        """Test rate limit check with validation error"""
        invalid_request = RateLimitCheckRequest(
            client_id="",
            endpoint="/api/test",
            http_method="GET"
        )
        
        with pytest.raises(RateLimitDecisionError):
            await decision_api.check_rate_limit(invalid_request)
    
    def test_format_response_allowed(self, decision_api):
        """Test formatting allowed response"""
        decision_result = RateLimitDecisionResult(
            allowed=True,
            remaining_tokens=42,
            reset_after_ms=12000
        )
        
        response = decision_api.format_response(decision_result)
        
        assert isinstance(response, RateLimitResponse)
        assert response.allowed is True
        assert response.remaining_tokens == 42
        assert response.reset_after_ms == 12000
        assert response.retry_after_ms is None
    
    def test_format_response_blocked(self, decision_api):
        """Test formatting blocked response"""
        decision_result = RateLimitDecisionResult(
            allowed=False,
            retry_after_ms=3000
        )
        
        response = decision_api.format_response(decision_result)
        
        assert isinstance(response, RateLimitResponse)
        assert response.allowed is False
        assert response.retry_after_ms == 3000
        assert response.remaining_tokens is None
        assert response.reset_after_ms is None
    
    @pytest.mark.asyncio
    async def test_process_rate_limit_request_allowed(self, decision_api, mock_rule_service,
                                                    mock_redis_state_manager, valid_request, test_rule):
        """Test complete rate limit request processing - allowed"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock successful token consumption
        token_result = TokenBucketResult(
            success=True,
            remaining_tokens=75,
            retry_after_ms=None,
            reset_after_ms=20000
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        response = await decision_api.process_rate_limit_request(valid_request)
        
        assert isinstance(response, RateLimitResponse)
        assert response.allowed is True
        assert response.remaining_tokens == 75
        assert response.reset_after_ms == 20000
    
    @pytest.mark.asyncio
    async def test_process_rate_limit_request_blocked(self, decision_api, mock_rule_service,
                                                    mock_redis_state_manager, valid_request, test_rule):
        """Test complete rate limit request processing - blocked"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock blocked token consumption
        token_result = TokenBucketResult(
            success=False,
            remaining_tokens=0,
            retry_after_ms=8000,
            reset_after_ms=None
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        response = await decision_api.process_rate_limit_request(valid_request)
        
        assert isinstance(response, RateLimitResponse)
        assert response.allowed is False
        assert response.retry_after_ms == 8000
    
    @pytest.mark.asyncio
    async def test_process_rate_limit_request_multiple_tokens(self, decision_api, mock_rule_service,
                                                            mock_redis_state_manager, valid_request, test_rule):
        """Test rate limit request processing with multiple tokens"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock successful token consumption
        token_result = TokenBucketResult(
            success=True,
            remaining_tokens=45,
            retry_after_ms=None,
            reset_after_ms=15000
        )
        mock_redis_state_manager.atomic_refill_and_consume.return_value = token_result
        
        response = await decision_api.process_rate_limit_request(valid_request, tokens_to_consume=5)
        
        # Verify the correct number of tokens was requested
        mock_redis_state_manager.atomic_refill_and_consume.assert_called_once()
        call_args = mock_redis_state_manager.atomic_refill_and_consume.call_args
        assert call_args.kwargs['tokens_to_consume'] == 5
        
        assert response.allowed is True
        assert response.remaining_tokens == 45
    
    @pytest.mark.asyncio
    async def test_get_bucket_info_success(self, decision_api, mock_rule_service,
                                         mock_redis_state_manager, test_rule):
        """Test getting bucket information"""
        # Mock rule retrieval
        mock_rule_service.get_rule.return_value = test_rule
        
        # Mock current token count
        mock_redis_state_manager.atomic_get_and_refill.return_value = 80
        
        bucket_info = await decision_api.get_bucket_info("client1", "/api/test", "GET")
        
        assert bucket_info is not None
        assert bucket_info["client_id"] == "client1"
        assert bucket_info["endpoint"] == "/api/test"
        assert bucket_info["http_method"] == "GET"
        assert bucket_info["rule"]["limit"] == 100
        assert bucket_info["rule"]["burst"] == 120
        assert bucket_info["current_state"]["tokens"] == 80
        assert "capacity_used_percent" in bucket_info["current_state"]
        assert "time_until_full_seconds" in bucket_info["current_state"]
        assert "timestamp" in bucket_info
    
    @pytest.mark.asyncio
    async def test_get_bucket_info_error(self, decision_api, mock_rule_service):
        """Test getting bucket information with error"""
        # Mock rule retrieval failure
        mock_rule_service.get_rule.side_effect = Exception("Redis error")
        
        bucket_info = await decision_api.get_bucket_info("client1", "/api/test", "GET")
        
        assert bucket_info is None
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, decision_api, mock_rule_service, mock_redis_state_manager):
        """Test health check when all components are healthy"""
        # Mock healthy components
        mock_rule_service.health_check.return_value = {"status": "healthy"}
        mock_redis_state_manager.health_check.return_value = True
        
        health = await decision_api.health_check()
        
        assert health["service"] == "rate_limit_decision_api"
        assert health["status"] == "healthy"
        assert health["components"]["rule_management"]["status"] == "healthy"
        assert health["components"]["redis_state"]["status"] == "healthy"
        assert health["components"]["token_bucket"]["status"] == "healthy"
        assert "timestamp" in health
    
    @pytest.mark.asyncio
    async def test_health_check_degraded(self, decision_api, mock_rule_service, mock_redis_state_manager):
        """Test health check when components are degraded"""
        # Mock degraded rule service
        mock_rule_service.health_check.return_value = {"status": "degraded"}
        mock_redis_state_manager.health_check.return_value = True
        
        health = await decision_api.health_check()
        
        assert health["service"] == "rate_limit_decision_api"
        assert health["status"] == "healthy"  # Still healthy if degraded
        assert health["components"]["rule_management"]["status"] == "degraded"
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, decision_api, mock_rule_service, mock_redis_state_manager):
        """Test health check when components are unhealthy"""
        # Mock unhealthy components
        mock_rule_service.health_check.return_value = {"status": "unhealthy"}
        mock_redis_state_manager.health_check.return_value = False
        
        health = await decision_api.health_check()
        
        assert health["service"] == "rate_limit_decision_api"
        assert health["status"] == "unhealthy"
        assert health["components"]["redis_state"]["status"] == "unhealthy"
    
    @pytest.mark.asyncio
    async def test_health_check_exception(self, decision_api, mock_rule_service):
        """Test health check with exception"""
        # Mock exception in health check
        mock_rule_service.health_check.side_effect = Exception("Health check failed")
        
        health = await decision_api.health_check()
        
        assert health["service"] == "rate_limit_decision_api"
        assert health["status"] == "unhealthy"
        assert "error" in health
    
    def test_get_stats(self, decision_api):
        """Test getting operational statistics"""
        stats = decision_api.get_stats()
        
        assert stats["service"] == "rate_limit_decision_api"
        assert "timestamp" in stats
        assert "components" in stats
        assert stats["components"]["rule_management"] == "active"
        assert stats["components"]["redis_state"] == "active"
        assert stats["components"]["token_bucket"] == "active"
    
    def test_get_stats_with_circuit_breaker(self, decision_api, mock_redis_state_manager):
        """Test getting stats with circuit breaker information"""
        # Mock circuit breaker stats
        cb_stats = {
            "state": "closed",
            "total_requests": 100,
            "total_failures": 2,
            "failure_rate": 2.0
        }
        mock_redis_state_manager.redis_client_manager.get_circuit_breaker_stats.return_value = cb_stats
        
        stats = decision_api.get_stats()
        
        assert "circuit_breaker" in stats
        assert stats["circuit_breaker"]["state"] == "closed"
        assert stats["circuit_breaker"]["total_requests"] == 100


class TestRateLimitDecisionResult:
    """Test RateLimitDecisionResult dataclass"""
    
    def test_allowed_result(self):
        """Test creating allowed decision result"""
        result = RateLimitDecisionResult(
            allowed=True,
            remaining_tokens=50,
            reset_after_ms=30000
        )
        
        assert result.allowed is True
        assert result.remaining_tokens == 50
        assert result.reset_after_ms == 30000
        assert result.retry_after_ms is None
        assert result.rule_applied is None
        assert result.used_default_rule is False
        assert result.error_message is None
    
    def test_blocked_result(self):
        """Test creating blocked decision result"""
        result = RateLimitDecisionResult(
            allowed=False,
            retry_after_ms=5000
        )
        
        assert result.allowed is False
        assert result.retry_after_ms == 5000
        assert result.remaining_tokens is None
        assert result.reset_after_ms is None
    
    def test_error_result(self):
        """Test creating error decision result"""
        result = RateLimitDecisionResult(
            allowed=False,
            error_message="Something went wrong"
        )
        
        assert result.allowed is False
        assert result.error_message == "Something went wrong"