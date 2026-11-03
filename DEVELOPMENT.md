# Development Guide

## How It Works

1. **Connect** to tablet via SSH (USB or Wi-Fi)
2. **Discover** notebooks in `/home/root/.local/share/remarkable/xochitl/`
3. **Backup** changed files incrementally via SCP
4. **Convert** .rm files → SVG (via rmc) → PDF with template backgrounds
5. **Rasterise** PDF pages to PNG images
6. **Transcribe** handwriting via AI vision model
7. **Clean up** raw text into structured Markdown via LLM
8. **Export** Markdown files with frontmatter + embedded images

Only changed notebooks are processed on each run.

## Source Directory Structure

```
RemarkableSync/
├── RemarkableSync.py           # CLI entry point (click commands)
├── src/
│   ├── ai/                     # AI provider abstraction
│   │   ├── base_provider.py    # BaseAIProvider ABC, error classes, prompt templates
│   │   ├── github_models_provider.py  # GitHub Models (OpenAI-compatible)
│   │   └── claude_provider.py  # Anthropic Claude
│   ├── commands/               # CLI command implementations
│   │   ├── config_command.py   # Interactive setup wizard
│   │   ├── pipeline.py         # Full sync pipeline (backup → PDF → MD)
│   │   ├── watch_command.py    # Watch mode (periodic re-sync)
│   │   ├── backup_command.py   # Backup-only command
│   │   ├── convert_command.py  # PDF conversion command
│   │   └── sync_command.py     # Legacy sync command
│   ├── ocr/
│   │   └── ocr_engine.py      # PDF → images → AI transcription
│   ├── utils/
│   │   ├── console.py         # Rich console output helpers
│   │   └── logging.py         # Logging configuration
│   ├── auth/                   # SSH/device authentication
│   ├── backup/                 # Tablet file discovery and SCP
│   ├── converters/             # .rm → SVG → PDF conversion
│   ├── config.py              # Config load/save, defaults
│   ├── keyring_store.py       # System keyring wrapper for secrets
│   ├── hybrid_converter.py    # Notebook structure organiser
│   ├── pdf_md_converter.py    # MarkdownExporter (PDF → per-page MD)
│   ├── rm_pdf_converter.py    # .rm file → PDF converter
│   └── template_renderer.py   # reMarkable template backgrounds
├── tests/                      # pytest test suite
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Dev/test dependencies
└── pyproject.toml              # Project metadata and tool config
```

## Output Directory Structure

```
# Internal backup data (AppData by default)
<backup_dir>/
├── Notebooks/              # Raw notebook files and metadata
├── Templates/              # Template files from device
├── PagePDFs/               # Cached per-page PDFs
└── sync_metadata.json      # Sync state

# Machine-local runtime (%LOCALAPPDATA%\remarkablesync on Windows)
<runtime_dir>/
├── locks/
│   └── [backup path hash]/ # Process and sync locks, never cloud-synced
└── logs/
    └── remarkablesync.log  # Current log and rotated backups

# PDF output (Documents by default)
<pdf_dir>/
└── [folder hierarchy]/
    └── Notebook Name.pdf

# Markdown output (Documents by default)
<output_dir>/
└── [folder hierarchy]/
    └── Notebook Name/
        ├── 001 - Title.md
        ├── 002 - 2024-08-27 - Meeting Notes.md
        ├── 003.md
        └── _images/
            ├── page_001.png
            ├── page_002.png
            └── page_003.png
```

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q --ignore=tests/test_wifi_connection.py
```

## Linting

```bash
ruff check .
ruff check --fix .   # auto-fix
```
