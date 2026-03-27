#!/usr/bin/env python3
"""Translate Markdown files with structure-aware chunking, parallel execution, and resume support.

Usage:
    python3 translate_md.py <input.md> <output.md> --engine deepl --target zh [--workers 4]

Engines: deepl, openai, gemini, claude, openrouter
"""

import sys
import os
import re
import json
import hashlib
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add script directory to path for translator import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translator import get_engine, get_lang_name, ENGINES


# ---------------------------------------------------------------------------
# Structure-aware Markdown chunking
# ---------------------------------------------------------------------------

def parse_structural_blocks(md_text: str) -> list[dict]:
    """Parse markdown into structural blocks that should not be split.

    Returns a list of dicts: {"type": str, "text": str, "level": int|None}
    Types: heading, code_block, table, paragraph, list, blockquote, blank
    """
    blocks = []
    lines = md_text.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # Code block (fenced)
        if line.strip().startswith('```'):
            block_lines = [line]
            i += 1
            while i < len(lines):
                block_lines.append(lines[i])
                if lines[i].strip().startswith('```') and len(block_lines) > 1:
                    i += 1
                    break
                i += 1
            blocks.append({"type": "code_block", "text": '\n'.join(block_lines), "level": None})
            continue

        # Heading
        m = re.match(r'^(#{1,6}) ', line)
        if m:
            blocks.append({"type": "heading", "text": line, "level": len(m.group(1))})
            i += 1
            continue

        # Table (line starts with |)
        if line.strip().startswith('|'):
            block_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                block_lines.append(lines[i])
                i += 1
            blocks.append({"type": "table", "text": '\n'.join(block_lines), "level": None})
            continue

        # Blockquote
        if line.strip().startswith('>'):
            block_lines = []
            while i < len(lines) and (lines[i].strip().startswith('>') or
                                       (lines[i].strip() and block_lines and not lines[i].strip().startswith('#'))):
                block_lines.append(lines[i])
                if not lines[i].strip().startswith('>'):
                    break
                i += 1
            blocks.append({"type": "blockquote", "text": '\n'.join(block_lines), "level": None})
            continue

        # List item (- or * or numbered)
        if re.match(r'^(\s*[-*+]|\s*\d+\.) ', line):
            block_lines = []
            while i < len(lines) and (re.match(r'^(\s*[-*+]|\s*\d+\.) ', lines[i]) or
                                       (lines[i].strip() and lines[i].startswith('  '))):
                block_lines.append(lines[i])
                i += 1
            blocks.append({"type": "list", "text": '\n'.join(block_lines), "level": None})
            continue

        # Blank line
        if not line.strip():
            blocks.append({"type": "blank", "text": "", "level": None})
            i += 1
            continue

        # Paragraph — collect consecutive non-blank, non-special lines
        block_lines = []
        while i < len(lines):
            l = lines[i]
            if (not l.strip() or l.strip().startswith('```') or
                re.match(r'^#{1,6} ', l) or l.strip().startswith('|') or
                l.strip().startswith('>') or re.match(r'^(\s*[-*+]|\s*\d+\.) ', l)):
                break
            block_lines.append(l)
            i += 1
        if block_lines:
            blocks.append({"type": "paragraph", "text": '\n'.join(block_lines), "level": None})

    return blocks


def force_split_block(block_text: str, max_chars: int) -> list[str]:
    """Force-split an oversized block, preserving code fence markers."""
    is_code = block_text.strip().startswith('```')

    if is_code:
        # Extract language tag from opening fence
        first_line = block_text.split('\n')[0]
        lang_tag = first_line.strip()
        inner_lines = block_text.split('\n')[1:]
        # Remove closing fence if present
        if inner_lines and inner_lines[-1].strip().startswith('```'):
            inner_lines = inner_lines[:-1]

        chunks = []
        current = []
        current_len = 0
        for line in inner_lines:
            if current_len + len(line) + 1 > max_chars - 20:  # Reserve space for fences
                chunks.append(f"{lang_tag}\n" + '\n'.join(current) + "\n```")
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1
        if current:
            chunks.append(f"{lang_tag}\n" + '\n'.join(current) + "\n```")
        return chunks

    # Non-code: split on paragraph boundaries or lines
    paragraphs = block_text.split('\n\n')
    if len(paragraphs) > 1:
        chunks = []
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) + 2 <= max_chars:
                buffer = f"{buffer}\n\n{para}" if buffer else para
            else:
                if buffer:
                    chunks.append(buffer)
                buffer = para
        if buffer:
            chunks.append(buffer)
        return chunks

    # Last resort: split by lines
    chunks = []
    buffer = ""
    for line in block_text.split('\n'):
        if len(buffer) + len(line) + 1 <= max_chars:
            buffer = f"{buffer}\n{line}" if buffer else line
        else:
            if buffer:
                chunks.append(buffer)
            buffer = line
    if buffer:
        chunks.append(buffer)
    return chunks


def merge_blocks_to_chunks(blocks: list[dict], max_chars: int = 3000) -> list[str]:
    """Merge structural blocks into translation chunks, preferring heading boundaries."""
    chunks = []
    buffer = ""

    for block in blocks:
        if block["type"] == "blank":
            buffer += "\n\n" if buffer else ""
            continue

        text = block["text"]

        # If this block alone exceeds max, force-split it
        if len(text) > max_chars * 2:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""
            chunks.extend(force_split_block(text, max_chars))
            continue

        # Prefer to split at heading boundaries
        if block["type"] == "heading" and block["level"] and block["level"] <= 2:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""

        if len(buffer) + len(text) + 2 <= max_chars:
            buffer = f"{buffer}\n\n{text}" if buffer.strip() else text
        else:
            if buffer.strip():
                chunks.append(buffer.strip())
            buffer = text

    if buffer.strip():
        chunks.append(buffer.strip())

    return chunks


def split_into_chunks(md_text: str, max_chars: int = 3000) -> list[dict]:
    """Split markdown into translatable chunks using structure-aware parsing.

    Strategy:
    - Parse into structural blocks (headings, code blocks, tables, lists, paragraphs)
    - Never split inside code blocks or tables
    - Prefer splitting at H1/H2 heading boundaries
    - Force-split oversized blocks with fence-marker preservation
    """
    blocks = parse_structural_blocks(md_text)
    chunk_texts = merge_blocks_to_chunks(blocks, max_chars)

    return [{"index": i, "text": c, "hash": hashlib.sha256(c.encode()).hexdigest()[:12]}
            for i, c in enumerate(chunk_texts)]


# ---------------------------------------------------------------------------
# Manifest-based integrity verification
# ---------------------------------------------------------------------------

def create_manifest(chunks: list[dict], source_path: str) -> dict:
    """Create a manifest for chunk verification."""
    with open(source_path, "rb") as f:
        source_hash = hashlib.sha256(f.read()).hexdigest()[:16]

    return {
        "source_file": source_path,
        "source_hash": source_hash,
        "chunk_count": len(chunks),
        "chunks": {
            c["hash"]: {
                "index": c["index"],
                "source_hash": c["hash"],
                "char_count": len(c["text"]),
            }
            for c in chunks
        }
    }


def validate_results(chunks: list[dict], results: list[dict], manifest: dict) -> list[str]:
    """Validate translation results against manifest. Returns list of warnings."""
    warnings = []

    for i, (chunk, result) in enumerate(zip(chunks, results)):
        if result is None:
            warnings.append(f"Chunk {i}: missing result")
            continue

        if "error" in result:
            warnings.append(f"Chunk {i}: translation error — {result['error']}")
            continue

        translated = result.get("translated", "")
        source_len = len(chunk["text"])
        trans_len = len(translated)

        # Flag suspiciously small translations (<10% of source)
        if source_len > 100 and trans_len < source_len * 0.1:
            warnings.append(f"Chunk {i}: output suspiciously small ({trans_len} chars vs {source_len} source)")

        # Flag empty translations
        if not translated.strip():
            warnings.append(f"Chunk {i}: empty translation output")

    return warnings


# ---------------------------------------------------------------------------
# Translation execution
# ---------------------------------------------------------------------------

def load_progress(progress_file: str) -> dict:
    """Load translation progress from file."""
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress_file: str, progress: dict):
    """Save translation progress to file."""
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def translate_chunk(engine, chunk: dict, target_lang: str, progress: dict, progress_file: str) -> dict:
    """Translate a single chunk, skipping if already done."""
    chunk_key = chunk["hash"]

    # Skip if already translated with same hash
    if chunk_key in progress and progress[chunk_key].get("done"):
        chunk["translated"] = progress[chunk_key]["text"]
        return chunk

    try:
        translated = engine.translate(chunk["text"], target_lang)
        chunk["translated"] = translated
        progress[chunk_key] = {"done": True, "text": translated}
        save_progress(progress_file, progress)
        return chunk
    except Exception as e:
        print(f"  [!] Chunk {chunk['index']} failed: {e}", file=sys.stderr)
        chunk["translated"] = chunk["text"]  # fallback to original
        chunk["error"] = str(e)
        return chunk


def translate_markdown(input_path: str, output_path: str, engine_name: str,
                       target_lang: str, source_lang: str = "auto",
                       workers: int = 4, max_chars: int = 3000, **engine_kwargs):
    """Main translation function."""
    # Read input
    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    print(f"Input: {input_path} ({len(md_text)} chars)", file=sys.stderr)

    # Initialize engine
    engine = get_engine(engine_name, **engine_kwargs)
    print(f"Engine: {engine.name}", file=sys.stderr)
    print(f"Target language: {get_lang_name(target_lang)}", file=sys.stderr)

    # Split into chunks (structure-aware)
    chunks = split_into_chunks(md_text, max_chars=max_chars)
    print(f"Chunks: {len(chunks)}", file=sys.stderr)

    # Create manifest for verification
    manifest = create_manifest(chunks, input_path)

    # Progress file for resume support
    base = os.path.splitext(output_path)[0]
    progress_file = f"{base}.progress.json"
    progress = load_progress(progress_file)

    already_done = sum(1 for c in chunks if c["hash"] in progress and progress[c["hash"]].get("done"))
    if already_done > 0:
        print(f"Resuming: {already_done}/{len(chunks)} chunks already translated", file=sys.stderr)

    # Translate chunks
    if engine_name == "deepl":
        # DeepL has rate limits, use sequential for free tier
        effective_workers = min(workers, 2)
    else:
        effective_workers = workers

    results = [None] * len(chunks)
    errors = 0

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {}
        for chunk in chunks:
            future = executor.submit(translate_chunk, engine, chunk, target_lang, progress, progress_file)
            futures[future] = chunk["index"]

        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
                results[idx] = result
                status = "cached" if result["hash"] in progress and "error" not in result else "done"
                if "error" in result:
                    status = "error"
                    errors += 1
                print(f"  [{idx + 1}/{len(chunks)}] {status}", file=sys.stderr)
            except Exception as e:
                print(f"  [{idx + 1}/{len(chunks)}] fatal error: {e}", file=sys.stderr)
                results[idx] = chunks[idx]
                results[idx]["translated"] = chunks[idx]["text"]
                errors += 1

    # Validate results
    warnings = validate_results(chunks, results, manifest)
    if warnings:
        print(f"\nValidation warnings:", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)

    # Merge translated chunks
    translated_parts = []
    for r in results:
        if r and "translated" in r:
            translated_parts.append(r["translated"])
        elif r:
            translated_parts.append(r["text"])

    translated_text = "\n\n".join(translated_parts)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(translated_text)

    # Save manifest alongside output
    manifest_path = f"{base}.manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Clean up progress file on success
    if errors == 0 and os.path.exists(progress_file):
        os.remove(progress_file)

    print(f"\nOutput: {output_path} ({len(translated_text)} chars)", file=sys.stderr)
    print(f"Manifest: {manifest_path}", file=sys.stderr)
    if errors > 0:
        print(f"Warnings: {errors} chunks had errors (original text used as fallback)", file=sys.stderr)
        print(f"Progress saved to {progress_file} — re-run to retry failed chunks", file=sys.stderr)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Translate Markdown files")
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("output", nargs="?", help="Output markdown file")
    parser.add_argument("--engine", "-e", default="deepl", choices=list(ENGINES.keys()),
                        help="Translation engine (default: deepl)")
    parser.add_argument("--target", "-t", default="zh", help="Target language code (default: zh)")
    parser.add_argument("--source", "-s", default="auto", help="Source language code (default: auto)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers (default: 4)")
    parser.add_argument("--max-chars", type=int, default=3000, help="Max chars per chunk (default: 3000)")
    parser.add_argument("--model", "-m", help="Override model for OpenAI/Gemini/Claude engines")

    args = parser.parse_args()

    if not args.output:
        base = os.path.splitext(args.input)[0]
        args.output = f"{base}_{args.target}.md"

    engine_kwargs = {}
    if args.model:
        engine_kwargs["model"] = args.model

    translate_markdown(
        args.input, args.output,
        engine_name=args.engine,
        target_lang=args.target,
        source_lang=args.source,
        workers=args.workers,
        max_chars=args.max_chars,
        **engine_kwargs,
    )


if __name__ == "__main__":
    main()
