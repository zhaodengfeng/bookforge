---
name: pdf-to-markdown
description: "Converts PDF files to Markdown and/or EPUB format. Full pipeline: PDF → MD → review/reformat → EPUB. Triggers: 'pdf to markdown', 'pdf to epub', 'pdf转md', 'pdf转epub', 'PDF转Markdown', 'convert pdf', user sends a PDF requesting conversion."
---

# PDF to Markdown / EPUB Conversion

## Full Pipeline: PDF → MD → (Translate) → EPUB

### Step 1: PDF to Markdown
```bash
python3 ~/.claude/skills/pdf-to-markdown/scripts/pdf_to_md.py <input.pdf> <output.md>
```

The script handles:
- Text extraction with layout preservation
- Heading detection (large/bold fonts → `#`, `##`, `###`)
- Table extraction → Markdown tables
- List detection → Markdown lists
- OCR fallback for scanned PDFs (pytesseract, chi_sim+eng)
- Page breaks as horizontal rules (`---`)

### Step 2: Review & Reformat Markdown
After initial conversion, review and clean up the markdown:
- Fix heading hierarchy (ensure logical H1 > H2 > H3 structure)
- Merge lines that were incorrectly split by PDF line breaks
- Clean up artifacts from PDF extraction (stray characters, broken paragraphs)
- Ensure proper paragraph spacing
- Fix list formatting
- Remove page headers/footers that got mixed into body text
- Send the cleaned MD file to user for review if requested

### Step 3 (Optional): Translate Markdown
If the user needs translation, use the translation script:
```bash
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py <input.md> <output.md> --engine <engine> --target <lang>
```

**Available engines:**
- `deepl` — DeepL API (default, high quality, free tier: 500k chars/month). Requires `DEEPL_API_KEY`
- `openai` — OpenAI GPT-4o-mini (cheap, good quality). Requires `OPENAI_API_KEY`
- `gemini` — Google Gemini Flash (fast, affordable). Requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `claude` — Anthropic Claude (highest quality, most expensive). Requires `ANTHROPIC_API_KEY`
- `openrouter` — OpenRouter (access hundreds of models via one API). Requires `OPENROUTER_API_KEY`. Use `--model` to pick model, e.g. `deepseek/deepseek-chat-v3-0324`, `qwen/qwen-2.5-72b-instruct`

**Translation options:**
- `--engine` / `-e`: Translation engine (default: deepl)
- `--target` / `-t`: Target language code (default: zh). Codes: zh, en, ja, ko, fr, de, es, pt, ru, it
- `--workers` / `-w`: Parallel workers (default: 4)
- `--model` / `-m`: Override model for OpenAI/Gemini/Claude (e.g., `gpt-4o`, `gemini-2.0-pro`, `claude-sonnet-4-20250514`)
- `--max-chars`: Max characters per chunk (default: 3000)

**Features:**
- Automatic chunking by chapter/section boundaries
- Parallel translation with configurable workers
- Resume support — interrupted translations can be continued
- SHA-256 hash tracking to skip already-translated chunks

### Step 4: Markdown to EPUB
```bash
python3 ~/.claude/skills/pdf-to-markdown/scripts/md_to_epub.py <input.md> <output.epub> [--title "Book Title"] [--author "Author Name"] [--lang zh-CN]
```

Features:
- Auto-extracts title from first H1 heading
- CJK-optimized CSS (PingFang SC, line-height 1.8, 2em text-indent)
- Auto-generates table of contents (TOC) up to 3 levels
- Chapters split at H2 level for proper navigation
- Clean typography with responsive layout

## Quick Commands

**PDF → MD only:**
```bash
python3 ~/.claude/skills/pdf-to-markdown/scripts/pdf_to_md.py input.pdf /tmp/output.md
```

**MD → Translated MD:**
```bash
# Using DeepL (default, recommended for cost)
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py input.md /tmp/translated.md -e deepl -t zh

# Using OpenAI
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py input.md /tmp/translated.md -e openai -t zh

# Using Gemini
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py input.md /tmp/translated.md -e gemini -t zh

# Using Claude (highest quality)
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py input.md /tmp/translated.md -e claude -t zh

# Using OpenRouter (pick any model)
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py input.md /tmp/translated.md -e openrouter -t zh -m deepseek/deepseek-chat-v3-0324
```

**MD → EPUB only:**
```bash
python3 ~/.claude/skills/pdf-to-markdown/scripts/md_to_epub.py input.md /tmp/output.epub --title "书名" --author "作者"
```

**Full pipeline (PDF → MD → Translate → EPUB):**
```bash
# Step 1: Extract
python3 ~/.claude/skills/pdf-to-markdown/scripts/pdf_to_md.py input.pdf /tmp/raw.md
# Step 2: Review raw.md, reformat with Claude
# Step 3: Translate (optional)
python3 ~/.claude/skills/pdf-to-markdown/scripts/translate_md.py /tmp/formatted.md /tmp/translated.md -e deepl -t zh
# Step 4: Convert to EPUB
python3 ~/.claude/skills/pdf-to-markdown/scripts/md_to_epub.py /tmp/translated.md /tmp/output.epub
```

## Dependencies
- **pandoc**: `brew install pandoc`
- **pdfplumber**: `pip3 install pdfplumber`
- **pypdf**: `pip3 install pypdf` (fallback)
- **pytesseract + pdf2image**: `pip3 install pytesseract pdf2image` (OCR fallback)

## API Keys (for translation)
Set the relevant environment variable for your chosen engine:
- DeepL: `export DEEPL_API_KEY=your_key`
- OpenAI: `export OPENAI_API_KEY=your_key`
- Gemini: `export GEMINI_API_KEY=your_key` (or `GOOGLE_API_KEY`)
- Claude: `export ANTHROPIC_API_KEY=your_key`
- OpenRouter: `export OPENROUTER_API_KEY=your_key`

## Known Pitfalls (Post-extraction Cleanup)

PDF extraction + translation introduces many subtle formatting bugs. When writing cleanup scripts, watch for these:

### 1. Markdown Setext Headings (CRITICAL)
`---` separators in the body text cause Setext heading bugs: any text line immediately before `---` becomes an H2 heading (wrong font/size). **Fix:** Remove ALL `---` from body content with `re.sub(r'\n---\n', '\n\n', content)`. Do this early in the pipeline.

### 2. Split Headings from PDF Extraction
PDF line breaks often split one heading into two `# ` lines (e.g., `# 唯有一人疯狂到足以` / `# 太空` should be one heading). **Fix:** Compare with table of contents entries to get correct full titles, then `content.replace()` to merge them.

### 3. Markdown Newline = Space in HTML
A single newline between text lines becomes a visible space in rendered HTML/PDF. For Chinese text, this creates unwanted gaps. **Fix:** Join consecutive body text lines into single lines. For CJK text, join without space; for English, join with space. Must detect block-level elements (headings, lists, bold markers, blank lines) to avoid joining those.

### 4. Unicode Superscript Rendering
Unicode superscript digits (⁰¹²³⁴⁵⁶⁷⁸⁹) render as □ boxes in many Chinese fonts (e.g., FZFangSong-Z02). **Fix:** In the HTML/PDF generation step, convert Unicode superscripts to `<sup>regular digits</sup>` with a fallback font (e.g., PingFang SC) in CSS.

### 5. Footnote Numbers Mixed with Content
PDF extraction often merges footnote reference numbers with body text (e.g., `9831971年` where `983` is a footnote and `1971年` is content). **Fix:** Clean with `re.sub(r'(\d{3})(\d{4}年)', r'\2', content)` before any line-joining step.

### 6. False Headings from `###` Prefix
PDF extraction may incorrectly mark body text lines with `### ` prefix. **Fix:** After the TOC section, strip `### ` from lines that look like body text (contain sentence punctuation, length > 30 chars).

### 7. Regex `[^X]` Matches Newlines
In Python regex, character class negation `[^*]` matches `\n` (unlike `.` which doesn't by default). This causes patterns like `\*\*[^*]+\*\*` to match across multiple lines, mangling content. **Fix:** Always use `[^*\n]+` when you intend single-line matching in character classes.

### 8. `re.DOTALL` Leaks into Heading Patterns
When using `re.DOTALL` for a multi-line search, `.*` in heading patterns like `## .*keyword.*\n\n` will match across lines, capturing wrong sections. **Fix:** Use `[^\n]*` instead of `.*` for heading-line patterns within DOTALL regexes.

### 9. Line-Joining Destroys Numbered Lists and Timelines
The continuation-line joiner merges numbered items (`1. text`, `2. text`) and year entries (`1971年...`) into one giant line. **Fix:** Detect these patterns as block-level elements in the joiner: `re.match(r'^\d{1,2}\. ', line)` for numbered lists, `re.match(r'^\d{4}年', line)` for timelines. Add blank lines between items before joining.

### 10. Processing Order Matters
Cleanup steps interact with each other. Recommended order:
1. Fix split headings and heading structure
2. Remove `---` separators (prevent Setext headings)
3. Strip false `###` headings
4. Extract/convert footnote numbers
5. Clean footnote digits mixed with content (e.g., before year entries)
6. **Add blank lines between list items / year entries** (before joining!)
7. Remove extra spaces (with URL protection)
8. Merge split paragraphs
9. Join continuation lines (the key rendering fix)
10. Section-specific formatting (books, names, etc.) — use `[^*\n]` in regexes

## Notes
- Default language is `zh-CN` for Chinese content; use `--lang en` for English
- Output files default to `/tmp/` for easy sending via Telegram
- The review step (Step 2) is critical — raw PDF extraction rarely produces perfect markdown
- For best EPUB quality, always do the review/reformat step rather than direct conversion
- Translation progress is auto-saved; if interrupted, re-run the same command to resume
- DeepL free tier has rate limits; the script automatically reduces parallelism for DeepL
