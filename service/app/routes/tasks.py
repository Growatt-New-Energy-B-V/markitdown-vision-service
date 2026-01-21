"""Task management endpoints."""
import io
import logging
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import ulid
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..config import get_settings
from ..models import Task, TaskStatus, TaskCreateResponse, TaskStatusResponse
from ..utils.database import create_task, get_task
from ..workers.task_queue import enqueue_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

# Maximum chunk size for streaming uploads (1MB)
CHUNK_SIZE = 1024 * 1024


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal."""
    # Remove path components
    filename = os.path.basename(filename)
    # Remove potentially dangerous characters
    filename = re.sub(r'[^\w\s\-\.]', '_', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255 - len(ext)] + ext
    return filename or "upload"


def validate_webhook_url(url: str) -> bool:
    """Validate webhook URL."""
    try:
        parsed = urlparse(url)
        # Only allow http/https schemes
        if parsed.scheme not in ("http", "https"):
            return False
        # Must have a netloc (host)
        if not parsed.netloc:
            return False
        return True
    except Exception:
        return False


@router.post("", response_model=TaskCreateResponse, status_code=202)
async def create_conversion_task(
    file: UploadFile = File(...),
    webhook_url: Optional[str] = Form(None),
    describe_images: bool = Query(False),
):
    """
    Create a new document conversion task.

    The file will be processed asynchronously. Use the returned task_id
    to poll for status or wait for a webhook notification.
    """
    settings = get_settings()

    # Validate webhook URL if provided
    if webhook_url and not validate_webhook_url(webhook_url):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook URL. Must be a valid http/https URL."
        )

    # Generate task ID using ULID for sortability
    task_id = str(ulid.new())

    # Create task directory
    task_dir = Path(settings.data_dir) / "tasks" / task_id
    input_dir = task_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize and save the uploaded file
    safe_filename = sanitize_filename(file.filename or "upload")
    input_path = input_dir / safe_filename

    # Stream file to disk to handle large uploads
    size_bytes = 0
    try:
        with open(input_path, "wb") as f:
            while chunk := await file.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_size:
                    # Clean up and reject
                    f.close()
                    input_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size is {settings.max_upload_size // (1024*1024)}MB"
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save upload for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    # Create task record
    now = datetime.now(timezone.utc)
    task = Task(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        original_filename=safe_filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        describe_images=describe_images,
        webhook_url=webhook_url,
        created_at=now,
    )

    await create_task(task)
    logger.info(f"Created task {task_id} for file {safe_filename} ({size_bytes} bytes)")

    # Enqueue for processing
    enqueue_task(task_id)

    return TaskCreateResponse(task_id=task_id, status=TaskStatus.QUEUED)


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get the status of a conversion task."""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    response = TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        original_filename=task.original_filename,
        size_bytes=task.size_bytes,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )

    if task.status == TaskStatus.COMPLETED:
        response.outputs = task.output_files
    elif task.status == TaskStatus.FAILED:
        response.error_code = task.error_code
        response.error_message = task.error_message

    return response


@router.get("/{task_id}/files/{path:path}")
async def download_task_file(task_id: str, path: str):
    """Download a specific output file from a completed task."""
    settings = get_settings()

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.EXPIRED:
        raise HTTPException(status_code=410, detail="Task outputs have expired")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task is not completed (status: {task.status.value})"
        )

    # Prevent path traversal
    # Normalize path and check for escaping
    safe_path = Path(path)
    if ".." in safe_path.parts or safe_path.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid file path")

    task_dir = Path(settings.data_dir) / "tasks" / task_id
    file_path = task_dir / safe_path

    # Resolve to absolute and verify it's within task directory
    try:
        resolved = file_path.resolve()
        task_dir_resolved = task_dir.resolve()
        if not str(resolved).startswith(str(task_dir_resolved)):
            raise HTTPException(status_code=400, detail="Invalid file path")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream"
    )


@router.get("/{task_id}/download.zip")
async def download_task_zip(task_id: str):
    """Download all task outputs as a zip file."""
    settings = get_settings()

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.EXPIRED:
        raise HTTPException(status_code=410, detail="Task outputs have expired")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task is not completed (status: {task.status.value})"
        )

    task_dir = Path(settings.data_dir) / "tasks" / task_id

    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for output_file in task.output_files:
            file_path = task_dir / output_file
            if file_path.exists():
                zf.write(file_path, output_file)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{task_id}.zip"'
        }
    )
