"""Task model for database operations."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import json


class TaskStatus(str, Enum):
    """Task status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class Task:
    """Task record for database storage."""
    task_id: str
    status: TaskStatus
    original_filename: str
    content_type: Optional[str]
    size_bytes: int
    describe_images: bool
    webhook_url: Optional[str]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    output_files: list[str] = field(default_factory=list)
    webhook_last_status: Optional[int] = None
    webhook_last_attempt_at: Optional[datetime] = None
    webhook_attempt_count: int = 0

    def __post_init__(self):
        if self.expires_at is None and self.created_at:
            self.expires_at = self.created_at + timedelta(hours=24)

    def to_dict(self) -> dict:
        """Convert task to dictionary for database storage."""
        return {
            "task_id": self.task_id,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "describe_images": int(self.describe_images),
            "webhook_url": self.webhook_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "output_files": json.dumps(self.output_files),
            "webhook_last_status": self.webhook_last_status,
            "webhook_last_attempt_at": self.webhook_last_attempt_at.isoformat() if self.webhook_last_attempt_at else None,
            "webhook_attempt_count": self.webhook_attempt_count,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        """Create Task from database row."""
        return cls(
            task_id=row["task_id"],
            status=TaskStatus(row["status"]),
            original_filename=row["original_filename"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            describe_images=bool(row["describe_images"]),
            webhook_url=row["webhook_url"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            output_files=json.loads(row["output_files"]) if row["output_files"] else [],
            webhook_last_status=row["webhook_last_status"],
            webhook_last_attempt_at=datetime.fromisoformat(row["webhook_last_attempt_at"]) if row["webhook_last_attempt_at"] else None,
            webhook_attempt_count=row["webhook_attempt_count"] or 0,
        )
