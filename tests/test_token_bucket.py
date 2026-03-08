"""Unit tests for TokenBucketService"""

import pytest
import time
from unittest.mock import patch

from rlaas.token_bucket import TokenBucketService
from rlaas.models import RateLimitRule, TokenBucketState, TokenBucketResult


class TestTokenBucketService:
    """Test TokenBucketService functionality"""
    
    @pytest.fixture
    def service(self):
        """Create TokenBucketService instance"""
        return TokenBucketService()
    
    @pytest.fixture
    def sample_rule(self):
        """Create sample rate limit rule"""
        return RateLimitRule(
            client_id="user_123",
            endpoint="/api/orders",
            http_method="POST",
            limit=100,  # 100 requests per window
            window_seconds=60,  # 60 second window
            burst=120  # 120 token burst capacity
        )
    
    def test_create_initial_bucket_state(self, service, sample_rule):
        """Test creating initial bucket state"""
        current_time = 1640995200.0
        
        state = service.create_initial_bucket_state(sample_rule, current_time)
        
        assert state.tokens == 120.0  # Should start with full burst capacity
        assert state.last_refill == current_time
        assert state.rule == sample_rule
    
    def test_create_initial_bucket_state_default_time(self, service, sample_rule):
        """Test creating initial bucket state with default time"""
        with patch('time.time', return_value=1640995200.0):
            state = service.create_initial_bucket_state(sample_rule)
            
            assert state.tokens == 120.0
            assert state.last_refill == 1640995200.0
    
    def test_refill_tokens_no_time_elapsed(self, service, sample_rule):
        """Test refill when no time has elapsed"""
        current_time = 1640995200.0
        initial_state = TokenBucketState(
            tokens=50.0,
            last_refill=current_time,
            rule=sample_rule
        )
        
        new_state = service.refill_tokens(initial_state, current_time)
        
        assert new_state.tokens == 50.0  # No change
        assert new_state.last_refill == current_time
    
    def test_refill_tokens_partial_refill(self, service, sample_rule):
        """Test partial token refill"""
        initial_time = 1640995200.0
        current_time = initial_time + 30.0  # 30 seconds later
        
        initial_state = TokenBucketState(
            tokens=50.0,
            last_refill=initial_time,
            rule=sample_rule
        )
        
        new_state = service.refill_tokens(initial_state, current_time)
        
        # Should add 50 tokens (100/60 * 30 = 50)
        expected_tokens = 50.0 + 50.0
        assert new_state.tokens == pytest.approx(expected_tokens, rel=1e-9)
        assert new_state.last_refill == current_time
    
    def test_refill_tokens_capped_at_burst(self, service, sample_rule):
        """Test refill is capped at burst capacity"""
        initial_time = 1640995200.0
        current_time = initial_time + 120.0  # 2 minutes later
        
        initial_state = TokenBucketState(
            tokens=100.0,
            last_refill=initial_time,
            rule=sample_rule
        )
        
        new_state = service.refill_tokens(initial_state, current_time)
        
        # Should be capped at burst capacity (120)
        assert new_state.tokens == 120.0
        assert new_state.last_refill == current_time
    
    def test_refill_tokens_negative_time_elapsed(self, service, sample_rule):
        """Test refill handles negative time elapsed gracefully"""
        initial_time = 1640995200.0
        current_time = initial_time - 10.0  # Time went backwards
        
        initial_state = TokenBucketState(
            tokens=50.0,
            last_refill=initial_time,
            rule=sample_rule
        )
        
        new_state = service.refill_tokens(initial_state, current_time)
        
        # Should not change tokens when time goes backwards
        assert new_state.tokens == 50.0
        assert new_state.last_refill == current_time
    
    def test_can_consume_tokens_sufficient(self, service, sample_rule):
        """Test can consume when sufficient tokens available"""
        state = TokenBucketState(
            tokens=10.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        assert service.can_consume_tokens(state, 1) is True
        assert service.can_consume_tokens(state, 10) is True
    
    def test_can_consume_tokens_insufficient(self, service, sample_rule):
        """Test can consume when insufficient tokens available"""
        state = TokenBucketState(
            tokens=5.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        assert service.can_consume_tokens(state, 6) is False
        assert service.can_consume_tokens(state, 10) is False
    
    def test_can_consume_tokens_exact_match(self, service, sample_rule):
        """Test can consume when exact tokens available"""
        state = TokenBucketState(
            tokens=5.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        assert service.can_consume_tokens(state, 5) is True
    
    def test_consume_tokens_success(self, service, sample_rule):
        """Test successful token consumption"""
        initial_state = TokenBucketState(
            tokens=10.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        new_state = service.consume_tokens(initial_state, 3)
        
        assert new_state.tokens == 7.0
        assert new_state.last_refill == initial_state.last_refill
        assert new_state.rule == initial_state.rule
    
    def test_consume_tokens_insufficient(self, service, sample_rule):
        """Test token consumption with insufficient tokens"""
        state = TokenBucketState(
            tokens=2.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        with pytest.raises(ValueError, match="Insufficient tokens"):
            service.consume_tokens(state, 5)
    
    def test_process_token_request_success(self, service, sample_rule):
        """Test successful token request processing"""
        current_time = 1640995200.0
        initial_state = TokenBucketState(
            tokens=50.0,
            last_refill=current_time - 30.0,  # 30 seconds ago
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(initial_state, 1, current_time)
        
        # Should succeed after refill (50 + 50 tokens from refill)
        assert result.success is True
        assert result.remaining_tokens == 99  # 100 - 1 consumed
        assert result.retry_after_ms is None
        assert result.reset_after_ms is not None
        
        # Final state should have consumed 1 token
        assert final_state.tokens == 99.0
        assert final_state.last_refill == current_time
    
    def test_process_token_request_blocked(self, service, sample_rule):
        """Test blocked token request processing"""
        current_time = 1640995200.0
        initial_state = TokenBucketState(
            tokens=0.5,  # Less than 1 token
            last_refill=current_time,  # No refill
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(initial_state, 1, current_time)
        
        # Should be blocked
        assert result.success is False
        assert result.remaining_tokens == 0  # Floor of 0.5
        assert result.retry_after_ms is not None
        assert result.reset_after_ms is None
        
        # State should be unchanged (no consumption)
        assert final_state.tokens == 0.5
        assert final_state.last_refill == current_time
    
    def test_process_token_request_with_refill_success(self, service, sample_rule):
        """Test token request that succeeds after refill"""
        initial_time = 1640995200.0
        current_time = initial_time + 60.0  # 1 minute later
        
        initial_state = TokenBucketState(
            tokens=0.0,  # Empty bucket
            last_refill=initial_time,
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(initial_state, 1, current_time)
        
        # Should succeed after refill (0 + 100 tokens from 1 minute refill)
        assert result.success is True
        assert result.remaining_tokens == 99  # 100 - 1 consumed
        assert final_state.tokens == 99.0
    
    def test_calculate_time_until_tokens_available_immediate(self, service, sample_rule):
        """Test time calculation when tokens already available"""
        state = TokenBucketState(
            tokens=10.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        wait_time = service.calculate_time_until_tokens_available(state, 5)
        assert wait_time == 0.0
    
    def test_calculate_time_until_tokens_available_wait_needed(self, service, sample_rule):
        """Test time calculation when waiting is needed"""
        state = TokenBucketState(
            tokens=2.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        wait_time = service.calculate_time_until_tokens_available(state, 5)
        # Need 3 more tokens, rate is 100/60 = 1.667 tokens/sec
        # So wait time should be 3 / 1.667 = 1.8 seconds
        expected_time = 3.0 / (100.0 / 60.0)
        assert wait_time == pytest.approx(expected_time, rel=1e-9)
    
    def test_calculate_time_until_full_already_full(self, service, sample_rule):
        """Test time until full when bucket is already full"""
        state = TokenBucketState(
            tokens=120.0,  # Full burst capacity
            last_refill=time.time(),
            rule=sample_rule
        )
        
        wait_time = service.calculate_time_until_full(state)
        assert wait_time == 0.0
    
    def test_calculate_time_until_full_partial(self, service, sample_rule):
        """Test time until full when bucket is partially full"""
        state = TokenBucketState(
            tokens=70.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        wait_time = service.calculate_time_until_full(state)
        # Need 50 more tokens, rate is 100/60 = 1.667 tokens/sec
        # So wait time should be 50 / 1.667 = 30 seconds
        expected_time = 50.0 / (100.0 / 60.0)
        assert wait_time == pytest.approx(expected_time, rel=1e-9)
    
    def test_get_bucket_info(self, service, sample_rule):
        """Test getting comprehensive bucket information"""
        current_time = 1640995200.0
        initial_time = current_time - 30.0
        
        state = TokenBucketState(
            tokens=50.0,
            last_refill=initial_time,
            rule=sample_rule
        )
        
        info = service.get_bucket_info(state, current_time)
        
        # Should include refilled tokens (50 + 50 = 100)
        assert info["current_tokens"] == 100.0
        assert info["max_tokens"] == 120
        assert info["refill_rate"] == pytest.approx(100.0 / 60.0, rel=1e-9)
        assert info["last_refill"] == current_time
        assert info["time_until_full"] == pytest.approx(12.0, rel=1e-9)  # 20 tokens / (100/60) rate
        
        # Check rule information
        assert info["rule"]["client_id"] == "user_123"
        assert info["rule"]["endpoint"] == "/api/orders"
        assert info["rule"]["http_method"] == "POST"
        assert info["rule"]["limit"] == 100
        assert info["rule"]["window_seconds"] == 60
        assert info["rule"]["burst"] == 120
    
    def test_edge_case_zero_tokens_requested(self, service, sample_rule):
        """Test edge case with zero tokens requested"""
        state = TokenBucketState(
            tokens=10.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(state, 0)
        
        # Should succeed without consuming any tokens
        assert result.success is True
        assert result.remaining_tokens == 10
        assert final_state.tokens == 10.0
    
    def test_edge_case_fractional_tokens(self, service, sample_rule):
        """Test handling of fractional tokens"""
        current_time = 1640995200.0
        initial_time = current_time - 1.5  # 1.5 seconds ago
        
        initial_state = TokenBucketState(
            tokens=0.0,
            last_refill=initial_time,
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(initial_state, 1, current_time)
        
        # Should add 1.5 * (100/60) = 2.5 tokens, then consume 1
        assert result.success is True
        assert final_state.tokens == pytest.approx(1.5, rel=1e-9)
    
    def test_multiple_token_consumption(self, service, sample_rule):
        """Test consuming multiple tokens at once"""
        state = TokenBucketState(
            tokens=10.0,
            last_refill=time.time(),
            rule=sample_rule
        )
        
        result, final_state = service.process_token_request(state, 5)
        
        assert result.success is True
        assert result.remaining_tokens == 5
        assert final_state.tokens == 5.0