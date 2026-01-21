"""In-process task queue for background processing."""
import asyncio
import logging
from datetime import datetime, timezone
from queue import Queue, Empty
from threading import Thread
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)

# Global task queue
_task_queue: Queue[str] = Queue()
_worker_threads: list[Thread] = []
_shutdown_event = asyncio.Event()
_loop: Optional[asyncio.AbstractEventLoop] = None


def enqueue_task(task_id: str) -> None:
    """Add a task to the processing queue."""
    _task_queue.put(task_id)
    logger.info(f"Task {task_id} enqueued for processing")


def _worker_thread(worker_id: int, loop: asyncio.AbstractEventLoop) -> None:
    """Worker thread that processes tasks."""
    logger.info(f"Worker {worker_id} started")

    while True:
        try:
            # Get task with timeout to allow checking shutdown
            try:
                task_id = _task_queue.get(timeout=1.0)
            except Empty:
                # Check if we should shutdown
                if _shutdown_event.is_set():
                    break
                continue

            logger.info(f"Worker {worker_id} processing task {task_id}")

            # Run the async task processor in the event loop
            future = asyncio.run_coroutine_threadsafe(
                _process_task(task_id),
                loop
            )

            try:
                # Wait for completion with a long timeout for large files
                future.result(timeout=3600)  # 1 hour max
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing {task_id}: {e}")

            _task_queue.task_done()

        except Exception as e:
            logger.error(f"Worker {worker_id} unexpected error: {e}")

    logger.info(f"Worker {worker_id} stopped")


async def _process_task(task_id: str) -> None:
    """Process a single task."""
    from ..utils.database import get_task, update_task_status
    from ..converters.pipeline import convert_document
    from .webhook import send_webhook_notification
    from ..models.task import TaskStatus

    task = await get_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found for processing")
        return

    # Mark as running
    now = datetime.now(timezone.utc)
    await update_task_status(task_id, TaskStatus.RUNNING, started_at=now)

    try:
        # Run the conversion
        output_files = await convert_document(task)

        # Mark as completed
        finished_at = datetime.now(timezone.utc)
        await update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            finished_at=finished_at,
            output_files=output_files,
        )
        logger.info(f"Task {task_id} completed successfully with {len(output_files)} outputs")

        # Send webhook if configured
        if task.webhook_url:
            await send_webhook_notification(task_id)

    except Exception as e:
        logger.exception(f"Task {task_id} failed: {e}")
        finished_at = datetime.now(timezone.utc)
        await update_task_status(
            task_id,
            TaskStatus.FAILED,
            finished_at=finished_at,
            error_code="CONVERSION_ERROR",
            error_message=str(e)[:500],  # Limit error message length
        )

        # Send webhook if configured
        if task.webhook_url:
            await send_webhook_notification(task_id)


def start_workers(loop: asyncio.AbstractEventLoop) -> None:
    """Start the worker threads."""
    global _loop, _worker_threads
    _loop = loop
    _shutdown_event.clear()

    settings = get_settings()

    for i in range(settings.max_concurrent_tasks):
        thread = Thread(target=_worker_thread, args=(i, loop), daemon=True)
        thread.start()
        _worker_threads.append(thread)

    logger.info(f"Started {settings.max_concurrent_tasks} worker threads")


def stop_workers() -> None:
    """Stop the worker threads."""
    global _worker_threads
    _shutdown_event.set()

    for thread in _worker_threads:
        thread.join(timeout=5.0)

    _worker_threads = []
    logger.info("Worker threads stopped")
