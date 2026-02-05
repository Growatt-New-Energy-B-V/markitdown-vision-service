"""Tests for task endpoints."""

import asyncio
import os
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_create_task_missing_file(client):
    """Test task creation without file."""
    response = await client.post("/tasks")
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_get_task_not_found(client):
    """Test getting non-existent task."""
    response = await client.get("/tasks/nonexistent-task-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_task_with_invalid_webhook(client, test_data_dir):
    """Test task creation with invalid webhook URL."""
    # Create a simple test file
    test_file = test_data_dir / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4 test content")

    with open(test_file, "rb") as f:
        response = await client.post(
            "/tasks",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"webhook_url": "not-a-valid-url"},
        )

    assert response.status_code == 400
    assert "Invalid webhook URL" in response.json()["detail"]


@pytest.mark.asyncio
async def test_download_file_path_traversal(client):
    """Test that path traversal is blocked."""
    response = await client.get("/tasks/some-task/files/../../../etc/passwd")
    assert response.status_code in (400, 404)


class TestE2EWithResources:
    """E2E tests that require resource files."""

    @pytest.mark.asyncio
    async def test_convert_pdf_basic(self, client, e2e_resources_dir):
        """Test basic PDF conversion."""
        pdf_path = e2e_resources_dir / "image-doc.pdf"
        if not pdf_path.exists():
            pytest.skip(f"Test file not found: {pdf_path}")

        # Create task
        with open(pdf_path, "rb") as f:
            response = await client.post(
                "/tasks",
                files={"file": ("image-doc.pdf", f, "application/pdf")},
            )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "queued"

        task_id = data["task_id"]

        # Poll for completion
        max_attempts = 60
        for _ in range(max_attempts):
            response = await client.get(f"/tasks/{task_id}")
            assert response.status_code == 200
            status_data = response.json()

            if status_data["status"] == "completed":
                break
            elif status_data["status"] == "failed":
                pytest.fail(f"Task failed: {status_data.get('error_message')}")

            await asyncio.sleep(1)
        else:
            pytest.fail("Task did not complete in time")

        # Verify outputs
        assert "outputs" in status_data
        assert len(status_data["outputs"]) > 0
        assert f"{task_id}.md" in status_data["outputs"]

        # Download markdown file
        response = await client.get(f"/tasks/{task_id}/files/{task_id}.md")
        assert response.status_code == 200
        md_content = response.text
        assert len(md_content) > 0

    @pytest.mark.asyncio
    async def test_convert_pdf_with_images(self, client, e2e_resources_dir):
        """Test PDF conversion extracts images."""
        pdf_path = e2e_resources_dir / "image-doc.pdf"
        if not pdf_path.exists():
            pytest.skip(f"Test file not found: {pdf_path}")

        # Create task
        with open(pdf_path, "rb") as f:
            response = await client.post(
                "/tasks",
                files={"file": ("image-doc.pdf", f, "application/pdf")},
                params={"describe_images": "false"},
            )

        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # Poll for completion
        max_attempts = 60
        for _ in range(max_attempts):
            response = await client.get(f"/tasks/{task_id}")
            status_data = response.json()

            if status_data["status"] == "completed":
                break
            elif status_data["status"] == "failed":
                pytest.fail(f"Task failed: {status_data.get('error_message')}")

            await asyncio.sleep(1)
        else:
            pytest.fail("Task did not complete in time")

        # Check if images were extracted
        outputs = status_data["outputs"]
        image_files = [f for f in outputs if f.startswith("images/")]
        assert len(image_files) > 0, "Expected images to be extracted"

        # Download an image
        if image_files:
            response = await client.get(f"/tasks/{task_id}/files/{image_files[0]}")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_convert_pdf_with_image_descriptions(self, client, e2e_resources_dir):
        """Test PDF conversion with image descriptions enabled."""
        # Skip if no OpenAI token
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        pdf_path = e2e_resources_dir / "image-doc.pdf"
        if not pdf_path.exists():
            pytest.skip(f"Test file not found: {pdf_path}")

        # Create task with image descriptions
        with open(pdf_path, "rb") as f:
            response = await client.post(
                "/tasks",
                files={"file": ("image-doc.pdf", f, "application/pdf")},
                params={"describe_images": "true"},
            )

        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # Poll for completion (longer timeout for LLM calls)
        max_attempts = 120
        for _ in range(max_attempts):
            response = await client.get(f"/tasks/{task_id}")
            status_data = response.json()

            if status_data["status"] == "completed":
                break
            elif status_data["status"] == "failed":
                pytest.fail(f"Task failed: {status_data.get('error_message')}")

            await asyncio.sleep(1)
        else:
            pytest.fail("Task did not complete in time")

        # Download and check markdown has descriptions
        response = await client.get(f"/tasks/{task_id}/files/{task_id}.md")
        assert response.status_code == 200
        md_content = response.text

        # Check for image description format from PDR
        # Image pX-iY: description
        assert "Image p" in md_content
        # Should have context tags if context was available
        # This is optional depending on whether context was found

    @pytest.mark.asyncio
    async def test_download_zip(self, client, e2e_resources_dir):
        """Test downloading task outputs as zip."""
        pdf_path = e2e_resources_dir / "image-doc.pdf"
        if not pdf_path.exists():
            pytest.skip(f"Test file not found: {pdf_path}")

        # Create and wait for task
        with open(pdf_path, "rb") as f:
            response = await client.post(
                "/tasks",
                files={"file": ("image-doc.pdf", f, "application/pdf")},
            )

        task_id = response.json()["task_id"]

        # Poll for completion
        for _ in range(60):
            response = await client.get(f"/tasks/{task_id}")
            if response.json()["status"] == "completed":
                break
            await asyncio.sleep(1)

        # Download zip
        response = await client.get(f"/tasks/{task_id}/download.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    @pytest.mark.asyncio
    async def test_large_pdf(self, client, e2e_resources_dir):
        """Test conversion of a larger PDF."""
        pdf_path = e2e_resources_dir / "large-doc.pdf"
        if not pdf_path.exists():
            pytest.skip(f"Test file not found: {pdf_path}")

        # Create task
        with open(pdf_path, "rb") as f:
            response = await client.post(
                "/tasks",
                files={"file": ("large-doc.pdf", f, "application/pdf")},
            )

        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # Poll for completion (longer timeout for large files)
        max_attempts = 180
        for _ in range(max_attempts):
            response = await client.get(f"/tasks/{task_id}")
            status_data = response.json()

            if status_data["status"] == "completed":
                break
            elif status_data["status"] == "failed":
                pytest.fail(f"Task failed: {status_data.get('error_message')}")

            await asyncio.sleep(1)
        else:
            pytest.fail("Task did not complete in time")

        # Verify outputs exist
        assert "outputs" in status_data
        assert f"{task_id}.md" in status_data["outputs"]
