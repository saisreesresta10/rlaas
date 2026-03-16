"""
SLA Validation Script
Reads Locust CSV output and validates the <10ms p99 latency SLA.

Usage:
    python scripts/validate_sla.py load-test-results_stats.csv
"""

import sys
import csv


P99_SLA_MS = 10.0       # p99 must be under 10ms
FAILURE_RATE_MAX = 0.01  # Max 1% failure rate
MIN_RPS = 100            # Minimum requests per second expected


def validate(csv_path: str) -> bool:
    passed = True

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Find the aggregated row
    total_row = next((r for r in rows if r["Name"] == "Aggregated"), None)
    if not total_row:
        print("❌ Could not find Aggregated row in CSV")
        return False

    total_requests = int(total_row["Request Count"])
    failures = int(total_row["Failure Count"])
    p99 = float(total_row["99%"])
    p95 = float(total_row["95%"])
    avg = float(total_row["Average (ms)"])
    rps = float(total_row["Requests/s"])

    print("\n" + "=" * 55)
    print("  LOAD TEST SLA VALIDATION REPORT")
    print("=" * 55)
    print(f"  Total Requests : {total_requests:,}")
    print(f"  Failures       : {failures:,}")
    print(f"  Avg Latency    : {avg:.2f}ms")
    print(f"  p95 Latency    : {p95:.2f}ms")
    print(f"  p99 Latency    : {p99:.2f}ms   (SLA: <{P99_SLA_MS}ms)")
    print(f"  Requests/sec   : {rps:.2f}      (Min: {MIN_RPS})")
    print("-" * 55)

    # Check p99 SLA
    if p99 <= P99_SLA_MS:
        print(f"  ✅ p99 latency {p99:.2f}ms — PASS")
    else:
        print(f"  ❌ p99 latency {p99:.2f}ms exceeds {P99_SLA_MS}ms — FAIL")
        passed = False

    # Check failure rate
    failure_rate = failures / total_requests if total_requests > 0 else 0
    if failure_rate <= FAILURE_RATE_MAX:
        print(f"  ✅ Failure rate {failure_rate:.2%} — PASS")
    else:
        print(f"  ❌ Failure rate {failure_rate:.2%} exceeds {FAILURE_RATE_MAX:.0%} — FAIL")
        passed = False

    # Check throughput
    if rps >= MIN_RPS:
        print(f"  ✅ Throughput {rps:.0f} req/s — PASS")
    else:
        print(f"  ❌ Throughput {rps:.0f} req/s below {MIN_RPS} req/s — FAIL")
        passed = False

    print("=" * 55)
    print(f"\n  Overall: {'✅ ALL SLAs MET' if passed else '❌ SLA VIOLATIONS FOUND'}")
    print()

    return passed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_sla.py <csv_path>")
        sys.exit(1)

    ok = validate(sys.argv[1])
    sys.exit(0 if ok else 1)
