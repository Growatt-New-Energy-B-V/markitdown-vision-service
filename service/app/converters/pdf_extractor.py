"""PDF extraction using markitdown library with image support."""
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdfplumber
from PIL import Image
from markitdown import MarkItDown, ExtractedImage

logger = logging.getLogger(__name__)


@dataclass
class ImageRef:
    """Reference to an extracted image."""
    image_id: str  # e.g., "p3-i2"
    page: int
    index: int  # index within page
    filename: str
    context_before: str
    context_after: str


async def extract_pdf_with_images(
    pdf_path: Path,
    output_images_dir: Path,
    context_chars: int = 500,
) -> tuple[str, list[ImageRef]]:
    """
    Extract text and images from a PDF using markitdown library.

    Uses markitdown for both text and image extraction.

    Returns:
        - Markdown content with image placeholders inserted
        - List of ImageRef objects with context
    """
    output_images_dir.mkdir(parents=True, exist_ok=True)

    # Get total page count from PDF
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    # Use markitdown for text and image extraction
    logger.info(f"Extracting text and images from {pdf_path} using markitdown")
    md = MarkItDown()
    result = md.convert(str(pdf_path), extract_images=True, context_chars=context_chars)
    markdown_content = result.text_content

    # Insert page locators
    markdown_content = _insert_page_locators(markdown_content, total_pages)

    # Process extracted images
    image_refs: list[ImageRef] = []
    for extracted_img in result.images:
        # Save image to output directory
        filename = _save_extracted_image(extracted_img, output_images_dir)
        if not filename:
            continue

        image_refs.append(ImageRef(
            image_id=extracted_img.image_id,
            page=extracted_img.page or 0,
            index=extracted_img.index or 0,
            filename=filename,
            context_before=extracted_img.context_before,
            context_after=extracted_img.context_after,
        ))

    logger.info(f"Extracted {len(image_refs)} images")

    # Insert image references into markdown
    if image_refs:
        markdown_content = _insert_image_references(markdown_content, image_refs)

    return markdown_content, image_refs


def _save_extracted_image(
    extracted_img: ExtractedImage,
    output_dir: Path,
) -> Optional[str]:
    """Save an ExtractedImage to a file."""
    try:
        raw_data = extracted_img.data
        image_id = extracted_img.image_id
        image_format = extracted_img.format

        # Check if it's already JPEG by looking at magic bytes
        if raw_data[:2] == b'\xff\xd8':
            filename = f"{image_id}.jpeg"
            (output_dir / filename).write_bytes(raw_data)
            return filename

        # Check if it's PNG
        if raw_data[:8] == b'\x89PNG\r\n\x1a\n':
            filename = f"{image_id}.png"
            (output_dir / filename).write_bytes(raw_data)
            return filename

        # Try to decode and save as PNG using PIL
        pil_img = None

        # Try letting PIL figure it out
        try:
            pil_img = Image.open(io.BytesIO(raw_data))
        except Exception:
            pass

        # Try raw pixel data if we have dimensions
        if pil_img is None and extracted_img.width and extracted_img.height:
            for mode in ["RGB", "L", "RGBA"]:
                try:
                    bytes_per_pixel = {"RGB": 3, "L": 1, "RGBA": 4}.get(mode, 3)
                    expected_size = extracted_img.width * extracted_img.height * bytes_per_pixel
                    if len(raw_data) >= expected_size:
                        pil_img = Image.frombytes(
                            mode,
                            (extracted_img.width, extracted_img.height),
                            raw_data[:expected_size]
                        )
                        break
                except Exception:
                    continue

        if pil_img:
            # Convert CMYK to RGB for web compatibility
            if pil_img.mode == "CMYK":
                pil_img = pil_img.convert("RGB")

            filename = f"{image_id}.png"
            pil_img.save(output_dir / filename, "PNG")
            return filename

        logger.warning(f"Could not decode image {image_id}")
        return None

    except Exception as e:
        logger.warning(f"Failed to save image {extracted_img.image_id}: {e}")
        return None


def _insert_page_locators(markdown_content: str, total_pages: int) -> str:
    """Insert page locator HTML comments into markdown content."""
    lines = markdown_content.split('\n')
    result_lines: list[str] = []
    current_page = 1

    # Insert locator for page 1 at the top
    result_lines.append(f'<!-- Page {current_page} / {total_pages} -->')

    for line in lines:
        result_lines.append(line)

        # Detect page breaks (horizontal rules or form feeds)
        if line.strip() in ('---', '***', '___') or '\f' in line:
            current_page += 1
            result_lines.append(f'<!-- Page {current_page} / {total_pages} -->')

    return '\n'.join(result_lines)


def _insert_image_references(
    markdown_content: str,
    image_refs: list[ImageRef],
) -> str:
    """Insert image references into markdown content."""
    # Group images by page
    images_by_page: dict[int, list[ImageRef]] = {}
    for ref in image_refs:
        if ref.page not in images_by_page:
            images_by_page[ref.page] = []
        images_by_page[ref.page].append(ref)

    # Sort images within each page by index
    for page_images in images_by_page.values():
        page_images.sort(key=lambda x: x.index)

    # Split markdown by page separators (--- or multiple newlines)
    # and insert images at appropriate positions
    lines = markdown_content.split('\n')
    result_lines: list[str] = []

    current_page = 1

    for line in lines:
        result_lines.append(line)

        # Detect page breaks (horizontal rules or form feeds)
        if line.strip() in ('---', '***', '___') or '\f' in line:
            # Insert images for the current page before moving to next
            if current_page in images_by_page:
                for ref in images_by_page[current_page]:
                    result_lines.append('')
                    result_lines.append(f'![{ref.image_id}](images/{ref.filename})')
                del images_by_page[current_page]

            current_page += 1

    # Insert any remaining images at the end
    for page_num in sorted(images_by_page.keys()):
        for ref in images_by_page[page_num]:
            result_lines.append('')
            result_lines.append(f'![{ref.image_id}](images/{ref.filename})')

    return '\n'.join(result_lines)
