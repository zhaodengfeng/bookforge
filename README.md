# BookForge

PDF → Markdown → Translate → EPUB/PDF toolkit with multi-engine translation support.

BookForge is a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that converts PDF books into clean Markdown, optionally translates them using your choice of AI translation engine, and outputs EPUB or other formats.

## Features

- **PDF Extraction** — Text extraction with heading detection, table support, list detection, and OCR fallback for scanned documents
- **Multi-Engine Translation** — 5 translation engines with a unified interface:
  - **DeepL** — High quality, free tier (500k chars/month)
  - **OpenAI** — GPT-4o-mini (cheap) or GPT-4o (quality)
  - **Google Gemini** — Flash (fast & affordable) or Pro
  - **Anthropic Claude** — Highest translation quality
  - **OpenRouter** — Access 200+ models through one API
- **Chunked Parallel Translation** — Automatic chapter/section splitting with configurable parallel workers
- **Resume Support** — Interrupted translations can be continued from where they left off
- **EPUB Output** — CJK-optimized styling, auto-generated TOC, chapter navigation

## Installation

### As a Claude Code Skill

```bash
# Clone to your Claude Code skills directory
git clone https://github.com/zhaodengfeng/bookforge.git ~/.claude/skills/bookforge
```

### Dependencies

```bash
# Required
brew install pandoc
pip3 install pdfplumber

# Optional fallbacks
pip3 install pypdf                    # PDF text extraction fallback
pip3 install pytesseract pdf2image    # OCR for scanned PDFs
```

### API Keys

Set the environment variable for your chosen translation engine (you only need one):

```bash
export DEEPL_API_KEY=your_key         # DeepL
export OPENAI_API_KEY=your_key        # OpenAI
export GEMINI_API_KEY=your_key        # Google Gemini
export ANTHROPIC_API_KEY=your_key     # Claude
export OPENROUTER_API_KEY=your_key    # OpenRouter
```

## Usage

### Quick Start — Full Pipeline

```bash
# Step 1: Extract PDF to Markdown
python3 scripts/pdf_to_md.py book.pdf /tmp/raw.md

# Step 2: (Optional) Review and clean up the Markdown with Claude

# Step 3: Translate to Chinese using DeepL
python3 scripts/translate_md.py /tmp/raw.md /tmp/translated.md -e deepl -t zh

# Step 4: Convert to EPUB
python3 scripts/md_to_epub.py /tmp/translated.md /tmp/book.epub --title "Book Title" --author "Author"
```

### PDF to Markdown

```bash
python3 scripts/pdf_to_md.py <input.pdf> [output.md]
```

Extraction strategies (auto-selected with fallback):
1. **pdfplumber** — Best for structured PDFs with headings, tables, lists
2. **pypdf** — Fallback for simpler text extraction
3. **OCR** — For scanned PDFs (supports Chinese + English)

### Translation

```bash
python3 scripts/translate_md.py <input.md> <output.md> [options]
```

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `-e, --engine` | Translation engine | `deepl` |
| `-t, --target` | Target language code | `zh` |
| `-s, --source` | Source language code | `auto` |
| `-w, --workers` | Parallel workers | `4` |
| `-m, --model` | Override model | engine default |
| `--max-chars` | Max chars per chunk | `3000` |

**Supported languages:** zh, en, ja, ko, fr, de, es, pt, ru, it, ar

**Engine examples:**

```bash
# DeepL (default, recommended for cost/quality balance)
python3 scripts/translate_md.py input.md output.md -t zh

# OpenAI GPT-4o-mini
python3 scripts/translate_md.py input.md output.md -e openai -t zh

# OpenAI with a different model
python3 scripts/translate_md.py input.md output.md -e openai -t zh -m gpt-4o

# Google Gemini Flash
python3 scripts/translate_md.py input.md output.md -e gemini -t zh

# Claude (highest quality)
python3 scripts/translate_md.py input.md output.md -e claude -t zh

# OpenRouter with any model
python3 scripts/translate_md.py input.md output.md -e openrouter -t zh -m deepseek/deepseek-chat-v3-0324
python3 scripts/translate_md.py input.md output.md -e openrouter -t zh -m qwen/qwen-2.5-72b-instruct
```

### Markdown to EPUB

```bash
python3 scripts/md_to_epub.py <input.md> [output.epub] [--title "Title"] [--author "Author"] [--lang zh-CN]
```

Features:
- Auto-extracts title from first H1 heading
- CJK-optimized CSS (PingFang SC, line-height 1.8, 2em text-indent)
- Auto-generated table of contents (up to 3 levels)
- Chapters split at H2 level

## How It Works

```
┌──────────┐    ┌──────────┐    ┌───────────┐    ┌──────────┐
│   PDF    │───▶│ Markdown │───▶│ Translate │───▶│  EPUB    │
│          │    │          │    │ (optional)│    │          │
└──────────┘    └──────────┘    └───────────┘    └──────────┘
 pdf_to_md.py    Review &       translate_md.py   md_to_epub.py
                 Reformat
```

### Translation Architecture

- Markdown is split into chunks at chapter/section boundaries
- Chunks are translated in parallel using configurable workers
- Progress is saved after each chunk (SHA-256 hash tracking)
- If interrupted, re-run the same command to resume from where it stopped
- DeepL automatically uses reduced parallelism to respect rate limits

## Project Structure

```
bookforge/
├── scripts/
│   ├── pdf_to_md.py       # PDF → Markdown extraction
│   ├── translator.py      # Unified translation engine interface
│   ├── translate_md.py    # Chunked parallel translation
│   └── md_to_epub.py      # Markdown → EPUB conversion
├── SKILL.md               # Claude Code skill definition
├── LICENSE                 # GPL-3.0
└── README.md
```

## License

[GPL-3.0](LICENSE)
