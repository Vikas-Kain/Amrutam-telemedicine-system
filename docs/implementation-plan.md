# Implementation Plan and Commit Discipline

This project uses an incremental, verifiable commit strategy to build the Amrutam Telemedicine Backend. Each milestone corresponds to a coherent engineering change with focused code, updated tests, and passing checks.

## Rules for each milestone
1. **Check state before starting:** Verify branch and clean working tree with `git status --short` and `git log --oneline -5`.
2. **Execute milestone prompt:** Use the corresponding milestone prompt from `amrutam_backend_agent_pack/prompts/`.
3. **Review the diff:** Inspect all modified lines; ensure changes match the current milestone scope only.
4. **Execute verification checks:** Run the exact test, lint (`ruff check .`), format (`ruff format --check .`), and migration commands.
5. **Exercise functionality:** Verify the endpoint or workflow directly (e.g. via test or HTTP client).
6. **Manual commit:** Do not commit automatically. The developer manually stages and commits the milestone with the specified commit message.
7. **No synthetic history:** Do not backdate commits or fabricate changes. Every commit represents genuine, tested development work.

## Milestones summary (25 commits)
1. `docs: add architecture and project implementation plan`
2. `chore: bootstrap FastAPI application and developer tooling`
3. `feat: add application settings and structured error handling`
4. `build: add Docker Compose development environment`
5. `feat: add PostgreSQL persistence and Alembic migrations`
6. `feat: add core telemedicine database models`
7. `feat: add user registration and secure password hashing`
8. `feat: add JWT authentication and role-based authorization`
9. `feat: add doctor profiles and search filters`
10. `feat: add doctor availability management`
11. `feat: add idempotency key persistence for write requests`
12. `feat: implement atomic idempotent appointment booking`
13. `feat: add booking retrieval and cancellation lifecycle`
14. `feat: enforce consultation lifecycle transitions`
15. `feat: add prescription and prescription-item workflows`
16. `feat: add payment lifecycle with mock provider adapter`
17. `feat: add audit logging for sensitive operations`
18. `feat: add aggregate admin analytics`
19. `feat: add background jobs and transactional outbox`
20. `feat: add rate limiting and resilience policies`
21. `test: complete core API and security test coverage`
22: `feat: instrument logs, metrics, traces, and health checks`
23. `test: add performance test scenarios and scaling evidence`
24. `build: harden container build and CI security checks`
25. `docs: finalize documentation and demo runbook`

## Definition of release-ready
The assignment is ready for final submission when:
- All core workflows (auth, availability, atomic booking, consultation, prescriptions, payments, audit, analytics) are implemented and verified.
- Database concurrency and idempotency tests pass against PostgreSQL.
- CI pipeline is green with lint, format, security scans, and tests.
- A clean clone follows [README.md](../README.md) instructions without undocumented manual interventions.
- Architecture, threat model, and operational documentation accurately reflect the codebase without false claims.
