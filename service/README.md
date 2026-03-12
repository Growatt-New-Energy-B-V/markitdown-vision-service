# markitdown-vision-service

A Dockerized Python service that converts documents to Markdown with optional LLM-powered image descriptions.

## Features

- Asynchronous document conversion via REST API
- PDF support with image extraction
- Optional OpenAI-powered image descriptions with context
- Webhook notifications for task completion
- 24-hour retention with automatic cleanup

## API Endpoints

### Create Task
`POST /tasks` - Upload a document for conversion

### Get Task Status
`GET /tasks/{task_id}` - Check task status

### Cancel Task
`POST /tasks/{task_id}/cancel` - Cancel a queued or running task

### Delete Task
`DELETE /tasks/{task_id}` - Delete a task and all its files

### Download Files
`GET /tasks/{task_id}/files/{path}` - Download a specific output file
`GET /tasks/{task_id}/download.zip` - Download all outputs as zip

### Health Check
`GET /health` - Service health status

## Configuration

Environment variables:

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | OpenAI API key for image descriptions | `""` | Yes (for image descriptions) |
| `OPENAI_BASE_URL` | Override OpenAI base URL (for LLM gateway/proxy routing) | None (uses OpenAI default) | No |
| `OPENAI_VISION_MODEL` | Vision model for image descriptions | `gpt-4o-mini` | No |
| `DATA_DIR` | Data storage directory | `/data` | No |
| `MAX_UPLOAD_SIZE` | Maximum upload size in bytes | `524288000` (500MB) | No |
| `MAX_CONCURRENT_DESCRIPTIONS` | Max parallel OpenAI API calls for image descriptions | `5` | No |
| `DESCRIPTION_MAX_RETRIES` | Retry attempts for failed image descriptions | `3` | No |
| `DESCRIPTION_RETRY_DELAY` | Base delay in seconds for exponential backoff | `1.0` | No |

## Running

```bash
docker build -t markitdown-vision-service .
docker run -p 8000:8000 -v /path/to/data:/data markitdown-vision-service
```
