"""Main FastAPI application."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .routes import tasks_router, health_router
from .workers import start_workers, stop_workers, start_janitor, stop_janitor
from .utils.database import get_db, close_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    settings = get_settings()

    # Ensure data directory exists
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(os.path.join(settings.data_dir, "tasks"), exist_ok=True)

    # Initialize database
    await get_db()
    logger.info("Database initialized")

    # Start workers
    loop = asyncio.get_event_loop()
    start_workers(loop)
    logger.info("Workers started")

    # Start janitor
    start_janitor()
    logger.info("Janitor started")

    logger.info(f"markitdown-vision-service started on {settings.host}:{settings.port}")

    yield

    # Cleanup
    logger.info("Shutting down...")
    stop_janitor()
    stop_workers()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="markitdown-vision-service",
    description="Document to Markdown conversion service with LLM-powered image descriptions",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Register routers
app.include_router(health_router)
app.include_router(tasks_router)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
