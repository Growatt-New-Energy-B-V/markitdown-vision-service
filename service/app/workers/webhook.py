"""Webhook notification delivery."""
import asyncio
import logging

import httpx

from ..config import get_settings
from ..models import WebhookPayload, TaskStatus
from ..utils.database import get_task, update_webhook_status

logger = logging.getLogger(__name__)


async def send_webhook_notification(task_id: str) -> None:
    """Send webhook notification with retries."""
    task = await get_task(task_id)
    if not task or not task.webhook_url:
        return

    if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        logger.warning(f"Skipping webhook for task {task_id} with status {task.status}")
        return

    settings = get_settings()

    # Build payload
    payload = WebhookPayload(
        task_id=task.task_id,
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )

    if task.status == TaskStatus.COMPLETED:
        payload.outputs = task.output_files
    elif task.status == TaskStatus.FAILED:
        payload.error_code = task.error_code
        payload.error_message = task.error_message

    # Attempt delivery with retries
    last_status = None
    for attempt in range(1, settings.webhook_max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
                response = await client.post(
                    task.webhook_url,
                    json=payload.model_dump(mode="json"),
                    headers={"Content-Type": "application/json"}
                )
                last_status = response.status_code

                if 200 <= response.status_code < 300:
                    logger.info(
                        f"Webhook delivered for task {task_id} "
                        f"(attempt {attempt}, status {response.status_code})"
                    )
                    await update_webhook_status(task_id, response.status_code, attempt)
                    return

                logger.warning(
                    f"Webhook delivery failed for task {task_id} "
                    f"(attempt {attempt}, status {response.status_code})"
                )

        except httpx.TimeoutException:
            logger.warning(f"Webhook timeout for task {task_id} (attempt {attempt})")
            last_status = 0
        except httpx.RequestError as e:
            logger.warning(f"Webhook error for task {task_id} (attempt {attempt}): {e}")
            last_status = 0
        except Exception as e:
            logger.error(f"Unexpected webhook error for task {task_id}: {e}")
            last_status = 0

        # Wait before retry (if not last attempt)
        if attempt < settings.webhook_max_retries:
            await asyncio.sleep(settings.webhook_retry_delay * attempt)

    # Record final status after all attempts
    await update_webhook_status(task_id, last_status or 0, settings.webhook_max_retries)
    logger.error(f"Webhook delivery failed for task {task_id} after {settings.webhook_max_retries} attempts")
