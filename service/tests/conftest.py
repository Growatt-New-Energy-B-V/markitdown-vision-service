"""Pytest configuration and fixtures."""
import os
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def e2e_resources_dir():
    """Get E2E resources directory from environment."""
    resources = os.environ.get("E2E_RESOURCES_DIR")
    if not resources:
        pytest.skip("E2E_RESOURCES_DIR not set")
    resources_path = Path(resources)
    if not resources_path.exists():
        pytest.skip(f"E2E_RESOURCES_DIR does not exist: {resources}")
    return resources_path


@pytest.fixture(scope="session")
def test_data_dir():
    """Get the test data directory."""
    tmpdir = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmpdir
    os.environ["DB_PATH"] = os.path.join(tmpdir, "test_db.sqlite")
    return Path(tmpdir)


@pytest_asyncio.fixture
async def client(test_data_dir):
    """Create async test client with proper lifespan."""
    # Reset settings to pick up test environment
    from app.config import reset_settings
    reset_settings()

    # Import app after setting environment
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup
        from app.utils.database import get_db, close_db
        from app.workers import start_workers, stop_workers, start_janitor, stop_janitor
        import asyncio

        await get_db()
        loop = asyncio.get_event_loop()
        start_workers(loop)
        start_janitor()

        try:
            yield ac
        finally:
            stop_janitor()
            stop_workers()
            await close_db()
