<h1><img src="https://raw.githubusercontent.com/JeffSteinbok/reMarkableSync/main/docs/logo.png" height="32" style="vertical-align: middle;"> reMarkableSync</h1>

![reMarkableSync](https://raw.githubusercontent.com/JeffSteinbok/reMarkableSync/main/githubSocial.png)

[![GitHub](https://img.shields.io/badge/GitHub-reMarkableSync-blue?logo=github)](https://github.com/JeffSteinbok/reMarkableSync)
[![GitHub release](https://img.shields.io/github/v/release/JeffSteinbok/reMarkableSync)](https://github.com/JeffSteinbok/reMarkableSync/releases)
[![CI](https://github.com/JeffSteinbok/reMarkableSync/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffSteinbok/reMarkableSync/actions/workflows/ci.yml)
[![Build Executables](https://github.com/JeffSteinbok/reMarkableSync/actions/workflows/build-executables.yml/badge.svg)](https://github.com/JeffSteinbok/reMarkableSync/actions/workflows/build-executables.yml)
[![PyPI version](https://img.shields.io/pypi/v/remarkablesync.svg)](https://pypi.org/project/remarkablesync/)
[![Homebrew](https://img.shields.io/badge/Homebrew-remarkablesync-FBB040?logo=homebrew)](https://github.com/JeffSteinbok/homebrew-remarkablesync)
[![Website](https://img.shields.io/badge/Website-jeffsteinbok.github.io-blue?logo=github-pages)](https://jeffsteinbok.github.io/reMarkableSync/)

A comprehensive Python toolkit for backing up reMarkable tablet notebooks, converting them to PDF, and transcribing handwriting to Markdown with AI — over USB or Wi-Fi.

> [!IMPORTANT]
> Known device support:
> - **reMarkable 2** — confirmed working and the primary device tested
> - **reMarkable Paper Pro** — expected to work, but SSH must be enabled through developer mode, which currently requires a factory reset
> - **reMarkable 1** — not currently verified; compatibility is not guaranteed
>
> AI handwriting-to-text features work with **GitHub Copilot**, **Claude** (Anthropic), or **Google Gemini** (free tier available).

## Device Compatibility

| Device | Status | Caveats |
|--------|--------|---------|
| **reMarkable 2** | Known to work | This is the primary device used for testing. |
| **reMarkable Paper Pro** | Known to work with setup caveat | SSH access must be enabled through developer mode, and enabling developer mode currently requires a factory reset. |
| **reMarkable 1** | Not currently verified | Compatibility is not guaranteed until it has been tested directly. |

## Features

- **USB & Wi-Fi sync** — connect via cable or wirelessly over your local network
- **Incremental backup** — only downloads files that have changed (tracked by size, mtime, and MD5)
- **PDF conversion** — v5 and v6 .rm formats with template backgrounds, folder hierarchy preserved
- **AI handwriting recognition** — send page images to GitHub Models (GPT-4o), Claude, or Google Gemini
- **Markdown export** — each notebook becomes a `.md` file with YAML frontmatter and embedded page images
- **Watch mode** — automatic periodic sync with system-tray status icon and run-at-startup option
- **Secure credential storage** — SSH password and AI tokens stored in your system keyring

## Supported AI Providers

| Provider | Description | API Key |
|----------|-------------|---------|
| **GitHub Copilot** | Uses GPT-4o via GitHub Models. Free for Copilot subscribers. | Automatic via GitHub login |
| **Google Gemini** | Gemini 2.5 Flash/Pro models. Free tier available. | [Get API key](https://aistudio.google.com/apikey) |
| **Claude** | Anthropic's Claude models. Requires paid API access. | [Get API key](https://console.anthropic.com/) |

## Quick Start

### 1. Install

```bash
# macOS (Homebrew)
brew tap jeffsteinbok/remarkablesync && brew install remarkablesync

# All platforms (pip)
pip install remarkablesync

# Or download a pre-built executable from the Releases page
```

### 2. Run the configuration wizard

```bash
reMarkableSync config
```

The wizard walks you through:

| Setting | Default |
|---------|---------|
| **Connection mode** | USB or Wi-Fi (wizard can enable Wi-Fi SSH for you) |
| **SSH password** | Saved to system keyring |
| **Backup directory** | `<AppData>/remarkablesync/backup` (internal sync data) |
| **PDF output** | `~/Documents/reMarkableSync/PDF` |
| **Markdown output** | `~/Documents/reMarkableSync/Markdown` |
| **AI provider** | GitHub Models (free with Copilot), Claude, or Google Gemini (free tier available) |
| **AI token** | Stored securely in system keyring |
| **Folders** | Choose which tablet folders to sync (or all) |

> [!TIP]
> **Multi-device setup:** Use the folder filter to sync different tablet folders to different computers — e.g., sync your "Work" folder to your work PC and "Home" to your personal machine. Each machine gets its own config.

### 3. Run it

```bash
reMarkableSync watch
```

This will use your configured defaults and launch a sync cycle (backup → PDF → Markdown), then keep running and re-sync every 30 minutes. Check your output directories to verify everything looks right.

### 4. Set it to run at startup

Once you're happy with the output, enable run-at-startup from the system tray icon menu (or via the watch command). reMarkableSync will sync your tablet automatically in the background whenever your computer is on.

> [!TIP]
> **Obsidian users:** Point the Markdown output directory at a folder inside your Obsidian vault. Your handwritten notes appear as searchable Markdown with embedded page images. Pair with [Obsidian OneDrive Sync](https://github.com/JeffSteinbok/obsidian-onedrive) to sync your vault across devices.

## AI Provider Setup

The AI handwriting-to-text features require either a **GitHub Copilot** account (for GitHub Models) or a **Claude** (Anthropic) API key. Support for additional providers can be added as needed.

Both AI provider SDKs are installed with `pip install -r requirements.txt`. The config wizard handles authentication interactively.

### GitHub Models

The wizard runs a GitHub device-code flow to authenticate. No manual token setup needed.

Alternatively, set a `GITHUB_TOKEN` environment variable with a PAT that has `models:read` scope.

### Claude (Anthropic)

1. Go to https://console.anthropic.com/settings/keys
2. Click **Create Key** and copy it (starts with `sk-ant-api03-...`)
3. Paste it into the config wizard — it's saved in your system keyring

Default model: `claude-sonnet-4-6`.

## Usage

After running `config`, most users only need `watch`. For one-off or scripted use:

```bash
# Default: backup + PDF conversion (uses saved config)
reMarkableSync

# Full pipeline: backup + PDF + AI OCR + Markdown
reMarkableSync md --with-backup --with-pdf

# Individual steps
reMarkableSync backup          # backup only
reMarkableSync convert         # PDF conversion only (from existing backup)
reMarkableSync md              # Markdown export only (from existing PDFs)

# Watch mode (periodic sync)
reMarkableSync watch           # uses saved config for interval, dirs, AI

# Check for updates
reMarkableSync check-update
```

### Command Line Options

All commands read defaults from the saved config. CLI flags override config values.

**Common:**
- `-d, --backup-dir PATH` — backup directory
- `-v, --verbose` — debug logging
- `--version` — version info

**Connection:**
- `--host HOST` — tablet IP (default: `10.11.99.1`)
- `--wifi` — connect over Wi-Fi
- `--wifi-host HOST` — tablet Wi-Fi IP (auto-discovered if omitted)

**Backup:**
- `-p, --password` — SSH password (prompted if not saved)
- `--skip-templates` — don't backup templates
- `--force-backup` — re-download everything

**Convert:**
- `-o, --output-dir PATH` — PDF output directory
- `--force-all` — reconvert all notebooks
- `--sample N` — convert first N notebooks only
- `--notebook NAME` — convert a single notebook

**Markdown (md):**
- `-V, --vault-dir PATH` — Markdown output directory
- `--ai-provider` — `github` or `claude`
- `--ai-model` — override default model
- `--ai-api-key` — API key (prefer keyring or env vars)
- `--tags` — comma-separated frontmatter tags (default: `remarkable`)
- `--no-images` — skip embedding page images
- `--with-backup` / `--with-pdf` — include earlier pipeline stages
- `--force-export` — re-export all notes

**Watch:**
- `-i, --interval N` — minutes between syncs (default: 30)
- `--systray / --no-systray` — system tray icon (default: enabled)

**Updates:**
- `reMarkableSync check-update` — check for newer versions
- Update notifications appear automatically (checked once per day)

## Wi-Fi Connection

The config wizard can enable Wi-Fi SSH on your tablet automatically via USB. If you prefer to do it manually:

1. Connect tablet via USB and SSH into `10.11.99.1`
2. Run `rm-ssh-over-wlan on`
3. Find the IP: `ip addr show wlan0`
4. Use that IP in the config wizard or `--wifi-host`

> [!TIP]
> Assign a static DHCP lease to your tablet in your router so the IP doesn't change.

## Generated Markdown Format

Each notebook becomes a folder with one Markdown file per page:

```markdown
---
title: "My Meeting Notes"
source: reMarkable
remarkable_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
notebook: Work
folder: Work/Meetings
page: 1
created: 2025-01-15
ai_provider: GitHubModelsProvider
ai_model: gpt-4o-mini
tags:
  - remarkable
---

## Action Items

- **Follow up** with Alice on the Q1 plan
- Schedule review for next Friday

![page 1](_images/page_001.png)
```

Page images are stored in a `_images/` subfolder next to the Markdown files.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't connect via USB | Verify cable, ping `10.11.99.1`, check SSH password |
| Can't connect via Wi-Fi | Same network? Try `ping remarkable.local` or use `--wifi-host <ip>` |
| AI OCR returns errors | Check API key/token, verify package installed (`anthropic` or `openai`), check rate limits |
| Empty Markdown files | AI provider may have failed — check log file for details |
| v6 notebooks not converting | Ensure `rmc` is installed (`pip install rmc`) — required for v6 .rm format |
| Watch lock error | Delete `<backup-dir>/.remarkable_watch.lock` |
| Permission errors | Ensure output directories are writable; run as admin on Windows if needed |

For any issue, re-run your command with `--log-level DBG` to get detailed output. See [How to get DEBUG logs](docs/debug-logs.md) for details.

## Acknowledgements

reMarkableSync is built on top of these excellent open-source projects:

| Library | Role |
|---------|------|
| [rmc](https://github.com/ricklupton/rmc) | Converts reMarkable v6 `.rm` files to SVG |
| [svglib](https://github.com/deeplook/svglib) | Converts SVG to ReportLab drawings |
| [ReportLab](https://github.com/MrBitBucket/reportlab-mirror) | Renders drawings and templates to PDF |
| [PyPDF2](https://github.com/py-pdf/pypdf) | Merges and overlays PDF pages |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | Rasterises PDF pages to images for AI OCR |
| [Pillow](https://github.com/python-pillow/Pillow) | Image processing and manipulation |

## Security

- SSH password and AI tokens are stored in your **system keyring** (never in plain-text config files)
- All communication is over your local network (USB or LAN) — nothing goes to the internet except AI API calls
- Config file at `<AppData>/remarkablesync/config.json` contains only non-secret settings
