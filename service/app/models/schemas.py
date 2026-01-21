"""Pydantic schemas for API requests and responses."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .task import TaskStatus


class TaskCreateResponse(BaseModel):
    """Response for task creation."""
    task_id: str
    status: TaskStatus = TaskStatus.QUEUED


class TaskStatusResponse(BaseModel):
    """Response for task status polling."""
    task_id: str
    status: TaskStatus
    original_filename: str
    size_bytes: int
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    outputs: Optional[list[str]] = None


class WebhookPayload(BaseModel):
    """Payload sent to webhook URLs."""
    task_id: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    outputs: Optional[list[str]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
