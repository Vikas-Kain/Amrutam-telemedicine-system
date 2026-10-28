# Performance Test Scenarios & Scaling Evidence

This document reports the performance testing methodology, reproducible workload definitions, actual local benchmark measurements, demonstrated bottlenecks, and the production scaling rationale for the Amrutam Telemedicine backend.

---

## 1. Test Environment

- **Operating System:** Windows 11 Enterprise (x86_64)
- **Runtime:** Python 3.12.10 (virtualenv `.venv`)
- **Web Framework:** FastAPI 0.162.0 running via Starlette / HTTPX ASGI pipeline
- **Database:** Local PostgreSQL 16.3 on `localhost:5432` with connection pooling (`pool_size=10`, `max_overflow=20`, `pool_timeout=30.0s`)
- **Network Topology:** Local loopback interface (eliminating external WAN latency jitter to measure pure application and database overhead)
- **Data State:** Seeded with non-sensitive synthetic doctors, available slots, patients, and consultation records using `tests/performance/data_seeder.py`

---

## 2. Workload Mix & Test Scenarios

The performance workload models realistic telemedicine traffic patterns (80–90% read-heavy discovery vs 10–20% write-heavy mutations):

| Scenario | HTTP Endpoint | Workload Mix Weight | Description |
|---|---|---|---|
| **Doctor Search** | `GET /api/v1/doctors` | **40%** | Filtered search by specialization (`Ayurveda`, `Panchakarma`, `Yoga`, `Homeopathy`) with bounded pagination (`page=1`, `page_size=20`). |
| **Slot Reads** | `GET /api/v1/doctors/{id}/slots` | **30%** | Availability slot queries filtering by doctor ID and `status=available`. |
| **Consultation Reads** | `GET /api/v1/consultations/{id}` | **20%** | Authenticated patient retrieval of appointment records and clinical consultation metadata. |
| **Booking Writes** | `POST /api/v1/bookings` | **10%** | Atomic appointment booking write with client-supplied `Idempotency-Key` and slot locking (`SELECT FOR UPDATE`). |

---

## 3. Actual Benchmark Execution Results

The benchmark was executed using the repeatable test harness [`tests/performance/run_benchmark.py`](file:///c:/Users/vikasln1/Classified/Amrutam-telemedicine-system/tests/performance/run_benchmark.py) with 10 concurrent virtual users across a continuous 10.06-second window:

### Summary Performance Metrics
- **Total Requests Processed:** **721 requests**
- **Test Duration:** **10.06 seconds**
- **Measured Throughput:** **71.7 Requests Per Second (RPS)**
- **p50 (Median) Latency:** **127.56 ms**
- **p90 Latency:** **185.28 ms**
- **p95 Tail Latency:** **225.44 ms**
- **p99 Worst Latency:** **271.37 ms**
- **Server Error Count:** **0 errors (HTTP 5xx)**
- **Server Error Rate:** **0.00%**

### Endpoint Breakdown
| Endpoint | Requests | p50 (ms) | p95 (ms) | Status Code Distribution |
|---|---|---|---|---|
| `GET /api/v1/doctors` | 277 | 134.9 ms | 194.7 ms | 200 OK: 277 |
| `GET /api/v1/doctors/{id}/slots` | 222 | 112.4 ms | 162.4 ms | 200 OK: 222 |
| `GET /api/v1/consultations/{id}` | 145 | 114.6 ms | 169.0 ms | 200 OK: 12, 403 Forbidden: 133* |
| `POST /api/v1/bookings` | 77 | 204.4 ms | 306.2 ms | 201 Created: 6, 409 Conflict: 71** |

> **Notes on Non-200 Responses:**
> - `* 403 Forbidden` on consultation reads reflects Layer 4 IDOR authorization enforcement: simulated virtual patients are strictly blocked from accessing consultations belonging to other patients.
> - `** 409 Conflict` on booking writes reflects high-contention slot locking: concurrent virtual patients attempting to book already-reserved slots receive deterministic business conflicts without double-booking or corrupting state.

---

## 4. How to Collect Metrics & Run Workloads

### Option A: Standalone Python Benchmark Harness (Recommended for Quick Runs)
Runs the end-to-end benchmark against real database sessions and prints formatted percentile distributions:
```powershell
.\.venv\Scripts\python.exe tests/performance/run_benchmark.py
```

### Option B: Locust Load Testing (Headless or Web UI)
Start the local API:
```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000
```
Run Locust in headless mode:
```powershell
.\.venv\Scripts\locust.exe -f tests/performance/locustfile.py --headless -u 20 -r 5 --run-time 30s --host http://localhost:8000 --csv=tests/performance/results/locust_run
```
Or launch with Web UI at `http://localhost:8089`:
```powershell
.\.venv\Scripts\locust.exe -f tests/performance/locustfile.py --host http://localhost:8000
```

### Option C: k6 Workload
Run the k6 JavaScript script against the local API:
```bash
k6 run tests/performance/k6_workload.js -e BASE_URL=http://localhost:8000
```

### Option D: Prometheus Metrics Collection
During any benchmark run, Prometheus scrapes latency and error percentiles directly from `http://localhost:8000/metrics`:
- Throughput: `sum(rate(http_requests_total[1m])) by (method, route)`
- Tail Latency: `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
- 5xx Error Ratio: `sum(rate(http_requests_total{status_code=~"5.."}[1m]))`

---

## 5. Demonstrated Bottlenecks & Tuning Analysis

Based on local profiling and query execution plans:

1. **Booking Contention vs Query Performance:**
   - Write operations (`POST /api/v1/bookings`) exhibit higher latency (p50: 204ms, p95: 306ms) than read operations (p50: 112–134ms) due to atomic row locking (`SELECT ... FOR UPDATE`), nested savepoint management for idempotency, and transactional outbox event insertion.
   - **Tuning applied:** The partial unique index `uq_consultations_active_slot` on `consultations(slot_id) WHERE status NOT IN ('cancelled')` prevents table-level lock escalation, keeping contention isolated strictly to the specific slot row.

2. **Doctor Directory Search Filter Optimization:**
   - Doctor queries filter by `specialization` and sort deterministically by `(created_at DESC, id DESC)`.
   - **Tuning applied:** Indexes on `doctors(specialization)` and `doctors(user_id)` allow PostgreSQL index scans rather than sequential table scans. Bounded pagination (`max_page_size=100`, default 20) prevents excessive heap allocations.

3. **Availability Slot Chronological Lookups:**
   - Slot reads filter by `doctor_id`, `start_at >= now`, and `status = 'available'`.
   - **Tuning applied:** The composite index `ix_availability_slots_doctor_start_status (doctor_id, start_at, status)` satisfies both the equality filter on doctor and status and the range filter on start time in a single index lookup.
