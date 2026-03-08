"""Unit tests for rule management API endpoints"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from rlaas.api import app, rlaas_app
from rlaas.models import RateLimitRule
from rlaas.rule_management import RuleValidationError


class TestRuleManagementAPI:
    """Test rule management API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_rule_service(self):
        """Create mock rule management service"""
        mock_service = MagicMock()
        mock_service.create_or_update_rule = AsyncMock()
        mock_service.get_rule = AsyncMock()
        mock_service.delete_rule = AsyncMock()
        mock_service.list_rules = AsyncMock()
        return mock_service
    
    @pytest.fixture
    def mock_decision_api(self, mock_rule_service):
        """Create mock decision API with rule service"""
        mock_api = MagicMock()
        mock_api.rule_management_service = mock_rule_service
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
    
    @pytest.fixture
    def test_rule_data(self):
        """Create test rule data"""
        return {
            "client_id": "client1",
            "endpoint": "/api/orders",
            "http_method": "POST",
            "limit": 100,
            "window_seconds": 60,
            "burst": 120
        }
    
    @pytest.fixture
    def test_rule(self, test_rule_data):
        """Create test rule object"""
        return RateLimitRule(**test_rule_data)
    
    def test_create_rule_success(self, client, mock_rule_service, test_rule_data):
        """Test successful rule creation"""
        # Mock successful rule creation
        mock_rule_service.create_or_update_rule.return_value = None
        
        response = client.post("/v1/rate-limit/rules", json=test_rule_data)
        
        assert response.status_code == 201
        data = response.json()
        
        assert data["message"] == "Rule created/updated successfully"
        assert data["rule"]["client_id"] == "client1"
        assert data["rule"]["endpoint"] == "/api/orders"
        assert data["rule"]["http_method"] == "POST"
        assert data["rule"]["limit"] == 100
        assert data["rule"]["window_seconds"] == 60
        assert data["rule"]["burst"] == 120
        assert "refill_rate" in data["rule"]
        assert "timestamp" in data
        
        # Verify service was called
        mock_rule_service.create_or_update_rule.assert_called_once()
        call_args = mock_rule_service.create_or_update_rule.call_args[0][0]
        assert call_args.client_id == "client1"
        assert call_args.endpoint == "/api/orders"
        assert call_args.http_method == "POST"
    
    def test_create_rule_validation_error(self, client, mock_rule_service):
        """Test rule creation with validation error"""
        # Mock validation error
        mock_rule_service.create_or_update_rule.side_effect = RuleValidationError(
            "Burst capacity must be >= limit"
        )
        
        rule_data = {
            "client_id": "client1",
            "endpoint": "/api/orders",
            "http_method": "POST",
            "limit": 100,
            "window_seconds": 60,
            "burst": 50  # Invalid: burst < limit
        }
        
        response = client.post("/v1/rate-limit/rules", json=rule_data)
        
        assert response.status_code == 400
        data = response.json()
        
        assert data["error"] == "rule_validation_error"
        assert "Burst capacity must be >= limit" in data["message"]
        assert "timestamp" in data
    
    def test_create_rule_invalid_json(self, client):
        """Test rule creation with invalid JSON"""
        response = client.post(
            "/v1/rate-limit/rules",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_create_rule_missing_fields(self, client):
        """Test rule creation with missing required fields"""
        rule_data = {
            "client_id": "client1",
            "endpoint": "/api/orders"
            # Missing http_method, limit, window_seconds, burst
        }
        
        response = client.post("/v1/rate-limit/rules", json=rule_data)
        
        assert response.status_code == 422  # Unprocessable Entity
        data = response.json()
        assert "detail" in data
    
    def test_create_rule_internal_error(self, client, mock_rule_service, test_rule_data):
        """Test rule creation with internal error"""
        # Mock internal error
        mock_rule_service.create_or_update_rule.side_effect = Exception("Redis connection failed")
        
        response = client.post("/v1/rate-limit/rules", json=test_rule_data)
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to create/update rule"
    
    def test_get_rule_success(self, client, mock_rule_service, test_rule):
        """Test successful rule retrieval"""
        # Mock successful rule retrieval
        mock_rule_service.get_rule.side_effect = [
            test_rule,  # First call (with fallback)
            test_rule   # Second call (without fallback)
        ]
        
        response = client.get(
            "/v1/rate-limit/rules/client1?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["rule"]["client_id"] == "client1"
        assert data["rule"]["endpoint"] == "/api/orders"
        assert data["rule"]["http_method"] == "POST"
        assert data["rule"]["limit"] == 100
        assert data["is_default_rule"] is False
        assert "timestamp" in data
        
        # Verify service was called correctly
        assert mock_rule_service.get_rule.call_count == 2
    
    def test_get_rule_default_fallback(self, client, mock_rule_service, test_rule):
        """Test rule retrieval with default fallback"""
        # Mock rule retrieval - specific rule not found, fallback succeeds
        mock_rule_service.get_rule.side_effect = [
            test_rule,  # First call (with fallback) succeeds
            None        # Second call (without fallback) returns None
        ]
        
        response = client.get(
            "/v1/rate-limit/rules/client1?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["rule"]["client_id"] == "client1"
        assert data["is_default_rule"] is True
        assert "timestamp" in data
    
    def test_get_rule_not_found(self, client, mock_rule_service):
        """Test rule retrieval when rule not found"""
        # Mock rule not found
        mock_rule_service.get_rule.return_value = None
        
        response = client.get(
            "/v1/rate-limit/rules/nonexistent?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Rule not found"
    
    def test_get_rule_missing_params(self, client):
        """Test rule retrieval with missing query parameters"""
        # Missing endpoint parameter
        response = client.get("/v1/rate-limit/rules/client1?http_method=POST")
        assert response.status_code == 422
        
        # Missing http_method parameter
        response = client.get("/v1/rate-limit/rules/client1?endpoint=/api/orders")
        assert response.status_code == 422
        
        # Missing both parameters
        response = client.get("/v1/rate-limit/rules/client1")
        assert response.status_code == 422
    
    def test_get_rule_internal_error(self, client, mock_rule_service):
        """Test rule retrieval with internal error"""
        # Mock internal error
        mock_rule_service.get_rule.side_effect = Exception("Redis connection failed")
        
        response = client.get(
            "/v1/rate-limit/rules/client1?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to retrieve rule"
    
    def test_delete_rule_success(self, client, mock_rule_service, test_rule):
        """Test successful rule deletion"""
        # Mock existing rule and successful deletion
        mock_rule_service.get_rule.return_value = test_rule
        mock_rule_service.delete_rule.return_value = None
        
        response = client.delete(
            "/v1/rate-limit/rules/client1?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["message"] == "Rule deleted successfully"
        assert data["deleted_rule"]["client_id"] == "client1"
        assert data["deleted_rule"]["endpoint"] == "/api/orders"
        assert data["deleted_rule"]["http_method"] == "POST"
        assert "timestamp" in data
        
        # Verify service was called correctly
        mock_rule_service.get_rule.assert_called_once_with(
            client_id="client1",
            endpoint="/api/orders",
            http_method="POST",
            use_default_fallback=False
        )
        mock_rule_service.delete_rule.assert_called_once_with(
            client_id="client1",
            endpoint="/api/orders",
            http_method="POST"
        )
    
    def test_delete_rule_not_found(self, client, mock_rule_service):
        """Test rule deletion when rule not found"""
        # Mock rule not found
        mock_rule_service.get_rule.return_value = None
        
        response = client.delete(
            "/v1/rate-limit/rules/nonexistent?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Rule not found"
        
        # Verify delete was not called
        mock_rule_service.delete_rule.assert_not_called()
    
    def test_delete_rule_missing_params(self, client):
        """Test rule deletion with missing query parameters"""
        # Missing endpoint parameter
        response = client.delete("/v1/rate-limit/rules/client1?http_method=POST")
        assert response.status_code == 422
        
        # Missing http_method parameter
        response = client.delete("/v1/rate-limit/rules/client1?endpoint=/api/orders")
        assert response.status_code == 422
        
        # Missing both parameters
        response = client.delete("/v1/rate-limit/rules/client1")
        assert response.status_code == 422
    
    def test_delete_rule_internal_error(self, client, mock_rule_service, test_rule):
        """Test rule deletion with internal error"""
        # Mock existing rule but deletion failure
        mock_rule_service.get_rule.return_value = test_rule
        mock_rule_service.delete_rule.side_effect = Exception("Redis connection failed")
        
        response = client.delete(
            "/v1/rate-limit/rules/client1?endpoint=/api/orders&http_method=POST"
        )
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to delete rule"
    
    def test_list_rules_success(self, client, mock_rule_service, test_rule):
        """Test successful rule listing"""
        # Mock rule listing
        mock_rules = [test_rule]
        mock_rule_service.list_rules.return_value = mock_rules
        
        response = client.get("/v1/rate-limit/rules")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["rules"]) == 1
        assert data["rules"][0]["client_id"] == "client1"
        assert data["rules"][0]["endpoint"] == "/api/orders"
        assert data["rules"][0]["http_method"] == "POST"
        assert data["pagination"]["limit"] == 100
        assert data["pagination"]["offset"] == 0
        assert data["pagination"]["total"] == 1
        assert "timestamp" in data
        
        # Verify service was called correctly
        mock_rule_service.list_rules.assert_called_once_with(
            client_id=None,
            endpoint=None,
            http_method=None,
            limit=100,
            offset=0
        )
    
    def test_list_rules_with_filters(self, client, mock_rule_service, test_rule):
        """Test rule listing with filters"""
        # Mock rule listing
        mock_rules = [test_rule]
        mock_rule_service.list_rules.return_value = mock_rules
        
        response = client.get(
            "/v1/rate-limit/rules?client_id=client1&endpoint=/api/orders&http_method=POST&limit=50&offset=10"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["filters"]["client_id"] == "client1"
        assert data["filters"]["endpoint"] == "/api/orders"
        assert data["filters"]["http_method"] == "POST"
        assert data["pagination"]["limit"] == 50
        assert data["pagination"]["offset"] == 10
        
        # Verify service was called with filters
        mock_rule_service.list_rules.assert_called_once_with(
            client_id="client1",
            endpoint="/api/orders",
            http_method="POST",
            limit=50,
            offset=10
        )
    
    def test_list_rules_empty(self, client, mock_rule_service):
        """Test rule listing when no rules exist"""
        # Mock empty rule list
        mock_rule_service.list_rules.return_value = []
        
        response = client.get("/v1/rate-limit/rules")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["rules"]) == 0
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["has_more"] is False
    
    def test_list_rules_pagination(self, client, mock_rule_service):
        """Test rule listing pagination"""
        # Mock full page of rules (indicating more available)
        mock_rules = [
            RateLimitRule(
                client_id=f"client{i}",
                endpoint="/api/test",
                http_method="GET",
                limit=100,
                window_seconds=60,
                burst=120
            )
            for i in range(50)  # Full page
        ]
        mock_rule_service.list_rules.return_value = mock_rules
        
        response = client.get("/v1/rate-limit/rules?limit=50")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["rules"]) == 50
        assert data["pagination"]["has_more"] is True  # Full page indicates more available
    
    def test_list_rules_internal_error(self, client, mock_rule_service):
        """Test rule listing with internal error"""
        # Mock internal error
        mock_rule_service.list_rules.side_effect = Exception("Redis connection failed")
        
        response = client.get("/v1/rate-limit/rules")
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Failed to list rules"


class TestRuleValidation:
    """Test rule validation in API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture(autouse=True)
    def setup_mock_container(self):
        """Setup mock container with decision API for all tests"""
        mock_api = MagicMock()
        mock_api.rule_management_service = MagicMock()
        mock_api.rule_management_service.create_or_update_rule = AsyncMock()
        
        mock_container = MagicMock()
        mock_container.decision_api = mock_api
        
        rlaas_app.container = mock_container
        rlaas_app._initialized = True
        yield
        # Cleanup
        rlaas_app.container = None
        rlaas_app._initialized = False
    
    def test_rule_validation_invalid_types(self, client):
        """Test rule validation with invalid field types"""
        invalid_rules = [
            {
                "client_id": 123,  # Should be string
                "endpoint": "/api/test",
                "http_method": "GET",
                "limit": 100,
                "window_seconds": 60,
                "burst": 120
            },
            {
                "client_id": "client1",
                "endpoint": 123,  # Should be string
                "http_method": "GET",
                "limit": 100,
                "window_seconds": 60,
                "burst": 120
            }
        ]
        
        for invalid_rule in invalid_rules:
            response = client.post("/v1/rate-limit/rules", json=invalid_rule)
            assert response.status_code == 422, f"Rule should be invalid: {invalid_rule}"
        
        # Note: FastAPI automatically converts string numbers to integers,
        # so "100" becomes 100, which is valid. This is expected behavior.
    
    def test_rule_validation_negative_values(self, client):
        """Test rule validation with negative values"""
        # Note: The actual validation happens in the RuleManagementService.
        # Since we're mocking the service, these tests verify the API structure
        # but not the actual validation logic. The validation is tested in
        # the rule management service tests.
        
        # Test that the API accepts the request structure (validation happens in service layer)
        rule_data = {
            "client_id": "client1",
            "endpoint": "/api/test",
            "http_method": "GET",
            "limit": -1,  # This would be caught by service validation in real usage
            "window_seconds": 60,
            "burst": 120
        }
        
        response = client.post("/v1/rate-limit/rules", json=rule_data)
        # With mocked service, this passes API validation but would fail in service layer
        assert response.status_code == 201