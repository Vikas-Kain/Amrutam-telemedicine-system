"""Repeatable performance benchmarking script for Amrutam Telemedicine backend.

Executes a controlled concurrent workload against real database sessions and API routing,
calculates p50/p90/p95/p99 latency percentiles, throughput (RPS), and error rates,
and guarantees synthetic data cleanup.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from app.db.session import get_session_factory
from app.main import create_app
from tests.performance.data_seeder import (
    PerformanceDataset,
    cleanup_performance_dataset,
    seed_performance_dataset,
)


@dataclass
class EndpointStats:
    """Statistics for an individual endpoint."""

    name: str
    latencies_ms: list[float] = field(default_factory=list)
    status_codes: dict[int, int] = field(default_factory=dict)
    errors: int = 0

    def record(self, duration_ms: float, status_code: int) -> None:
        self.latencies_ms.append(duration_ms)
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        if status_code >= 500:
            self.errors += 1

    @property
    def count(self) -> int:
        return len(self.latencies_ms)

    def percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_l = sorted(self.latencies_ms)
        idx = int(len(sorted_l) * (p / 100.0))
        idx = min(idx, len(sorted_l) - 1)
        return sorted_l[idx]


@dataclass
class BenchmarkResult:
    """Summary metrics of complete benchmark execution."""

    total_requests: int
    duration_seconds: float
    throughput_rps: float
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_count: int
    error_rate_pct: float
    endpoints: dict[str, EndpointStats] = field(default_factory=dict)


async def execute_virtual_user_workload(
    client: httpx.AsyncClient,
    dataset: PerformanceDataset,
    stats_map: dict[str, EndpointStats],
    duration_seconds: float,
    user_idx: int,
) -> None:
    """Simulate a single virtual user continuously issuing requests across the workload mix."""
    start_time = time.perf_counter()
    patient_token = dataset.patient_tokens[user_idx % len(dataset.patient_tokens)]
    headers = {
        "Authorization": f"Bearer {patient_token}",
        "Accept": "application/json",
    }

    import random

    while (time.perf_counter() - start_time) < duration_seconds:
        rnd = random.random()

        # 1. 40% Doctor Search & Listing
        if rnd < 0.40:
            endpoint_name = "GET /api/v1/doctors"
            spec = random.choice(["Ayurveda", "Panchakarma", "Yoga", "Homeopathy", ""])
            url = f"/api/v1/doctors?page=1&page_size=20{'&specialization=' + spec if spec else ''}"
            t0 = time.perf_counter()
            resp = await client.get(url, headers=headers)
            lat = (time.perf_counter() - t0) * 1000
            stats_map[endpoint_name].record(lat, resp.status_code)

        # 2. 30% Slot Reads
        elif rnd < 0.70:
            endpoint_name = "GET /api/v1/doctors/{id}/slots"
            doc_id = random.choice(dataset.doctor_ids)
            url = f"/api/v1/doctors/{doc_id}/slots?status=available"
            t0 = time.perf_counter()
            resp = await client.get(url, headers=headers)
            lat = (time.perf_counter() - t0) * 1000
            stats_map[endpoint_name].record(lat, resp.status_code)

        # 3. 20% Consultation Reads
        elif rnd < 0.90:
            endpoint_name = "GET /api/v1/consultations/{id}"
            if dataset.consultation_ids:
                consult_id = random.choice(dataset.consultation_ids)
                url = f"/api/v1/consultations/{consult_id}"
                t0 = time.perf_counter()
                resp = await client.get(url, headers=headers)
                lat = (time.perf_counter() - t0) * 1000
                stats_map[endpoint_name].record(lat, resp.status_code)
            else:
                # Fallback to health read if no consultations seeded yet
                t0 = time.perf_counter()
                resp = await client.get("/health/ready", headers=headers)
                lat = (time.perf_counter() - t0) * 1000
                stats_map["GET /health/ready"].record(lat, resp.status_code)

        # 4. 10% Booking Writes
        else:
            endpoint_name = "POST /api/v1/bookings"
            doc_id = random.choice(dataset.doctor_ids)
            slot_id = random.choice(dataset.slot_ids)
            idempotency_key = f"bench_key_{uuid.uuid4().hex}"
            booking_headers = {
                **headers,
                "Idempotency-Key": idempotency_key,
                "Content-Type": "application/json",
            }
            payload = {
                "doctor_id": doc_id,
                "slot_id": slot_id,
                "reason": "Performance workload booking write test.",
            }
            t0 = time.perf_counter()
            resp = await client.post("/api/v1/bookings", json=payload, headers=booking_headers)
            lat = (time.perf_counter() - t0) * 1000
            stats_map[endpoint_name].record(lat, resp.status_code)

        # Small pacing delay between requests (10ms)
        await asyncio.sleep(0.01)


async def run_benchmark(
    concurrency: int = 10,
    duration_seconds: float = 10.0,
    doctor_count: int = 15,
    slots_per_doctor: int = 10,
) -> BenchmarkResult:
    """Run full benchmark against active PostgreSQL session factory and ASGI application."""
    session_factory = get_session_factory()
    dataset: PerformanceDataset | None = None

    stats_map = {
        "GET /api/v1/doctors": EndpointStats("GET /api/v1/doctors"),
        "GET /api/v1/doctors/{id}/slots": EndpointStats("GET /api/v1/doctors/{id}/slots"),
        "GET /api/v1/consultations/{id}": EndpointStats("GET /api/v1/consultations/{id}"),
        "POST /api/v1/bookings": EndpointStats("POST /api/v1/bookings"),
        "GET /health/ready": EndpointStats("GET /health/ready"),
    }

    try:
        # Step 1: Seed synthetic test data
        async with session_factory() as session:
            dataset = await seed_performance_dataset(
                session=session,
                doctor_count=doctor_count,
                slots_per_doctor=slots_per_doctor,
                patient_count=concurrency,
            )

        # Step 2: Initialize ASGI client
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=10.0,
        ) as client:
            # Step 3: Launch concurrent virtual users
            bench_start = time.perf_counter()
            tasks = [
                execute_virtual_user_workload(
                    client=client,
                    dataset=dataset,
                    stats_map=stats_map,
                    duration_seconds=duration_seconds,
                    user_idx=u_idx,
                )
                for u_idx in range(concurrency)
            ]
            await asyncio.gather(*tasks)
            total_duration = time.perf_counter() - bench_start

        # Step 4: Compile results
        all_latencies = []
        total_requests = 0
        total_errors = 0
        for stat in stats_map.values():
            all_latencies.extend(stat.latencies_ms)
            total_requests += stat.count
            total_errors += stat.errors

        throughput = total_requests / total_duration if total_duration > 0 else 0.0
        sorted_latencies = sorted(all_latencies) if all_latencies else [0.0]

        def get_pct(p: float) -> float:
            idx = int(len(sorted_latencies) * (p / 100.0))
            idx = min(idx, len(sorted_latencies) - 1)
            return sorted_latencies[idx]

        result = BenchmarkResult(
            total_requests=total_requests,
            duration_seconds=round(total_duration, 2),
            throughput_rps=round(throughput, 1),
            p50_latency_ms=round(get_pct(50), 2),
            p90_latency_ms=round(get_pct(90), 2),
            p95_latency_ms=round(get_pct(95), 2),
            p99_latency_ms=round(get_pct(99), 2),
            error_count=total_errors,
            error_rate_pct=round(
                (total_errors / total_requests * 100.0) if total_requests else 0.0, 2
            ),
            endpoints=stats_map,
        )
        return result

    finally:
        # Step 5: Guaranteed cleanup
        async with session_factory() as session:
            await cleanup_performance_dataset(session=session, dataset=dataset)


if __name__ == "__main__":
    print(f"[{datetime.now(UTC).isoformat()}] Starting repeatable performance benchmark...")
    result = asyncio.run(run_benchmark(concurrency=10, duration_seconds=10.0))
    print(f"\n--- Benchmark Results ({result.duration_seconds}s run) ---")
    print(f"Total Requests: {result.total_requests}")
    print(f"Throughput:     {result.throughput_rps} RPS")
    print(f"p50 Latency:    {result.p50_latency_ms} ms")
    print(f"p90 Latency:    {result.p90_latency_ms} ms")
    print(f"p95 Latency:    {result.p95_latency_ms} ms")
    print(f"p99 Latency:    {result.p99_latency_ms} ms")
    print(f"Error Rate:     {result.error_rate_pct}% ({result.error_count} errors)")
    print("\nEndpoint Breakdown:")
    for name, stat in result.endpoints.items():
        if stat.count > 0:
            print(
                f"  {name:<32} Count: {stat.count:<5} "
                f"p50: {stat.percentile(50):.1f}ms  "
                f"p95: {stat.percentile(95):.1f}ms  "
                f"Status: {dict(stat.status_codes)}"
            )
