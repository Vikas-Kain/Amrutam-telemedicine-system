"""Locust load test suite for Amrutam Telemedicine API.

Workload Mix (Telemedicine Access Pattern):
- 40% Doctor search & directory listings (GET /api/v1/doctors?specialization=...)
- 30% Doctor availability slot reads (GET /api/v1/doctors/{id}/slots)
- 20% Patient consultation detail reads (GET /api/v1/consultations/{id})
- 10% Atomic appointment booking writes (POST /api/v1/bookings)

Run locally in headless mode:
    locust -f tests/performance/locustfile.py --headless -u 20 -r 5 --run-time 30s --host http://localhost:8000
"""

import random
import uuid
from typing import Any

from locust import HttpUser, between, task


class TelemedicineUser(HttpUser):
    """Simulated patient interacting with doctor directory, slots, bookings, and records."""

    wait_time = between(0.05, 0.2)

    # Shared pool of discoverable IDs populated during session warmup
    known_doctor_ids: list[str] = []
    known_slot_ids: list[str] = []
    known_consultation_ids: list[str] = []
    auth_token: str | None = None
    patient_id: str | None = None

    def on_start(self) -> None:
        """Register and authenticate a temporary virtual user for load testing."""
        rand_suffix = uuid.uuid4().hex[:8]
        email = f"perf_user_{rand_suffix}@example.com"
        password = "PerfUser123!Secure"

        # 1. Register synthetic user
        reg_payload = {
            "email": email,
            "password": password,
            "role": "patient",
            "full_name": f"Perf User {rand_suffix}",
            "phone": "+919876543210",
        }
        with self.client.post(
            "/api/v1/auth/register",
            json=reg_payload,
            name="/api/v1/auth/register",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
                data = resp.json()
                self.patient_id = data.get("id")

        # 2. Login to obtain JWT Bearer access token
        login_payload = {
            "email": email,
            "password": password,
        }
        with self.client.post(
            "/api/v1/auth/login",
            json=login_payload,
            name="/api/v1/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
                data = resp.json()
                self.auth_token = data.get("access_token")

        # 3. Warm up known doctor IDs from directory if pool is empty
        if not TelemedicineUser.known_doctor_ids:
            with self.client.get(
                "/api/v1/doctors?page_size=20",
                name="/api/v1/doctors [warmup]",
                catch_response=True,
            ) as resp:
                if resp.status_code == 200:
                    resp.success()
                    items = resp.json().get("items", [])
                    TelemedicineUser.known_doctor_ids = [doc["id"] for doc in items]

    @property
    def auth_headers(self) -> dict[str, str]:
        """Headers containing authorization Bearer token."""
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    @task(40)
    def doctor_search(self) -> None:
        """Benchmark doctor search with specialization filters and bounded pagination."""
        specialization = random.choice(["Ayurveda", "Panchakarma", "Yoga", "Homeopathy", ""])
        params: dict[str, Any] = {"page": 1, "page_size": 20}
        if specialization:
            params["specialization"] = specialization

        self.client.get(
            "/api/v1/doctors",
            params=params,
            headers=self.auth_headers,
            name="/api/v1/doctors",
        )

    @task(30)
    def slot_reads(self) -> None:
        """Benchmark doctor availability slot queries."""
        if not TelemedicineUser.known_doctor_ids:
            return

        doctor_id = random.choice(TelemedicineUser.known_doctor_ids)
        with self.client.get(
            f"/api/v1/doctors/{doctor_id}/slots?status=available",
            headers=self.auth_headers,
            name="/api/v1/doctors/{id}/slots",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
                items = resp.json().get("items", [])
                for slot in items:
                    if slot.get("status") == "available":
                        TelemedicineUser.known_slot_ids.append(slot["id"])

    @task(20)
    def consultation_reads(self) -> None:
        """Benchmark authenticated consultation details retrieval."""
        if not TelemedicineUser.known_consultation_ids:
            # Query active user bookings if no consultation ID is cached yet
            self.client.get(
                "/api/v1/doctors",
                headers=self.auth_headers,
                name="/api/v1/doctors",
            )
            return

        consultation_id = random.choice(TelemedicineUser.known_consultation_ids)
        self.client.get(
            f"/api/v1/consultations/{consultation_id}",
            headers=self.auth_headers,
            name="/api/v1/consultations/{id}",
        )

    @task(10)
    def booking_writes(self) -> None:
        """Benchmark atomic appointment booking with idempotency keys."""
        if not TelemedicineUser.known_doctor_ids or not TelemedicineUser.known_slot_ids:
            return

        doctor_id = random.choice(TelemedicineUser.known_doctor_ids)
        slot_id = random.choice(TelemedicineUser.known_slot_ids)
        idempotency_key = f"perf_key_{uuid.uuid4().hex}"

        headers = {
            **self.auth_headers,
            "Idempotency-Key": idempotency_key,
        }
        payload = {
            "doctor_id": doctor_id,
            "slot_id": slot_id,
            "reason": "Synthetic consultation write benchmark.",
        }

        with self.client.post(
            "/api/v1/bookings",
            json=payload,
            headers=headers,
            name="/api/v1/bookings",
            catch_response=True,
        ) as resp:
            # Both 201 (successful new booking) and 409 (slot collision or conflict)
            # are expected, deterministic, and valid business responses under concurrent load
            if resp.status_code in (201, 409):
                resp.success()
                if resp.status_code == 201:
                    data = resp.json()
                    consult_id = data.get("id") or data.get("booking", {}).get("id")
                    if consult_id:
                        TelemedicineUser.known_consultation_ids.append(consult_id)
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")
