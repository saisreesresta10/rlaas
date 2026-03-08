# Distributed Rate Limiter as a Service (RLaaS)

Product Design & Implementation Specification

Author Role:
Principal Software Engineer (Backend & Distributed Systems)

Ownership Model:
This system is designed as a production-owned backend service with assumptions of:
- On-call ownership
- Long-term maintainability
- Incremental evolution under real traffic

This is not a demo or academic exercise. Design decisions prioritize correctness, reliability, and operational simplicity.

------------------------------------------------------------
1. Problem Statement
------------------------------------------------------------

Modern distributed systems require consistent and centralized rate limiting across multiple backend services to prevent abuse, enforce fair usage, and protect downstream dependencies.

Implementing rate limiting independently in each service leads to:
- Inconsistent enforcement
- Operational complexity
- Difficulty in dynamic configuration

RLaaS solves this by acting as a centralized, low-latency decision service that provides real-time ALLOW/BLOCK decisions for incoming requests.

------------------------------------------------------------
2. Goals & Non-Goals
------------------------------------------------------------

Goals:
- Centralized rate limiting across distributed clients
- Low-latency decision making (<10ms p99)
- Horizontal scalability
- Strong consistency for enforcement
- Operational visibility and fault tolerance

Non-Goals:
- API gateway replacement
- Authentication or authorization
- Billing or quota management

------------------------------------------------------------
3. Assumptions & Scale
------------------------------------------------------------

- Millions of requests per day
- Multiple backend services as clients
- Stateless API servers
- Shared centralized state
- Strict latency and availability requirements

------------------------------------------------------------
4. High-Level Architecture
------------------------------------------------------------

Architecture Overview:
- Stateless FastAPI servers
- Redis as shared distributed state
- Load-balancer friendly deployment
- Horizontal scaling at API layer

Flow:
Clients → Load Balancer → RLaaS API → Redis

Design Rationale:
- Stateless APIs enable easy horizontal scaling
- Redis provides low-latency atomic state management
- Clear separation between decision logic and storage

------------------------------------------------------------
5. Rate Limiting Strategy
------------------------------------------------------------

Algorithm: Token Bucket

Rationale:
- Supports burst traffic
- Simple and predictable behavior
- Widely used in production systems

Core Concepts:
- Tokens refill at a fixed rate
- Each request consumes a token
- Requests are blocked when tokens are exhausted

Comparison:
- Leaky Bucket: Smooths traffic but limits bursts
- Sliding Window: More precise but higher computation cost
- Token Bucket: Best balance of simplicity and flexibility

------------------------------------------------------------
6. Distributed State Management
------------------------------------------------------------

State Store:
Redis

Key Requirements:
- Atomic updates
- Consistent enforcement across nodes
- Minimal Redis round trips

Key Pattern:
rate_limit:{client_id}:{endpoint}:{http_method}

State Stored:
- Current token count
- Last refill timestamp
- Rate configuration metadata

Concurrency Handling:
- Redis atomic operations
- Lua scripts for refill and consumption
- Prevents race conditions and double counting

------------------------------------------------------------
7. API Design
------------------------------------------------------------

7.1 Check Rate Limit
POST /v1/rate-limit/check

Request:
{
  "client_id": "user_123",
  "endpoint": "/orders",
  "http_method": "POST"
}

Allowed Response:
{
  "allowed": true,
  "remaining_tokens": 42,
  "reset_after_ms": 12000
}

Blocked Response:
{
  "allowed": false,
  "retry_after_ms": 3000
}

------------------------------------------------------------

7.2 Configure Rate Limit Rule
POST /v1/rate-limit/rules

Request:
{
  "client_id": "user_123",
  "endpoint": "/orders",
  "limit": 100,
  "window_seconds": 60,
  "burst": 20
}

Rules are applied dynamically without service restarts.

------------------------------------------------------------
8. Non-Functional Requirements
------------------------------------------------------------

Latency:
- <10ms p99 for rate-limit checks

Availability:
- Graceful degradation on partial failures
- No cascading failures to clients

Consistency:
- Strong consistency for token updates
- Abuse prevention under concurrent access

Cost Efficiency:
- Single atomic Redis operation per request
- Minimal memory footprint

------------------------------------------------------------
9. Failure Handling
------------------------------------------------------------

Redis Unavailability:
- Configurable fail-open or fail-closed behavior
- Timeouts and retries
- Circuit breaker to prevent cascading failures

Network Latency:
- Strict request timeouts
- Controlled retry behavior

------------------------------------------------------------
10. Observability & Operations
------------------------------------------------------------

Metrics:
- Total requests
- Blocked requests
- Redis latency
- Error rates

Health Check:
GET /health

Logging:
- Structured logs
- Decision outcomes
- Error conditions

------------------------------------------------------------
11. Testing Strategy
------------------------------------------------------------

Unit Tests:
- Token bucket refill logic
- Burst handling
- Edge cases (zero tokens, exact limits)

Integration Tests:
- Redis atomicity
- Concurrent request handling
- Dynamic rule updates

Load Tests:
- 10k+ requests per minute
- Validate latency SLA
- Verify correctness under load

Failure Tests:
- Redis downtime
- Network delays
- Partial outages

------------------------------------------------------------
12. Technology Stack
------------------------------------------------------------

- Language: Python
- Framework: FastAPI
- State Store: Redis
- Containerization: Docker
- Deployment: AWS EC2
- CI/CD: GitHub Actions
- Testing: pytest

------------------------------------------------------------
13. Phased Delivery Plan
------------------------------------------------------------

Phase 1 – Core System:
- Token Bucket logic
- Redis shared state
- Rate-limit check API
- Static rule configuration
- Unit and basic integration tests

Phase 2 – Reliability & Scale:
- Lua scripts for atomicity
- Dynamic rule updates
- Metrics and health checks
- Redis failure handling

Phase 3 – Production Hardening:
- Load testing
- Circuit breaker behavior
- Advanced observability

------------------------------------------------------------
14. Future Evolution
------------------------------------------------------------

- Multi-region Redis replication
- Client-side caching hints
- Per-tier rate limits
- API gateway integration
- Cost-aware rate limiting strategies

------------------------------------------------------------
15. Summary
------------------------------------------------------------

RLaaS is designed as a production-grade backend system with:
- Clear ownership boundaries
- Strong consistency guarantees
- Scalable architecture
- Operational visibility
- Incremental delivery strategy

The design balances correctness, performance, and maintainability, making it suitable for real-world deployment and long-term ownership.