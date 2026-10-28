# Security Threat Model

## Scope and assumptions
The Amrutam Telemedicine Backend processes sensitive user credentials, doctor professional licenses, appointment reservations, medical prescriptions, payment transaction references, and operational audit records. This threat model applies the STRIDE methodology to identify threats, define assets, establish trust boundaries, and specify security controls.

## Assets and data classification

| Classification | Examples | Storage and transport security |
|---|---|---|
| **Critical secrets** | JWT private signing keys, MFA symmetric encryption keys, webhook secrets, DB passwords | Injected via environment / secret manager; strictly excluded from Git, logs, and docker images |
| **Authentication data** | User password hashes, TOTP MFA secret states, refresh tokens | Argon2id password hashing; TOTP secrets encrypted with AES-256-GCM; rate-limited routes |
| **Sensitive health information (PHI)** | Consultation reasons, medical prescriptions, patient notes | TLS in transit; AES-256 at rest; strict query-level authorization; never included in logs |
| **Financial data** | Payment amount, currency, status, provider transaction ID | Avoid handling raw cardholder data (PCI-DSS out-of-scope via provider redirection/tokens); audit all status transitions |
| **Personal identifiable info (PII)** | Patient names, phone numbers, email addresses | Minimal data collection principle; indexed email normalization; RBAC enforcement |
| **Operational & audit data** | Audit log entries, metrics, trace spans, request IDs | Low-cardinality labels; scrubbed of query bind values and headers; append-only persistence |

## Actors and trust boundaries
1. **Anonymous web client:** Untrusted internet actor; restricted to `/auth/register`, `/auth/login`, public doctor search, and `/health/live`.
2. **Authenticated patient:** Limited strictly to viewing/editing own profile, browsing doctors, booking appointments, and reading own consultations/prescriptions.
3. **Authenticated doctor:** Authorized to manage own availability slots, view assigned consultations, update consultation status, and write prescriptions for assigned patients.
4. **Administrator:** Authorized to perform operational oversight and review aggregate analytics; access to individual clinical records is denied by default or strictly audited.
5. **Background worker:** Scoped internal process; reads transactional outbox and executes retryable async jobs with least-privilege credentials.
6. **External payment provider:** Outside trust boundary; communicates via signed HTTPS webhooks.

## STRIDE threat catalog and mitigations

| Threat (STRIDE) | Attack vector & scenario | Impact | Mitigations & security controls | Verification & tests |
|---|---|---|---|---|
| **Spoofing** | Credential stuffing / brute force login | Unauthorized account takeover | Argon2id hashing (`app/core/security.py`), short-lived JWT access tokens (15m), TOTP MFA with AES-256-GCM encrypted secrets (`app/core/mfa.py`), IP/account rate limiting (`app/core/rate_limit.py`) | `tests/test_auth.py`, `tests/test_security.py`, `tests/test_rate_limiting.py` |
| **Spoofing** | Forged payment webhook callback | Fraudulent consultation confirmation | HMAC-SHA256 signature verification over raw request body in `app/services/payment_provider.py`; replay timestamp tolerance | `tests/test_payments.py` |
| **Tampering** | Concurrent double booking race | Two patients reserve the same slot | Database-level row locking (`SELECT FOR UPDATE`), partial unique constraints (`uq_consultations_active_slot`), atomic transactions | `tests/test_concurrency.py`, `tests/test_bookings.py` |
| **Tampering** | Replayed or modified write request | Duplicate booking charges | Strict `Idempotency-Key` validation; SHA-256 canonical fingerprint check; payload mismatch rejects with 409 (`app/services/idempotency_service.py`) | `tests/test_idempotency.py` |
| **Repudiation** | Denied consultation cancellation or prescription change | Inability to establish clinical audit trail | Append-only `audit_logs` table recording actor ID, resource type, action, timestamp, and correlation ID (`app/services/audit_service.py`) | `tests/test_audit.py` |
| **Information Disclosure** | Broken Object-Level Authorization (IDOR) | Patient A reads Patient B's prescription | Mandatory ownership / assignment checks in service and query layers (`WHERE patient_id = :current_user_id`) across all clinical routes | `tests/test_security.py` |
| **Information Disclosure** | Sensitive data in logs or trace spans | Leakage of PHI, passwords, or tokens in logs | JSON structured logger with redaction allowlist (`app/core/logging.py`); OpenTelemetry attribute sanitizer (`app/core/tracing.py`) | `tests/test_logging.py`, `tests/test_observability.py` |
| **Denial of Service** | Volumetric flooding / large payload submission | Resource exhaustion, worker starvation | Sliding window rate limiting (`app/core/rate_limit.py`), request body size caps (`RequestBodyLimitMiddleware`), bounded pagination (`1 <= page_size <= 100`) | `tests/test_rate_limiting.py`, `tests/test_resilience.py` |
| **Elevation of Privilege** | Normal user calling administrative analytics | Unauthorized access to platform metrics | Role-based authorization dependencies (`require_roles("admin")`, `require_doctor`) checked on every protected endpoint | `tests/test_analytics.py`, `tests/test_security.py` |

## Residual risks and non-goals
- **Mock Payment Processing:** The take-home implementation uses a simulated mock payment provider adapter (`MockPaymentProviderAdapter`); real payment provider integration and PCI-DSS certification are out of scope. No real cardholder data is handled or stored.
- **Single-Machine Execution:** Local execution runs via Docker Compose on a single machine; production deployment requires managed TLS termination, multi-AZ database replication, and enterprise secret vaults.
- **Compliance Certification Boundary:** No claim of formal HIPAA, GDPR, or SOC-2 certification is made without third-party compliance audit, legal review, and production operational controls.
