"""LLM-powered image description."""
import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

from ..config import get_settings
from .pdf_extractor import ImageRef

logger = logging.getLogger(__name__)


async def describe_images(
    markdown_content: str,
    image_refs: list[ImageRef],
    images_dir: Path,
) -> str:
    """
    Add LLM-generated descriptions to images in the markdown.

    For each image, inserts:
    - Context before the image
    - Image description from LLM
    - Context after the image
    """
    settings = get_settings()

    if not settings.openai_api_token:
        logger.warning("No OpenAI API token configured, skipping image descriptions")
        return markdown_content

    client = AsyncOpenAI(api_key=settings.openai_api_token)

    # Process each image
    for ref in image_refs:
        try:
            description = await _get_image_description(
                client, ref, images_dir
            )

            # Build the description block according to PDR spec
            description_block = _build_description_block(ref, description)

            # Replace the image markdown with description block
            # Original: ![p3-i3](images/p3-i3.png)
            # New: context + description block
            old_pattern = f"![{ref.image_id}](images/{ref.filename})"
            markdown_content = markdown_content.replace(
                old_pattern, description_block
            )

        except Exception as e:
            logger.error(f"Failed to describe image {ref.image_id}: {e}")
            # Insert error message instead
            error_block = _build_description_block(
                ref, f"description unavailable (LLM error: {str(e)[:100]})"
            )
            old_pattern = f"![{ref.image_id}](images/{ref.filename})"
            markdown_content = markdown_content.replace(old_pattern, error_block)

    return markdown_content


async def _get_image_description(
    client: AsyncOpenAI,
    ref: ImageRef,
    images_dir: Path,
) -> str:
    """Get description for a single image using OpenAI Vision."""
    image_path = images_dir / ref.filename

    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Read and encode image
    image_data = image_path.read_bytes()
    image_b64 = base64.b64encode(image_data).decode("utf-8")

    # Determine media type
    ext = image_path.suffix.lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"

    # Build prompt with context
    context_prompt = ""
    if ref.context_before:
        context_prompt += f"Text before the image: {ref.context_before}\n\n"
    if ref.context_after:
        context_prompt += f"Text after the image: {ref.context_after}\n\n"

    system_prompt = """You are an expert at describing images in documents.
Your task is to provide a clear, concise description of the image that helps
someone understand what the image shows and how it relates to the surrounding text.

Keep descriptions factual and focused. If the image contains text, include the
key textual content. If it's a diagram, chart, or figure, describe what it shows.
For photos, describe the subject matter."""

    user_prompt = f"""Please describe this image from a document.

{context_prompt}Provide a clear, concise description of what the image shows."""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                            "detail": "auto",
                        },
                    },
                ],
            },
        ],
        max_tokens=500,
    )

    description = response.choices[0].message.content
    return description.strip() if description else "No description available"


def _build_description_block(ref: ImageRef, description: str) -> str:
    """Build the description block according to PDR specification."""
    # Format from PDR:
    # <context before image p3-i3>
    # Image p3-i3: the image describes .....
    # <context after image p3-i3>

    lines = []

    # Context before (may be empty)
    if ref.context_before:
        lines.append(ref.context_before)
        lines.append("")

    # Image reference and description
    lines.append(f"![{ref.image_id}](images/{ref.filename})")
    lines.append(f"Image {ref.image_id}: {description}")
    lines.append("")

    # Context after (may be empty)
    if ref.context_after:
        lines.append(ref.context_after)

    return "\n".join(lines)
