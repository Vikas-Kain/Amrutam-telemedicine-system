"""Transactional outbox worker for reliable asynchronous event dispatch.

Polls pending and retryable outbox events, executes registered domain handlers,
applies bounded exponential backoff with jitter on transient failures, and routes
exhausted or unrecoverable events to dead_letter.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.retry import RetryPolicy, calculate_backoff_delay, is_transient_error
from app.models.outbox import OutboxEvent
from app.services.outbox.handlers import HANDLER_REGISTRY

logger = logging.getLogger(__name__)


class OutboxWorker:
    """Asynchronous background worker polling and dispatching transactional outbox events."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        retry_policy: RetryPolicy | None = None,
        batch_size: int = 10,
        poll_interval: float = 1.0,
    ) -> None:
        self.session_factory = session_factory
        self.retry_policy = retry_policy or RetryPolicy()
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._is_running = False

    async def claim_and_process_batch(
        self,
        session: AsyncSession,
        batch_size: int | None = None,
    ) -> int:
        """Query, lock, and process a batch of pending or retryable outbox events.

        Uses PostgreSQL FOR UPDATE SKIP LOCKED to prevent duplicate processing
        under concurrent multi-worker horizontal scaling.
        """
        limit = batch_size or self.batch_size
        now = datetime.now(UTC)

        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_(["pending", "failed"]),
                or_(
                    OutboxEvent.next_retry_at.is_(None),
                    OutboxEvent.next_retry_at <= now,
                ),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )

        # Apply PostgreSQL row-level skip-locked for non-blocking concurrent worker claims
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        result = await session.execute(stmt)
        events = list(result.scalars().all())

        if not events:
            return 0

        processed_count = 0
        for event in events:
            now_action = datetime.now(UTC)
            handler = HANDLER_REGISTRY.get(event.event_type)

            if handler is None:
                logger.warning(
                    "No handler registered for event type '%s' (event_id=%s); marking completed.",
                    event.event_type,
                    event.id,
                )
                event.status = "completed"
                event.processed_at = now_action
                event.last_error = None
                event.next_retry_at = None
                processed_count += 1
                continue

            try:
                await handler(event, session)
                event.status = "completed"
                event.processed_at = now_action
                event.last_error = None
                event.next_retry_at = None
                processed_count += 1
                logger.debug(
                    "Successfully processed outbox event %s (%s)",
                    event.id,
                    event.event_type,
                )
            except Exception as exc:  # noqa: BLE001
                event.attempt_count += 1
                err_msg = f"{type(exc).__name__}: {exc}"
                event.last_error = err_msg
                is_transient = is_transient_error(exc)

                if is_transient and event.attempt_count < self.retry_policy.max_attempts:
                    delay = calculate_backoff_delay(
                        attempt=event.attempt_count,
                        base_delay=self.retry_policy.base_delay,
                        max_delay=self.retry_policy.max_delay,
                        jitter=self.retry_policy.jitter,
                    )
                    event.status = "failed"
                    event.next_retry_at = now_action + timedelta(seconds=delay)
                    logger.warning(
                        "Transient failure processing outbox event %s (%s) on attempt %s/%s. "
                        "Backing off for %.2fs: %s",
                        event.id,
                        event.event_type,
                        event.attempt_count,
                        self.retry_policy.max_attempts,
                        delay,
                        err_msg,
                    )
                else:
                    event.status = "dead_letter"
                    event.next_retry_at = None
                    logger.error(
                        "Permanent failure or retries exhausted for outbox event %s (%s) "
                        "on attempt %s/%s. Moved to dead_letter: %s",
                        event.id,
                        event.event_type,
                        event.attempt_count,
                        self.retry_policy.max_attempts,
                        err_msg,
                    )
                processed_count += 1

        await session.commit()
        return processed_count

    async def run_once(self, batch_size: int | None = None) -> int:
        """Execute a single batch run of outbox event processing."""
        async with self.session_factory() as session:
            return await self.claim_and_process_batch(session, batch_size=batch_size)

    async def run_loop(
        self,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuously poll and process outbox events until stopped."""
        self._is_running = True
        logger.info(
            "Outbox worker started (batch_size=%s, poll_interval=%.2fs)",
            self.batch_size,
            self.poll_interval,
        )

        try:
            while self._is_running:
                if stop_event and stop_event.is_set():
                    break

                try:
                    processed = await self.run_once()
                    if processed == 0:
                        await asyncio.sleep(self.poll_interval)
                except asyncio.CancelledError:
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected error in outbox worker poll loop: %s", exc)
                    await asyncio.sleep(self.poll_interval)
        finally:
            self._is_running = False
            logger.info("Outbox worker stopped.")

    def stop(self) -> None:
        """Signal the worker loop to terminate cleanly."""
        self._is_running = False
