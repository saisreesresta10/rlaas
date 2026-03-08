"""Lua scripts for atomic Redis operations"""

# Token bucket refill and consume script
# This script atomically refills tokens based on elapsed time and attempts to consume tokens
TOKEN_BUCKET_REFILL_AND_CONSUME = """
-- Token bucket refill and consume script
-- KEYS[1]: bucket key
-- ARGV[1]: current timestamp (float)
-- ARGV[2]: refill rate (tokens per second, float)
-- ARGV[3]: burst capacity (int)
-- ARGV[4]: tokens to consume (int)
-- ARGV[5]: TTL for the key (seconds, int)

local bucket_key = KEYS[1]
local current_time = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local burst_capacity = tonumber(ARGV[3])
local tokens_to_consume = tonumber(ARGV[4])
local ttl_seconds = tonumber(ARGV[5])

-- Get current bucket state
local bucket_data = redis.call('GET', bucket_key)
local tokens, last_refill

if bucket_data then
    -- Parse existing bucket state
    local state = cjson.decode(bucket_data)
    tokens = tonumber(state.tokens)
    last_refill = tonumber(state.last_refill)
else
    -- Initialize new bucket with full burst capacity
    tokens = burst_capacity
    last_refill = current_time
end

-- Calculate refill based on elapsed time
local time_elapsed = math.max(0, current_time - last_refill)
local tokens_to_add = refill_rate * time_elapsed
tokens = math.min(tokens + tokens_to_add, burst_capacity)

-- Check if consumption is possible
if tokens >= tokens_to_consume then
    -- Consume tokens
    tokens = tokens - tokens_to_consume
    
    -- Update bucket state with new values
    local new_state = {
        tokens = tokens,
        last_refill = current_time
    }
    
    -- Store updated state with TTL
    redis.call('SETEX', bucket_key, ttl_seconds, cjson.encode(new_state))
    
    -- Return success with remaining tokens
    return {1, math.floor(tokens)}
else
    -- Update bucket state without consumption (just refill)
    local new_state = {
        tokens = tokens,
        last_refill = current_time
    }
    
    -- Store updated state with TTL
    redis.call('SETEX', bucket_key, ttl_seconds, cjson.encode(new_state))
    
    -- Return failure with current tokens
    return {0, math.floor(tokens)}
end
"""

# Token bucket state retrieval and refill script
# This script retrieves current state and applies refill without consumption
TOKEN_BUCKET_GET_AND_REFILL = """
-- Token bucket get and refill script (no consumption)
-- KEYS[1]: bucket key
-- ARGV[1]: current timestamp (float)
-- ARGV[2]: refill rate (tokens per second, float)
-- ARGV[3]: burst capacity (int)
-- ARGV[4]: TTL for the key (seconds, int)

local bucket_key = KEYS[1]
local current_time = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local burst_capacity = tonumber(ARGV[3])
local ttl_seconds = tonumber(ARGV[4])

-- Get current bucket state
local bucket_data = redis.call('GET', bucket_key)
local tokens, last_refill

if bucket_data then
    -- Parse existing bucket state
    local state = cjson.decode(bucket_data)
    tokens = tonumber(state.tokens)
    last_refill = tonumber(state.last_refill)
else
    -- Initialize new bucket with full burst capacity
    tokens = burst_capacity
    last_refill = current_time
end

-- Calculate refill based on elapsed time
local time_elapsed = math.max(0, current_time - last_refill)
local tokens_to_add = refill_rate * time_elapsed
tokens = math.min(tokens + tokens_to_add, burst_capacity)

-- Update bucket state with refilled tokens
local new_state = {
    tokens = tokens,
    last_refill = current_time
}

-- Store updated state with TTL
redis.call('SETEX', bucket_key, ttl_seconds, cjson.encode(new_state))

-- Return current tokens after refill
return math.floor(tokens)
"""

# Batch token bucket operations script
# This script can handle multiple bucket operations in a single atomic transaction
BATCH_TOKEN_BUCKET_OPERATIONS = """
-- Batch token bucket operations script
-- KEYS: bucket keys (variable number)
-- ARGV[1]: current timestamp (float)
-- ARGV[2]: number of operations
-- ARGV[3+]: operation data (refill_rate, burst_capacity, tokens_to_consume, ttl_seconds) repeated for each operation

local current_time = tonumber(ARGV[1])
local num_operations = tonumber(ARGV[2])
local results = {}

for i = 1, num_operations do
    local bucket_key = KEYS[i]
    local base_index = 3 + (i - 1) * 4
    local refill_rate = tonumber(ARGV[base_index])
    local burst_capacity = tonumber(ARGV[base_index + 1])
    local tokens_to_consume = tonumber(ARGV[base_index + 2])
    local ttl_seconds = tonumber(ARGV[base_index + 3])
    
    -- Get current bucket state
    local bucket_data = redis.call('GET', bucket_key)
    local tokens, last_refill
    
    if bucket_data then
        local state = cjson.decode(bucket_data)
        tokens = tonumber(state.tokens)
        last_refill = tonumber(state.last_refill)
    else
        tokens = burst_capacity
        last_refill = current_time
    end
    
    -- Calculate refill
    local time_elapsed = math.max(0, current_time - last_refill)
    local tokens_to_add = refill_rate * time_elapsed
    tokens = math.min(tokens + tokens_to_add, burst_capacity)
    
    -- Check if consumption is possible
    local success = 0
    if tokens >= tokens_to_consume then
        tokens = tokens - tokens_to_consume
        success = 1
    end
    
    -- Update bucket state
    local new_state = {
        tokens = tokens,
        last_refill = current_time
    }
    redis.call('SETEX', bucket_key, ttl_seconds, cjson.encode(new_state))
    
    -- Store result
    results[i] = {success, math.floor(tokens)}
end

return results
"""