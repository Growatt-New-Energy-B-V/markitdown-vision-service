"""Janitor job for cleaning up expired tasks."""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..utils.database import get_expired_tasks, mark_task_expired

logger = logging.getLogger(__name__)

_janitor_task: Optional[asyncio.Task] = None


async def _cleanup_task_files(task_id: str) -> None:
    """Delete files for an expired task."""
    settings = get_settings()
    task_dir = Path(settings.data_dir) / "tasks" / task_id

    if task_dir.exists():
        try:
            shutil.rmtree(task_dir)
            logger.info(f"Cleaned up files for expired task {task_id}")
        except Exception as e:
            logger.error(f"Failed to clean up task {task_id}: {e}")


async def _janitor_loop() -> None:
    """Periodic cleanup of expired tasks."""
    settings = get_settings()
    interval = settings.cleanup_interval_minutes * 60

    logger.info(f"Janitor started, cleanup interval: {settings.cleanup_interval_minutes} minutes")

    while True:
        try:
            # Get expired tasks
            expired_tasks = await get_expired_tasks()

            if expired_tasks:
                logger.info(f"Found {len(expired_tasks)} expired tasks to clean up")

                for task in expired_tasks:
                    try:
                        await _cleanup_task_files(task.task_id)
                        await mark_task_expired(task.task_id)
                    except Exception as e:
                        logger.error(f"Error cleaning up task {task.task_id}: {e}")

        except asyncio.CancelledError:
            logger.info("Janitor cancelled")
            raise
        except Exception as e:
            logger.error(f"Janitor error: {e}")

        # Wait for next cleanup cycle
        await asyncio.sleep(interval)


def start_janitor() -> None:
    """Start the janitor background task."""
    global _janitor_task
    _janitor_task = asyncio.create_task(_janitor_loop())
    logger.info("Janitor task started")


def stop_janitor() -> None:
    """Stop the janitor background task."""
    global _janitor_task
    if _janitor_task:
        _janitor_task.cancel()
        _janitor_task = None
        logger.info("Janitor task stopped")
