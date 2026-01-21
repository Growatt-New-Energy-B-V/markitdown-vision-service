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

## Running

```bash
docker build -t markitdown-vision-service .
docker run -p 8000:8000 -v /path/to/data:/data markitdown-vision-service
```
