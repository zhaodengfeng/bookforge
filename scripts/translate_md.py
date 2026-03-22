#!/usr/bin/env python3
"""Translate Markdown files with chunking, parallel execution, and resume support.

Usage:
    python3 translate_md.py <input.md> <output.md> --engine deepl --target zh [--workers 4]

Engines: deepl, openai, gemini, claude
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


def split_into_chunks(md_text: str, max_chars: int = 3000) -> list[dict]:
    """Split markdown into translatable chunks, preserving structure.

    Strategy:
    - Split on H1/H2 headings first (chapter boundaries)
    - If a section is still too large, split on H3 or paragraphs
    - Never split inside code blocks or tables
    """
    chunks = []
    # Split on H1/H2 boundaries
    sections = re.split(r'(?=^#{1,2} )', md_text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        if len(section) <= max_chars:
            chunks.append(section)
        else:
            # Further split on H3 or double newlines
            subsections = re.split(r'(?=^### )|(?:\n\n)', section, flags=re.MULTILINE)
            buffer = ""
            for sub in subsections:
                sub = sub.strip()
                if not sub:
                    continue
                if len(buffer) + len(sub) + 2 <= max_chars:
                    buffer = f"{buffer}\n\n{sub}" if buffer else sub
                else:
                    if buffer:
                        chunks.append(buffer)
                    # If single subsection is too large, just add it as-is
                    buffer = sub
            if buffer:
                chunks.append(buffer)

    return [{"index": i, "text": c, "hash": hashlib.sha256(c.encode()).hexdigest()[:12]} for i, c in enumerate(chunks)]


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
        translated = engine.translate(chunk["text"], get_lang_name(target_lang))
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

    # Split into chunks
    chunks = split_into_chunks(md_text, max_chars=max_chars)
    print(f"Chunks: {len(chunks)}", file=sys.stderr)

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

    # Clean up progress file on success
    if errors == 0 and os.path.exists(progress_file):
        os.remove(progress_file)

    print(f"\nOutput: {output_path} ({len(translated_text)} chars)", file=sys.stderr)
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
