"""Background worker runner entrypoint for local development and container deployments.

Usage:
    python -m app.worker              # Run continuous polling loop
    python -m app.worker --once       # Run single batch and exit (for cron/CI)
    python -m app.worker --batch-size 20 --poll-interval 2.0
"""

import argparse
import asyncio
import logging
import signal
import sys

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_session_factory
from app.services.outbox.worker import OutboxWorker

logger = logging.getLogger("app.worker")


def parse_args() -> argparse.Namespace:
    """Parse worker command line arguments."""
    parser = argparse.ArgumentParser(description="Amrutam Telemedicine Outbox Worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch of pending outbox events and exit",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Maximum events to claim per batch (default: 10)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling delay in seconds when queue is idle (default: 1.0)",
    )
    return parser.parse_args()


async def main() -> None:
    """Initialize and run the outbox background worker."""
    args = parse_args()
    settings = get_settings()
    setup_logging(
        service_name=f"{settings.app_name}-worker",
        environment=settings.app_env,
        log_level=settings.log_level,
        log_format=settings.log_format,
    )

    logger.info("Initializing Outbox Worker (environment: %s)", settings.app_env)
    session_factory = get_session_factory()
    worker = OutboxWorker(
        session_factory=session_factory,
        batch_size=args.batch_size,
        poll_interval=args.poll_interval,
    )

    if args.once:
        logger.info("Running single outbox batch...")
        processed = await worker.run_once()
        logger.info("Single batch completed: %s events processed.", processed)
        return

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received; stopping worker cleanly...")
        stop_event.set()
        worker.stop()

    loop = asyncio.get_running_loop()
    # On Windows, signal.SIGTERM/SIGINT may not be fully supported via add_signal_handler
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_signal)

    try:
        await worker.run_loop(stop_event=stop_event)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker interrupted by user.")
    finally:
        logger.info("Worker process terminated.")


if __name__ == "__main__":
    asyncio.run(main())
