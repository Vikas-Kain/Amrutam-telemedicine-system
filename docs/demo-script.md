# Five-Minute Evaluation Demo Script

This script provides a step-by-step walkthrough to evaluate the key security, transactional, and architectural guarantees of the Amrutam Telemedicine Backend in under five minutes.

---

## Prerequisites

1. Ensure PostgreSQL is running and migrations are applied:
   ```powershell
   # Start database container
   docker compose up -d db

   # Apply database migrations
   .\.venv\Scripts\alembic.exe upgrade head
   ```

2. Start the FastAPI development server in a terminal:
   ```powershell
   .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
   ```

Base API URL: `http://127.0.0.1:8000`

---

## Step 1: Health & Observability Probes

Verify the service is running and connected to PostgreSQL:

```powershell
# 1. Process Liveness
curl.exe -i -X GET http://127.0.0.1:8000/health/live

# 2. Dependency Readiness (verifies live PostgreSQL connectivity)
curl.exe -i -X GET http://127.0.0.1:8000/health/ready
```
**Expected Outcome:** Both return HTTP 200 OK with `{"status":"ok"}` and `{"status":"ready","database":"connected"}`.

---

## Step 2: Register & Authenticate Actors

We create two actors: **Patient Alice** and **Patient Bob**.

```powershell
# 1. Register Patient Alice
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{"email":"alice@example.com","password":"Password123!Secure","role":"patient","full_name":"Alice Walker"}'

# 2. Login Alice and extract JWT access token
$aliceLogin = curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"alice@example.com","password":"Password123!Secure"}' | ConvertFrom-Json
$aliceToken = $aliceLogin.access_token
Write-Host "Alice Token: $aliceToken"

# 3. Register Patient Bob
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{"email":"bob@example.com","password":"Password123!Secure","role":"patient","full_name":"Bob Stone"}'

# 4. Login Bob and extract JWT access token
$bobLogin = curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"bob@example.com","password":"Password123!Secure"}' | ConvertFrom-Json
$bobToken = $bobLogin.access_token
Write-Host "Bob Token: $bobToken"
```

---

## Step 3: Register a Doctor & Create Availability Slot

Register a doctor with a verified profile and create a bookable future slot:

```powershell
# 1. Register Doctor Dr. Sharma
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  -d '{"email":"dr.sharma@example.com","password":"Password123!Secure","role":"doctor","full_name":"Dr. Sharma","specialization":"Ayurveda","license_number":"AYU-DEMO-9999","consultation_fee_minor":50000}'

# 2. Login Dr. Sharma
$docLogin = curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"dr.sharma@example.com","password":"Password123!Secure"}' | ConvertFrom-Json
$docToken = $docLogin.access_token

# 3. Fetch Doctor ID
$docs = curl.exe -s -X GET "http://127.0.0.1:8000/api/v1/doctors?specialization=Ayurveda" | ConvertFrom-Json
$doctorId = $docs.items[0].id

# 4. Doctor creates a bookable future slot (tomorrow 10:00 - 10:30 UTC)
$slotStart = (Get-Date).AddDays(1).ToUniversalTime().ToString("yyyy-MM-ddT10:00:00Z")
$slotEnd = (Get-Date).AddDays(1).ToUniversalTime().ToString("yyyy-MM-ddT10:30:00Z")

$slot = curl.exe -s -X POST "http://127.0.0.1:8000/api/v1/doctors/$doctorId/slots" `
  -H "Authorization: Bearer $docToken" `
  -H "Content-Type: application/json" `
  -d "{`"start_at`":`"$slotStart`",`"end_at`":`"$slotEnd`"}" | ConvertFrom-Json
$slotId = $slot.id
Write-Host "Created Slot ID: $slotId"
```

---

## Step 4: Atomic Appointment Booking (Valid Booking)

Alice books the available slot with a client-supplied `Idempotency-Key`:

```powershell
$bookingKey = [guid]::NewGuid().ToString()

$bookingResp = curl.exe -i -X POST http://127.0.0.1:8000/api/v1/bookings `
  -H "Authorization: Bearer $aliceToken" `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: $bookingKey" `
  -d "{`"doctor_id`":`"$doctorId`",`"slot_id`":`"$slotId`",`"reason`":`"Severe migraine consultation`"}"

$booking = curl.exe -s -X POST http://127.0.0.1:8000/api/v1/bookings `
  -H "Authorization: Bearer $aliceToken" `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: $bookingKey" `
  -d "{`"doctor_id`":`"$doctorId`",`"slot_id`":`"$slotId`",`"reason`":`"Severe migraine consultation`"}" | ConvertFrom-Json

$consultationId = $booking.id
Write-Host "Booked Consultation ID: $consultationId"
```
**Expected Outcome:** HTTP 201 Created. The slot is marked `booked` and an outbox event is created within a single database transaction.

---

## Step 5: Duplicate Idempotent Retry

Replay the exact same booking request using the same `Idempotency-Key`:

```powershell
curl.exe -i -X POST http://127.0.0.1:8000/api/v1/bookings `
  -H "Authorization: Bearer $aliceToken" `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: $bookingKey" `
  -d "{`"doctor_id`":`"$doctorId`",`"slot_id`":`"$slotId`",`"reason`":`"Severe migraine consultation`"}"
```
**Expected Outcome:** Returns the cached response payload with `X-Idempotent-Replay: true`. Zero duplicate database writes occur.

---

## Step 6: Conflicting Booking Attempt (Concurrency Protection)

Patient Bob attempts to book the same slot:

```powershell
$bobKey = [guid]::NewGuid().ToString()

curl.exe -i -X POST http://127.0.0.1:8000/api/v1/bookings `
  -H "Authorization: Bearer $bobToken" `
  -H "Content-Type: application/json" `
  -H "Idempotency-Key: $bobKey" `
  -d "{`"doctor_id`":`"$doctorId`",`"slot_id`":`"$slotId`",`"reason`":`"Back pain consultation`"}"
```
**Expected Outcome:** **HTTP 409 Conflict** with error code `SLOT_NOT_AVAILABLE`. Relational row-locking (`SELECT FOR UPDATE`) and partial unique constraints prevent double-booking.

---

## Step 7: Unauthorized Access Rejection (Layer 4 IDOR Boundary)

Bob attempts to view Alice's consultation details:

```powershell
curl.exe -i -X GET "http://127.0.0.1:8000/api/v1/consultations/$consultationId" `
  -H "Authorization: Bearer $bobToken"
```
**Expected Outcome:** **HTTP 403 Forbidden** with error code `FORBIDDEN`. Layer 4 resource ownership checks guarantee cross-patient clinical data isolation.

---

## Step 8: Consultation Lifecycle & Prescription Issuance

Doctor confirms the consultation, conducts it, issues a prescription, and completes the consultation:

```powershell
# 1. Doctor confirms consultation
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/consultations/$consultationId/confirm" `
  -H "Authorization: Bearer $docToken"

# 2. Doctor starts consultation
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/consultations/$consultationId/start" `
  -H "Authorization: Bearer $docToken"

# 3. Doctor issues prescription
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/consultations/$consultationId/prescriptions" `
  -H "Authorization: Bearer $docToken" `
  -H "Content-Type: application/json" `
  -d '{
    "notes": "Take with warm water twice daily after meals",
    "items": [
      {
        "medicine_name": "Ashwagandha Churna",
        "dosage": "500mg",
        "route": "oral",
        "frequency": "twice daily",
        "duration": "14 days",
        "instructions": "After dinner"
      }
    ]
  }'

# 4. Doctor completes consultation
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/consultations/$consultationId/complete" `
  -H "Authorization: Bearer $docToken"
```
**Expected Outcome:** State transitions strictly adhere to the consultation state machine: `booked -> confirmed -> in_progress -> completed`.

---

## Step 9: Prometheus Metrics & Operational Telemetry

Inspect operational metrics exposed at `/metrics`:

```powershell
curl.exe -s http://127.0.0.1:8000/metrics | Select-String -Pattern "http_requests_total|booking_operations_total"
```
**Expected Outcome:** Prometheus text metrics showing request counters and booking outcomes partitioned by low-cardinality labels without user or PHI leakage.

---

## Step 10: Automated Test Suite & CI Validation

Run the full local automated verification:

```powershell
# 1. Lint and code format
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .

# 2. Security audit for known vulnerabilities
.\.venv\Scripts\pip-audit.exe

# 3. Run complete test suite (326 tests)
.\.venv\Scripts\pytest.exe -v
```
**Expected Outcome:** 326 tests pass cleanly with 0 failures, 0 errors, and clean security audit.
