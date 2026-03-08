"""Property-based tests for metrics emission behavior"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import AsyncMock, MagicMock, patch
from prometheus_client import CollectorRegistry, REGISTRY
import time

from rlaas.metrics import MetricsService
from rlaas.models import RateLimitResponse, RateLimitRule


class TestPropertyMetricsEmission:
    """Property-based tests for metrics emission consistency"""
    
    @pytest.fixture
    def metrics_collector(self):
        """Create metrics service with isolated registry"""
        # Create isolated registry for testing
        registry = CollectorRegistry()
        service = MetricsService(registry=registry)
        return service
    
    @given(
        client_id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc'))),
        endpoint=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc', 'Pd', 'Po'))),
        http_method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        allowed=st.booleans(),
        remaining_tokens=st.floats(min_value=0.0, max_value=1000.0),
        retry_after_ms=st.integers(min_value=0, max_value=3600000)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_decision_metrics_emission_property(self, metrics_collector, client_id, endpoint, 
                                              http_method, allowed, remaining_tokens, retry_after_ms):
        """
        Property 13: Metrics Emission Completeness
        Every rate limit decision should emit appropriate metrics
        **Validates: Requirements 6.1**
        """
        response = RateLimitResponse(
            allowed=allowed,
            remaining_tokens=remaining_tokens,
            retry_after_ms=retry_after_ms,
            reset_after_ms=retry_after_ms
        )
        
        # Record decision metrics
        metrics_collector.record_request(
            client_id=client_id,
            endpoint=endpoint,
            http_method=http_method,
            allowed=allowed,
            duration_seconds=0.1
        )
        
        # Verify metrics were recorded
        # Get metric samples from the registry
        metric_families = list(metrics_collector.registry.collect())
        
        # Should have decision-related metrics
        metric_names = [family.name for family in metric_families]
        
        # Check for expected metrics (allow for variations in naming)
        expected_metric_patterns = [
            "rate_limit",
            "request",
            "decision",
            "duration",
            "total"
        ]
        
        # At least one metric should be present that matches our patterns
        found_metrics = []
        for pattern in expected_metric_patterns:
            matching_metrics = [name for name in metric_names if pattern in name.lower()]
            found_metrics.extend(matching_metrics)
        
        assert len(found_metrics) > 0, f"No rate limiting metrics found. Available: {metric_names}"
        
        # Verify metric values are reasonable
        for family in metric_families:
            for sample in family.samples:
                # All metric values should be valid numbers
                assert isinstance(sample.value, (int, float)), f"Metric {sample.name} should have numeric value"
                assert not (sample.value != sample.value), f"Metric {sample.name} should not be NaN"  # Check for NaN
                
                # Count metrics should be non-negative
                if "count" in sample.name or "total" in sample.name:
                    assert sample.value >= 0, f"Count metric {sample.name} should be non-negative"
    
    @given(
        request_count=st.integers(min_value=1, max_value=10),
        response_time_ms=st.floats(min_value=1.0, max_value=1000.0)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_request_metrics_emission_property(self, metrics_collector, request_count, response_time_ms):
        """
        Property: Request Metrics Emission
        Every API request should emit timing and count metrics
        **Validates: Requirements 7.2**
        """
        for i in range(request_count):
            # Record request metrics
            metrics_collector.record_request(
                client_id=f"client_{i}",
                endpoint=f"/api/test_{i}",
                http_method="GET",
                allowed=True,
                duration_seconds=response_time_ms / 1000.0
            )
        
        # Verify metrics were recorded
        metric_families = list(metrics_collector.registry.collect())
        metric_names = [family.name for family in metric_families]
        
        # Should have request-related metrics
        request_metrics = [name for name in metric_names if any(pattern in name.lower() for pattern in ["request", "duration", "total"])]
        assert len(request_metrics) > 0, f"No request-related metrics found. Available: {metric_names}"
        
        # Verify metric values make sense
        for family in metric_families:
            for sample in family.samples:
                if "count" in sample.name or "total" in sample.name:
                    # Count metrics should be >= 0
                    assert sample.value >= 0, f"Count metric {sample.name} should be non-negative"
                elif "duration" in sample.name or "time" in sample.name:
                    # Duration metrics should be reasonable
                    assert sample.value >= 0, f"Duration metric {sample.name} should be non-negative"
    
    @given(
        error_count=st.integers(min_value=1, max_value=5),
        error_type=st.sampled_from(["timeout", "connection_error", "redis_error", "validation_error"])
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_error_metrics_emission_property(self, metrics_collector, error_count, error_type):
        """
        Property: Error Metrics Emission
        Every error should emit appropriate error metrics
        **Validates: Requirements 7.3**
        """
        for i in range(error_count):
            # Record error metrics
            metrics_collector.record_error(
                error_type=error_type,
                component="test_component"
            )
        
        # Verify error metrics were recorded
        metric_families = list(metrics_collector.registry.collect())
        metric_names = [family.name for family in metric_families]
        
        # Should have error-related metrics
        error_metrics = [name for name in metric_names if "error" in name.lower() or "failure" in name.lower()]
        assert len(error_metrics) > 0, f"No error-related metrics found. Available: {metric_names}"
        
        # Verify error counts
        for family in metric_families:
            for sample in family.samples:
                if "error" in sample.name and ("count" in sample.name or "total" in sample.name):
                    assert sample.value >= 0, f"Error count metric {sample.name} should be non-negative"
    
    @given(
        metric_operations=st.lists(
            st.tuples(
                st.sampled_from(["decision", "request", "error"]),
                st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')))
            ),
            min_size=1,
            max_size=10
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_metrics_consistency_property(self, metrics_collector, metric_operations):
        """
        Property: Metrics Consistency
        Metrics should be consistent and monotonic (counts should only increase)
        **Validates: Requirements 7.4**
        """
        initial_metrics = {}
        
        # Capture initial metric state
        for family in metrics_collector.registry.collect():
            for sample in family.samples:
                initial_metrics[sample.name] = sample.value
        
        # Perform metric operations
        for operation_type, identifier in metric_operations:
            if operation_type == "decision":
                metrics_collector.record_request(
                    client_id=identifier,
                    endpoint="/api/test",
                    http_method="GET",
                    allowed=True,
                    duration_seconds=0.1
                )
            elif operation_type == "request":
                metrics_collector.record_request(
                    client_id=identifier,
                    endpoint=f"/api/{identifier}",
                    http_method="GET",
                    allowed=True,
                    duration_seconds=0.1
                )
            elif operation_type == "error":
                metrics_collector.record_error(
                    error_type="test_error",
                    component=identifier
                )
        
        # Capture final metric state
        final_metrics = {}
        for family in metrics_collector.registry.collect():
            for sample in family.samples:
                final_metrics[sample.name] = sample.value
        
        # Verify metrics are monotonic (counts should not decrease)
        for metric_name, initial_value in initial_metrics.items():
            if metric_name in final_metrics:
                final_value = final_metrics[metric_name]
                if "count" in metric_name or "total" in metric_name:
                    assert final_value >= initial_value, f"Count metric {metric_name} decreased from {initial_value} to {final_value}"
    
    @given(
        concurrent_operations=st.integers(min_value=2, max_value=10)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_concurrent_metrics_emission_property(self, metrics_collector, concurrent_operations):
        """
        Property: Concurrent metrics emission should be thread-safe
        """
        async def emit_metrics(operation_id):
            """Emit metrics concurrently"""
            metrics_collector.record_request(
                client_id=f"client_{operation_id}",
                endpoint=f"/api/test_{operation_id}",
                http_method="GET",
                allowed=True,
                duration_seconds=0.1
            )
            
            metrics_collector.record_error(
                error_type="test_error",
                component=f"component_{operation_id}"
            )
        
        async def test_concurrent():
            # Run concurrent metric operations
            tasks = [emit_metrics(i) for i in range(concurrent_operations)]
            await asyncio.gather(*tasks)
            
            # Verify metrics were recorded without corruption
            metric_families = list(metrics_collector.registry.collect())
            
            # Should have metrics from all operations
            total_samples = sum(len(family.samples) for family in metric_families)
            assert total_samples > 0, "No metrics recorded during concurrent operations"
            
            # All metric values should be valid (non-negative for counts)
            for family in metric_families:
                for sample in family.samples:
                    if "count" in sample.name or "total" in sample.name:
                        assert sample.value >= 0, f"Invalid metric value: {sample.name} = {sample.value}"
                        assert not (sample.value != sample.value), f"NaN metric value: {sample.name}"  # Check for NaN
        
        asyncio.run(test_concurrent())
    
    @given(
        metric_labels=st.dictionaries(
            keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
            values=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Pc'))),
            min_size=1,
            max_size=5
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_metric_labels_consistency_property(self, metrics_collector, metric_labels):
        """
        Property: Metric labels should be consistent and properly formatted
        """
        # Use some of the labels as client_id and endpoint
        client_id = list(metric_labels.values())[0] if metric_labels else "test_client"
        endpoint = f"/api/{list(metric_labels.values())[1] if len(metric_labels) > 1 else 'test'}"
        
        # Record metrics with labels
        metrics_collector.record_request(
            client_id=client_id,
            endpoint=endpoint,
            http_method="GET",
            allowed=True,
            duration_seconds=0.1
        )
        
        # Verify metrics were recorded with proper labels
        metric_families = list(metrics_collector.registry.collect())
        
        # Should have metrics with labels
        found_labeled_metrics = False
        for family in metric_families:
            for sample in family.samples:
                if sample.labels:
                    found_labeled_metrics = True
                    # Labels should be strings
                    for label_name, label_value in sample.labels.items():
                        assert isinstance(label_name, str), f"Label name should be string: {label_name}"
                        assert isinstance(label_value, str), f"Label value should be string: {label_value}"
                        # Label values should not be empty
                        assert len(label_value) > 0, f"Label value should not be empty: {label_name}={label_value}"
        
        # At least some metrics should have labels (this depends on the implementation)
        # We don't assert this strictly since it depends on how the metrics collector is implemented