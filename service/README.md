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
- `OPENAI_API_TOKEN` - OpenAI API key for image descriptions
- `DATA_DIR` - Data storage directory (default: `/data`)
- `MAX_UPLOAD_SIZE` - Maximum upload size in bytes (default: 500MB)
- `MAX_CONCURRENT_DESCRIPTIONS` - Max parallel OpenAI API calls for image descriptions (default: 5)
- `DESCRIPTION_MAX_RETRIES` - Retry attempts for failed image descriptions (default: 3)
- `DESCRIPTION_RETRY_DELAY` - Base delay in seconds for exponential backoff (default: 1.0)

## Running

```bash
docker build -t markitdown-vision-service .
docker run -p 8000:8000 -v /path/to/data:/data markitdown-vision-service
```
