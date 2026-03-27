#!/usr/bin/env python3
"""Convert PDF to Markdown with heading detection, table extraction, and OCR fallback."""

import sys
import os
import re


def extract_with_pdfplumber(pdf_path):
    """Extract text and tables using pdfplumber with font-based heading detection."""
    import pdfplumber

    md_parts = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if page_idx > 0:
                md_parts.append("\n---\n")

            # Extract tables first to know which areas are tables
            tables = page.extract_tables()
            table_bboxes = []
            if hasattr(page, 'find_tables'):
                for t in page.find_tables():
                    table_bboxes.append(t.bbox)

            # Try to extract text with character-level info for heading detection
            chars = page.chars
            if chars:
                lines = _chars_to_markdown_lines(chars)
                md_parts.append("\n".join(lines))
            else:
                text = page.extract_text()
                if text:
                    md_parts.append(text)

            # Add tables as markdown tables
            for table in tables:
                if table and len(table) > 0:
                    md_parts.append("")
                    md_parts.append(_table_to_markdown(table))
                    md_parts.append("")

    return "\n".join(md_parts)


# Default heading detection thresholds (font size ratio relative to median)
HEADING_THRESHOLDS = {
    "h1": 1.8,       # ratio >= 1.8 → H1
    "h2": 1.4,       # ratio >= 1.4 → H2
    "h3": 1.15,      # ratio >= 1.15 → H3
    "h3_bold": 1.05,  # bold + ratio >= 1.05 → H3
}


def _chars_to_markdown_lines(chars, heading_thresholds=None):
    """Group characters into lines and detect headings based on font size."""
    if not chars:
        return []

    thresholds = {**HEADING_THRESHOLDS, **(heading_thresholds or {})}

    # Group chars by approximate y-position (same line)
    lines_dict = {}
    for c in chars:
        y_key = round(c.get("top", 0), 0)
        # Find existing line within tolerance
        matched = False
        for existing_y in list(lines_dict.keys()):
            if abs(existing_y - y_key) < 3:
                lines_dict[existing_y].append(c)
                matched = True
                break
        if not matched:
            lines_dict[y_key] = [c]

    # Sort lines by y position (top to bottom)
    sorted_lines = sorted(lines_dict.items(), key=lambda x: x[0])

    # Collect font sizes to determine what's "normal"
    all_sizes = []
    for _, line_chars in sorted_lines:
        sizes = [c.get("size", 12) for c in line_chars]
        if sizes:
            all_sizes.extend(sizes)

    if not all_sizes:
        return []

    # Use median as "normal" size
    all_sizes.sort()
    normal_size = all_sizes[len(all_sizes) // 2]

    md_lines = []
    for _, line_chars in sorted_lines:
        # Sort chars left to right
        line_chars.sort(key=lambda c: c.get("x0", 0))
        text = "".join(c.get("text", "") for c in line_chars).strip()
        if not text:
            md_lines.append("")
            continue

        # Determine heading level based on font size relative to normal
        avg_size = sum(c.get("size", 12) for c in line_chars) / len(line_chars)
        is_bold = any("bold" in str(c.get("fontname", "")).lower() for c in line_chars)

        ratio = avg_size / normal_size if normal_size > 0 else 1

        if ratio >= thresholds["h1"]:
            text = f"# {text}"
        elif ratio >= thresholds["h2"]:
            text = f"## {text}"
        elif ratio >= thresholds["h3"] or (is_bold and ratio >= thresholds["h3_bold"]):
            text = f"### {text}"
        elif is_bold and len(text) < 100:
            text = f"**{text}**"

        # Detect list items
        if re.match(r"^[•·‣▪◦]\s*", text):
            text = re.sub(r"^[•·‣▪◦]\s*", "- ", text)
        elif re.match(r"^\d+[.)]\s+", text):
            pass  # Already numbered list format

        md_lines.append(text)

    return md_lines


def _table_to_markdown(table):
    """Convert a table (list of rows) to GitHub Flavored Markdown table."""
    if not table or len(table) == 0:
        return ""

    # Clean cells
    cleaned = []
    for row in table:
        cleaned_row = []
        for cell in row:
            cell_text = str(cell) if cell is not None else ""
            cell_text = cell_text.replace("\n", " ").replace("|", "\\|").strip()
            cleaned_row.append(cell_text)
        cleaned.append(cleaned_row)

    # Ensure all rows have same number of columns
    max_cols = max(len(row) for row in cleaned)
    for row in cleaned:
        while len(row) < max_cols:
            row.append("")

    lines = []
    # Header row
    lines.append("| " + " | ".join(cleaned[0]) + " |")
    # Separator
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    # Data rows
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def extract_with_pypdf(pdf_path):
    """Fallback: extract text using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    md_parts = []

    for i, page in enumerate(reader.pages):
        if i > 0:
            md_parts.append("\n---\n")
        text = page.extract_text()
        if text:
            md_parts.append(text)

    return "\n".join(md_parts)


def _ocr_single_page(args):
    """OCR a single page image. Used by multiprocessing pool."""
    import pytesseract
    idx, image_path, lang = args
    from PIL import Image
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang=lang)
    return idx, text.strip() if text else ""


def extract_with_ocr(pdf_path, ocr_lang="chi_sim+eng", ocr_workers=None):
    """Fallback for scanned PDFs: use OCR with batch multiprocessing."""
    from pdf2image import convert_from_path
    import tempfile
    from multiprocessing import Pool, cpu_count

    images = convert_from_path(pdf_path, dpi=300)

    # Save images to temp files for multiprocessing (PIL images can't be pickled)
    temp_dir = tempfile.mkdtemp(prefix="bookforge_ocr_")
    temp_paths = []
    for i, image in enumerate(images):
        path = os.path.join(temp_dir, f"page_{i:04d}.png")
        image.save(path)
        temp_paths.append((i, path, ocr_lang))

    workers = ocr_workers or min(cpu_count(), len(images), 4)
    print(f"OCR: {len(images)} pages with {workers} workers", file=sys.stderr)

    results = {}
    with Pool(processes=workers) as pool:
        for idx, text in pool.imap_unordered(_ocr_single_page, temp_paths):
            results[idx] = text

    # Clean up temp files
    for _, path, _ in temp_paths:
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass

    # Assemble in order
    md_parts = []
    for i in range(len(images)):
        if i > 0:
            md_parts.append("\n---\n")
        if results.get(i):
            md_parts.append(results[i])

    return "\n".join(md_parts)


def convert_pdf_to_markdown(pdf_path, output_path):
    """Main conversion function with multiple fallback strategies."""
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    markdown = ""

    # Strategy 1: pdfplumber (best for structured PDFs)
    try:
        markdown = extract_with_pdfplumber(pdf_path)
        if markdown and len(markdown.strip()) > 50:
            print("Extracted using pdfplumber", file=sys.stderr)
        else:
            raise ValueError("Insufficient text extracted")
    except Exception as e:
        print(f"pdfplumber failed: {e}", file=sys.stderr)

        # Strategy 2: pypdf
        try:
            markdown = extract_with_pypdf(pdf_path)
            if markdown and len(markdown.strip()) > 50:
                print("Extracted using pypdf", file=sys.stderr)
            else:
                raise ValueError("Insufficient text extracted")
        except Exception as e2:
            print(f"pypdf failed: {e2}", file=sys.stderr)

            # Strategy 3: OCR
            try:
                markdown = extract_with_ocr(pdf_path)
                print("Extracted using OCR", file=sys.stderr)
            except Exception as e3:
                print(f"OCR failed: {e3}", file=sys.stderr)
                print("All extraction methods failed.", file=sys.stderr)
                sys.exit(1)

    # Post-process: clean up excessive blank lines
    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"Output written to: {output_path}", file=sys.stderr)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.pdf> [output.md]", file=sys.stderr)
        sys.exit(1)

    input_pdf = sys.argv[1]

    if len(sys.argv) >= 3:
        output_md = sys.argv[2]
    else:
        base = os.path.splitext(os.path.basename(input_pdf))[0]
        output_md = f"/tmp/{base}.md"

    convert_pdf_to_markdown(input_pdf, output_md)
