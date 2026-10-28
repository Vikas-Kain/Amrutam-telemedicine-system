# Data Model and Invariants

This document specifies the logical data model for the Amrutam Telemedicine Backend. SQLAlchemy 2.x declarative models and Alembic migrations will serve as the physical implementation.

## Entity specifications

### users
- `id`: UUID primary key (default `gen_random_uuid()`).
- `email_normalized`: VARCHAR(255), unique, non-null, indexed (case-insensitive normalized).
- `password_hash`: VARCHAR(255), non-null (Argon2id hash); never returned in schemas.
- `role`: VARCHAR(32), non-null (`patient`, `doctor`, `admin`).
- `is_active`: BOOLEAN, non-null, default `true`.
- `mfa_enabled`: BOOLEAN, non-null, default `false`.
- `mfa_secret_encrypted`: TEXT, nullable; encrypted at rest with an environment key.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null, normalized to UTC.

### profiles
- `id`: UUID primary key.
- `user_id`: UUID, non-null, unique foreign key to `users.id` on delete CASCADE.
- `full_name`: VARCHAR(255), non-null.
- `phone`: VARCHAR(32), nullable.
- `date_of_birth`: DATE, nullable.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.

### doctors
- `id`: UUID primary key.
- `user_id`: UUID, non-null, unique foreign key to `users.id` on delete CASCADE.
- `specialization`: VARCHAR(128), non-null, indexed.
- `license_number`: VARCHAR(64), non-null, unique, indexed.
- `is_verified`: BOOLEAN, non-null, default `false`, indexed.
- `consultation_fee_minor`: INTEGER, non-null, check `consultation_fee_minor >= 0` (stored in minor currency units, e.g. paise / cents).
- `currency`: VARCHAR(3), non-null, default `'INR'`.
- `bio`: TEXT, nullable.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.

### availability_slots
- `id`: UUID primary key.
- `doctor_id`: UUID, non-null, foreign key to `doctors.id` on delete CASCADE.
- `start_at`: TIMESTAMPTZ, non-null.
- `end_at`: TIMESTAMPTZ, non-null.
- `status`: VARCHAR(32), non-null, default `'available'` (`available`, `booked`, `blocked`).
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.
- **Constraints & Indexes:**
  - Check constraint: `end_at > start_at` (`chk_slot_time_interval`).
  - Check constraint: `status IN ('available', 'booked', 'blocked')` (`chk_availability_slots_status`).
  - Exclusion constraint: `exclude_overlapping_doctor_slots` via PostgreSQL GiST (`btree_gist` extension): `EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_at, end_at) WITH &&)`.
  - Composite indexes: `(doctor_id, start_at, status)` (`ix_availability_slots_doctor_start_status`) and `(doctor_id, start_at, end_at)` (`ix_availability_slots_doctor_range`).
  - Composite unique key: `(id, doctor_id)` (`uq_availability_slots_id_doctor`), referenced by the consultation ownership foreign key.
- **Lifecycle & Booking Rules:**
  - Statuses:
    - `'available'`: Open for appointment booking by patients.
    - `'booked'`: Reserved for an active consultation; protected from deletion or modification by the doctor.
    - `'blocked'`: Administratively blocked by the doctor; ineligible for appointment booking.
  - Cancellation & Reuse: When an active consultation occupying a slot is cancelled, the slot transition back to `'available'` must occur atomically within the same database transaction.


### consultations
- `id`: UUID primary key.
- `patient_id`: UUID, non-null, foreign key to `users.id`.
- `doctor_id`: UUID, non-null, foreign key to `doctors.id`.
- `slot_id`: UUID, non-null, foreign key to `availability_slots.id`.
- `status`: VARCHAR(32), non-null, default `'booked'` (`booked`, `confirmed`, `in_progress`, `completed`, `cancelled`, `no_show`).
- `reason`: TEXT, nullable.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.
- **Constraints:**
  - Partial unique index: `UNIQUE (slot_id) WHERE status NOT IN ('cancelled')` to guarantee no double-booking at the database level.
  - Composite foreign key `(slot_id, doctor_id)` → `availability_slots(id, doctor_id)` (`fk_consultations_slot_doctor`) prevents pairing a consultation with a doctor other than the slot owner.
  - Foreign keys ensure referential integrity with patient, doctor, and slot.

### prescriptions
- `id`: UUID primary key.
- `consultation_id`: UUID, non-null, unique foreign key to `consultations.id`.
- `patient_id`: UUID, non-null, foreign key to `users.id`.
- `doctor_id`: UUID, non-null, foreign key to `doctors.id`.
- `notes`: TEXT, nullable.
- `issued_at`: TIMESTAMPTZ, non-null.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.

### prescription_items
- `id`: UUID primary key.
- `prescription_id`: UUID, non-null, foreign key to `prescriptions.id` on delete CASCADE.
- `medicine_name`: VARCHAR(255), non-null.
- `dosage`: VARCHAR(64), non-null.
- `route`: VARCHAR(64), non-null (e.g. `'oral'`, `'topical'`).
- `frequency`: VARCHAR(64), non-null (e.g. `'twice daily'`).
- `duration`: VARCHAR(64), non-null (e.g. `'5 days'`).
- `instructions`: TEXT, nullable.

### payments
- `id`: UUID primary key.
- `consultation_id`: UUID, non-null, foreign key to `consultations.id`.
- `amount_minor`: INTEGER, non-null, check `amount_minor >= 0`.
- `currency`: VARCHAR(3), non-null, default `'INR'`.
- `status`: VARCHAR(32), non-null, default `'pending'` (`pending`, `succeeded`, `failed`, `refunded`).
- `provider`: VARCHAR(64), non-null (e.g. `'mock_provider'`).
- `provider_reference`: VARCHAR(255), nullable, unique where non-null.
- `created_at`, `updated_at`: TIMESTAMPTZ, non-null.

### audit_logs
- `id`: UUID primary key.
- `actor_user_id`: UUID, nullable, foreign key to `users.id` on delete SET NULL.
- `action`: VARCHAR(128), non-null, indexed.
- `resource_type`: VARCHAR(64), non-null, indexed.
- `resource_id`: UUID, nullable, indexed.
- `correlation_id`: VARCHAR(64), nullable.
- `metadata`: JSONB, nullable (contains safe audit metadata; strictly redacts credentials, tokens, and PHI).
- `created_at`: TIMESTAMPTZ, non-null, indexed.

### idempotency_keys
- `id`: UUID primary key.
- `user_id`: UUID, non-null, foreign key to `users.id` on delete CASCADE.
- `key`: VARCHAR(255), non-null.
- `operation`: VARCHAR(64), non-null.
- `request_hash`: VARCHAR(64), non-null (SHA-256 of request payload).
- `status`: VARCHAR(32), non-null (`in_progress`, `completed`, `failed`).
- `response_code`: INTEGER, nullable.
- `response_body`: JSONB, nullable.
- `resource_id`: UUID, nullable.
- `expires_at`: TIMESTAMPTZ, non-null.
- `created_at`: TIMESTAMPTZ, non-null.
- **Constraints:**
  - Unique constraint: `UNIQUE (user_id, key, operation)`.

### outbox_events
- `id`: UUID primary key.
- `event_type`: VARCHAR(128), non-null, indexed.
- `aggregate_type`: VARCHAR(64), non-null.
- `aggregate_id`: UUID, non-null.
- `payload`: JSONB, non-null.
- `status`: VARCHAR(32), non-null, default `'pending'` (`pending`, `processed`, `failed`).
- `attempt_count`: INTEGER, non-null, default 0.
- `last_error`: TEXT, nullable.
- `created_at`: TIMESTAMPTZ, non-null, indexed.
- `processed_at`: TIMESTAMPTZ, nullable.
- **Booking event rule:** successful booking transactions persist a `booking.created` event containing only consultation, doctor, and slot identifiers; the appointment reason is excluded.

## Invariants to enforce and test
1. **Email uniqueness:** `email_normalized` is strictly unique across all active accounts.
2. **Credential protection:** Password hashes and encrypted MFA secrets are never returned in any response schema.
3. **Availability ownership:** Only the owning doctor (or admin) can create, modify, or block their availability slots.
4. **Slot assignment integrity:** A consultation cannot pair a slot with a doctor other than the slot's owner.
5. **Atomic booking exclusivity:** Exactly one active consultation may occupy a slot (`SELECT ... FOR UPDATE` + partial unique index).
6. **Cancellation consistency:** Cancellation releases slot status atomically within the same database transaction.
7. **Idempotency replay:** Replayed identical requests return original results; mismatched payloads return `409 Conflict`.
8. **Consultation state machine:** Consultations only follow allowed forward transitions (`booked` → `confirmed` → `in_progress` → `completed`).
9. **Prescription authorization:** Prescriptions can only be authored by the assigned doctor for completed/in-progress consultations.
10. **Payment state consistency:** Payment records are updated idempotently without double-crediting.
11. **Audit integrity:** Audit logs are append-only and strictly sanitized of sensitive clinical and credential payloads.
12. **Monetary precision:** Money is stored exclusively in integer minor units (avoiding binary floating-point roundoff).
