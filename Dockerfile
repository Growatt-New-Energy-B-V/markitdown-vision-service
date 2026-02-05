FROM python:3.13-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
ENV EXIFTOOL_PATH=/usr/bin/exiftool
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV PYTHONUNBUFFERED=1

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install the markitdown package first (for caching)
COPY packages/markitdown /app/packages/markitdown
RUN pip --no-cache-dir install /app/packages/markitdown[all]

# Copy and install the service with test dependencies
COPY service /app/service
RUN pip --no-cache-dir install "/app/service[test]"

# Copy test resources
COPY .claude/resources /app/resources

# Create non-root user and data directory
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser \
    && mkdir -p /data/tasks \
    && chown -R 1000:1000 /data /app

USER 1000:1000

# Expose the service port
EXPOSE 8000

# Set environment defaults
ENV DATA_DIR=/data
ENV DB_PATH=/data/task_db.sqlite
ENV HOST=0.0.0.0
ENV PORT=8000
ENV E2E_RESOURCES_DIR=/app/resources

# Default command runs the service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
