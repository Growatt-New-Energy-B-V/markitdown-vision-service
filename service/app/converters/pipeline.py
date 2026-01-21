"""Document conversion pipeline."""
import logging
import re
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..models.task import Task
from .pdf_extractor import extract_pdf_with_images
from .image_describer import describe_images

logger = logging.getLogger(__name__)


async def convert_document(task: Task) -> list[str]:
    """
    Convert a document to Markdown with optional image description.

    Returns a list of output file paths relative to the task directory.
    """
    settings = get_settings()
    task_dir = Path(settings.data_dir) / "tasks" / task.task_id
    input_dir = task_dir / "input"
    images_dir = task_dir / "images"

    # Find the input file
    input_files = list(input_dir.iterdir())
    if not input_files:
        raise ValueError("No input file found")
    input_path = input_files[0]

    logger.info(f"Converting {input_path} for task {task.task_id}")

    # Detect format and convert
    extension = input_path.suffix.lower()

    if extension == ".pdf":
        # Extract PDF with images
        markdown_content, image_refs = await extract_pdf_with_images(
            input_path, images_dir
        )
    else:
        # For other formats, use basic markitdown
        # This can be extended later for DOCX, PPTX, etc.
        raise ValueError(f"Unsupported file format: {extension}")

    # If image description is requested and we have images
    if task.describe_images and image_refs:
        settings = get_settings()
        if settings.openai_api_token:
            markdown_content = await describe_images(
                markdown_content, image_refs, images_dir
            )
        else:
            logger.warning(
                f"Task {task.task_id} requested image descriptions but "
                "OPENAI_API_TOKEN is not set"
            )

    # Write the output markdown
    output_md_path = task_dir / f"{task.task_id}.md"
    output_md_path.write_text(markdown_content, encoding="utf-8")

    # Build output file list
    output_files = [f"{task.task_id}.md"]
    if images_dir.exists():
        for img_path in sorted(images_dir.iterdir()):
            output_files.append(f"images/{img_path.name}")

    logger.info(
        f"Task {task.task_id} converted: {len(output_files)} output files"
    )
    return output_files
