"""SQLite database operations for task management."""
import aiosqlite
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models.task import Task, TaskStatus
from ..config import get_settings

logger = logging.getLogger(__name__)

# Global database connection
_db_connection: Optional[aiosqlite.Connection] = None
_db_lock = asyncio.Lock()


CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    describe_images INTEGER NOT NULL DEFAULT 0,
    webhook_url TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    expires_at TEXT,
    error_code TEXT,
    error_message TEXT,
    output_files TEXT,
    webhook_last_status INTEGER,
    webhook_last_attempt_at TEXT,
    webhook_attempt_count INTEGER DEFAULT 0
)
"""

CREATE_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
"""

CREATE_INDEX_EXPIRES = """
CREATE INDEX IF NOT EXISTS idx_tasks_expires_at ON tasks(expires_at)
"""


async def get_db() -> aiosqlite.Connection:
    """Get the database connection, creating it if needed."""
    global _db_connection
    async with _db_lock:
        if _db_connection is None:
            settings = get_settings()
            # Ensure data directory exists
            db_path = Path(settings.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            _db_connection = await aiosqlite.connect(str(db_path))
            _db_connection.row_factory = aiosqlite.Row

            # Create tables
            await _db_connection.execute(CREATE_TASKS_TABLE)
            await _db_connection.execute(CREATE_INDEX_STATUS)
            await _db_connection.execute(CREATE_INDEX_EXPIRES)
            await _db_connection.commit()
            logger.info(f"Database initialized at {db_path}")

        return _db_connection


async def close_db():
    """Close the database connection."""
    global _db_connection
    async with _db_lock:
        if _db_connection is not None:
            await _db_connection.close()
            _db_connection = None
            logger.info("Database connection closed")


async def create_task(task: Task) -> Task:
    """Create a new task in the database."""
    db = await get_db()
    data = task.to_dict()
    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    values = list(data.values())

    await db.execute(
        f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
        values
    )
    await db.commit()
    logger.info(f"Task {task.task_id} created with status {task.status}")
    return task


async def get_task(task_id: str) -> Optional[Task]:
    """Get a task by ID."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks WHERE task_id = ?",
        (task_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return Task.from_row(dict(row))
    return None


async def update_task_status(
    task_id: str,
    status: TaskStatus,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    output_files: Optional[list[str]] = None,
) -> Optional[Task]:
    """Update task status and related fields."""
    db = await get_db()

    updates = ["status = ?"]
    values = [status.value]

    if started_at is not None:
        updates.append("started_at = ?")
        values.append(started_at.isoformat())

    if finished_at is not None:
        updates.append("finished_at = ?")
        values.append(finished_at.isoformat())

    if error_code is not None:
        updates.append("error_code = ?")
        values.append(error_code)

    if error_message is not None:
        updates.append("error_message = ?")
        values.append(error_message)

    if output_files is not None:
        updates.append("output_files = ?")
        values.append(json.dumps(output_files))

    values.append(task_id)
    query = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?"

    await db.execute(query, values)
    await db.commit()
    logger.info(f"Task {task_id} updated to status {status}")

    return await get_task(task_id)


async def update_webhook_status(
    task_id: str,
    status_code: int,
    attempt_count: int,
) -> None:
    """Update webhook delivery status."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """UPDATE tasks
           SET webhook_last_status = ?,
               webhook_last_attempt_at = ?,
               webhook_attempt_count = ?
           WHERE task_id = ?""",
        (status_code, now, attempt_count, task_id)
    )
    await db.commit()


async def get_queued_tasks(limit: int = 10) -> list[Task]:
    """Get tasks that are queued and ready for processing."""
    db = await get_db()
    async with db.execute(
        """SELECT * FROM tasks
           WHERE status = ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (TaskStatus.QUEUED.value, limit)
    ) as cursor:
        rows = await cursor.fetchall()
        return [Task.from_row(dict(row)) for row in rows]


async def get_expired_tasks() -> list[Task]:
    """Get tasks that have expired and need cleanup."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    async with db.execute(
        """SELECT * FROM tasks
           WHERE status IN (?, ?)
           AND expires_at < ?""",
        (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, now)
    ) as cursor:
        rows = await cursor.fetchall()
        return [Task.from_row(dict(row)) for row in rows]


async def mark_task_expired(task_id: str) -> None:
    """Mark a task as expired after cleanup."""
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET status = ? WHERE task_id = ?",
        (TaskStatus.EXPIRED.value, task_id)
    )
    await db.commit()
    logger.info(f"Task {task_id} marked as expired")


async def cancel_task(task_id: str) -> Optional[Task]:
    """
    Cancel a task if it's in a cancellable state (queued or running).

    Returns the updated task if cancelled, None if task not found.
    Raises ValueError if task cannot be cancelled.
    """
    task = await get_task(task_id)
    if not task:
        return None

    if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
        raise ValueError(
            f"Task cannot be cancelled (status: {task.status.value})"
        )

    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """UPDATE tasks
           SET status = ?, finished_at = ?
           WHERE task_id = ?""",
        (TaskStatus.CANCELLED.value, now, task_id)
    )
    await db.commit()
    logger.info(f"Task {task_id} cancelled")

    return await get_task(task_id)


async def delete_task(task_id: str) -> bool:
    """
    Delete a task from the database.

    Returns True if deleted, False if not found.
    """
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM tasks WHERE task_id = ?",
        (task_id,)
    )
    await db.commit()
    deleted = cursor.rowcount > 0
    if deleted:
        logger.info(f"Task {task_id} deleted from database")
    return deleted
