#!/usr/bin/env python3
"""Convert Markdown to EPUB with proper formatting, metadata, and Chinese support."""

import sys
import os
import re
import subprocess
import tempfile


def extract_title_from_md(md_path):
    """Extract title from the first H1 heading in the markdown file."""
    with open(md_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    # Fallback to filename
    return os.path.splitext(os.path.basename(md_path))[0]


def create_epub_css():
    """Create a CSS file for clean EPUB styling with CJK support."""
    css = """\
body {
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    font-size: 1em;
    line-height: 1.8;
    margin: 1em;
    text-align: justify;
}

h1 {
    font-size: 1.8em;
    font-weight: bold;
    margin: 1.5em 0 0.8em 0;
    text-align: center;
    page-break-before: always;
}

h2 {
    font-size: 1.4em;
    font-weight: bold;
    margin: 1.2em 0 0.6em 0;
    border-bottom: 1px solid #ccc;
    padding-bottom: 0.3em;
}

h3 {
    font-size: 1.2em;
    font-weight: bold;
    margin: 1em 0 0.5em 0;
}

p {
    margin: 0.5em 0;
    text-indent: 2em;
}

blockquote {
    margin: 1em 2em;
    padding: 0.5em 1em;
    border-left: 3px solid #ccc;
    color: #555;
    font-style: italic;
}

blockquote p {
    text-indent: 0;
}

ul, ol {
    margin: 0.5em 0;
    padding-left: 2em;
}

li {
    margin: 0.3em 0;
}

li p {
    text-indent: 0;
}

code {
    font-family: "SF Mono", "Fira Code", "Source Code Pro", monospace;
    font-size: 0.9em;
    background-color: #f5f5f5;
    padding: 0.1em 0.3em;
    border-radius: 3px;
}

pre {
    background-color: #f5f5f5;
    padding: 1em;
    overflow-x: auto;
    border-radius: 5px;
    line-height: 1.4;
}

pre code {
    background: none;
    padding: 0;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

th, td {
    border: 1px solid #ddd;
    padding: 0.5em;
    text-align: left;
}

th {
    background-color: #f5f5f5;
    font-weight: bold;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 2em 0;
}

img {
    max-width: 100%;
    height: auto;
}
"""
    css_path = os.path.join(tempfile.gettempdir(), "epub_style.css")
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(css)
    return css_path


def preprocess_markdown(md_path):
    """Preprocess markdown to clean up common issues before EPUB conversion."""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove page break markers (horizontal rules used as page separators)
    content = re.sub(r"\n---\n", "\n\n", content)

    # Ensure proper spacing around headings
    content = re.sub(r"([^\n])\n(#{1,6} )", r"\1\n\n\2", content)
    content = re.sub(r"(#{1,6} [^\n]+)\n([^\n#])", r"\1\n\n\2", content)

    # Clean up excessive blank lines
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    # Write preprocessed content to temp file
    preprocessed_path = os.path.join(tempfile.gettempdir(), "preprocessed.md")
    with open(preprocessed_path, "w", encoding="utf-8") as f:
        f.write(content)

    return preprocessed_path


def convert_md_to_epub(md_path, output_path, title=None, author=None, lang="zh-CN"):
    """Convert Markdown to EPUB using pandoc."""
    if not os.path.exists(md_path):
        print(f"Error: File not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    # Extract title if not provided
    if not title:
        title = extract_title_from_md(md_path)

    # Create CSS
    css_path = create_epub_css()

    # Preprocess markdown
    preprocessed_path = preprocess_markdown(md_path)

    # Build pandoc command
    cmd = [
        "pandoc",
        preprocessed_path,
        "-o", output_path,
        "--css", css_path,
        "--metadata", f"title={title}",
        "--metadata", f"lang={lang}",
        "--toc",
        "--toc-depth=3",
        "--split-level=2",
        "--epub-title-page=false",
    ]

    if author:
        cmd.extend(["--metadata", f"author={author}"])

    print(f"Converting: {md_path} -> {output_path}", file=sys.stderr)
    print(f"Title: {title}", file=sys.stderr)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Pandoc error: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        print(f"EPUB created: {output_path}", file=sys.stderr)
        return output_path
    except FileNotFoundError:
        print("Error: pandoc not found. Install with: brew install pandoc", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.md> [output.epub] [--title TITLE] [--author AUTHOR] [--lang LANG]", file=sys.stderr)
        sys.exit(1)

    input_md = sys.argv[1]

    # Parse optional arguments
    title = None
    author = None
    lang = "zh-CN"
    output_epub = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--title" and i + 1 < len(sys.argv):
            title = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--author" and i + 1 < len(sys.argv):
            author = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--lang" and i + 1 < len(sys.argv):
            lang = sys.argv[i + 1]
            i += 2
        elif not output_epub:
            output_epub = sys.argv[i]
            i += 1
        else:
            i += 1

    if not output_epub:
        base = os.path.splitext(os.path.basename(input_md))[0]
        output_epub = f"/tmp/{base}.epub"

    convert_md_to_epub(input_md, output_epub, title=title, author=author, lang=lang)
