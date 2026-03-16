"""
Locust load test for RLaaS
Tests the rate limit check endpoint under load to validate the <10ms p99 SLA.

Run locally:
    pip install locust
    locust -f scripts/locustfile.py --host http://localhost:8000

Run headless (CI):
    locust -f scripts/locustfile.py --headless --users 100 --spawn-rate 10 --run-time 60s --host http://localhost:8000
"""

import random
from locust import HttpUser, task, between, events


# Sample client IDs and endpoints to simulate realistic traffic
CLIENT_IDS = [f"user_{i}" for i in range(1, 51)]  # 50 unique users
ENDPOINTS = ["/api/orders", "/api/products", "/api/search", "/api/cart", "/api/profile"]
HTTP_METHODS = ["GET", "POST", "PUT", "DELETE"]


class RLaaSUser(HttpUser):
    """Simulates a backend service calling RLaaS for rate limit decisions."""

    # Wait 10-50ms between requests (simulates realistic backend traffic)
    wait_time = between(0.01, 0.05)

    def on_start(self):
        """Called when a simulated user starts. Assign a fixed client identity."""
        self.client_id = random.choice(CLIENT_IDS)
        self.endpoint = random.choice(ENDPOINTS)

    @task(10)
    def check_rate_limit(self):
        """Main task: check rate limit (90% of traffic)."""
        payload = {
            "client_id": self.client_id,
            "endpoint": self.endpoint,
            "http_method": random.choice(HTTP_METHODS),
        }
        with self.client.post(
            "/v1/rate-limit/check",
            json=payload,
            catch_response=True,
            name="/v1/rate-limit/check",
        ) as response:
            if response.status_code in (200, 429):
                # Both ALLOW and BLOCK are valid responses
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def health_check(self):
        """Occasional health check (10% of traffic)."""
        self.client.get("/health", name="/health")


class RLaaSBurstUser(HttpUser):
    """Simulates burst traffic - sends requests as fast as possible."""

    wait_time = between(0.001, 0.005)  # Very fast, simulates burst

    def on_start(self):
        self.client_id = f"burst_user_{random.randint(1, 10)}"

    @task
    def burst_check(self):
        payload = {
            "client_id": self.client_id,
            "endpoint": "/api/orders",
            "http_method": "POST",
        }
        with self.client.post(
            "/v1/rate-limit/check",
            json=payload,
            catch_response=True,
            name="/v1/rate-limit/check [burst]",
        ) as response:
            if response.status_code in (200, 429):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Print summary when load test ends."""
    stats = environment.stats.total
    print("\n" + "=" * 50)
    print("LOAD TEST SUMMARY")
    print("=" * 50)
    print(f"Total Requests:    {stats.num_requests}")
    print(f"Failed Requests:   {stats.num_failures}")
    print(f"Avg Response Time: {stats.avg_response_time:.2f}ms")
    print(f"p50 Response Time: {stats.get_response_time_percentile(0.50):.2f}ms")
    print(f"p95 Response Time: {stats.get_response_time_percentile(0.95):.2f}ms")
    print(f"p99 Response Time: {stats.get_response_time_percentile(0.99):.2f}ms")
    print(f"Requests/sec:      {stats.current_rps:.2f}")
    print("=" * 50)

    # Fail if p99 exceeds 10ms SLA
    p99 = stats.get_response_time_percentile(0.99)
    if p99 > 10:
        print(f"\n❌ SLA VIOLATION: p99 {p99:.2f}ms exceeds 10ms target")
        environment.process_exit_code = 1
    else:
        print(f"\n✅ SLA MET: p99 {p99:.2f}ms is within 10ms target")
