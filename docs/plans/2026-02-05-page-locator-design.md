# Page Locator in Markdown Output

## Goal

Add invisible HTML comment page locators (`<!-- Page X / N -->`) to the markdown output generated from PDFs, so each page is machine-identifiable without affecting rendered output.

## Design

### Format

```
<!-- Page 1 / 3 -->
```

- HTML comment: invisible when rendered, machine-readable
- Every page gets a locator, including page 1 (at the top of the document)
- Total page count is read from the PDF file via `pdfplumber`

### Changes to `service/app/converters/pdf_extractor.py`

1. **New function `_insert_page_locators(markdown_content: str, total_pages: int) -> str`**
   - Inserts `<!-- Page 1 / N -->` at the top of the markdown
   - Inserts `<!-- Page X / N -->` after each page separator (`---`, `***`, `___`, `\f`)
   - Tracks `current_page` similarly to `_insert_image_references`

2. **Update `extract_pdf_with_images`**
   - Use `pdfplumber.open(pdf_path)` to get `total_pages = len(pdf.pages)`
   - Call `_insert_page_locators(markdown_content, total_pages)` unconditionally
   - Continue calling `_insert_image_references` only when images exist

### Output Example

```markdown
<!-- Page 1 / 3 -->
Content of page 1...

---

<!-- Page 2 / 3 -->
Content of page 2...

---

<!-- Page 3 / 3 -->
Content of page 3...
```

### Dependencies

- `pdfplumber` (already in `service/pyproject.toml`)
