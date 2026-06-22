#!/usr/bin/env python3
"""
RemarkableSync - Unified command-line interface

Single entry point for backing up and converting reMarkable tablet files.
"""

import os
import sys
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Check Python version before importing anything else
if sys.version_info < (3, 11):
    print("Error: RemarkableSync requires Python 3.11 or higher.")
    print(
        f"You are using Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    print("\nPlease upgrade your Python installation:")
    print("  - Download from: https://www.python.org/downloads/")
    print("  - Or use a package manager (brew, apt, etc.)")
    sys.exit(1)

import click

from src.__version__ import __version__
from src.backup.connection import USB_HOST
from src.utils.logging import LogLevel

# ---------------------------------------------------------------------------
# Shared connection options (reused across commands)
# ---------------------------------------------------------------------------

_LOG_LEVELS = [e.value for e in LogLevel]

_connection_options = [
    click.option(
        "--host",
        default=USB_HOST,
        show_default=True,
        help="Tablet USB IP address or hostname.",
    ),
    click.option(
        "--wifi",
        "use_wifi",
        is_flag=True,
        help="Connect via Wi-Fi instead of USB.",
    ),
    click.option(
        "--wifi-host",
        default="",
        help="Tablet Wi-Fi IP address or hostname (auto-discovered when empty).",
    ),
]


def add_connection_options(func):
    """Decorator that adds the three shared connection options to a command."""
    for option in reversed(_connection_options):
        func = option(func)
    return func


def add_log_level_option(func):
    """Decorator that adds --log-level option to a command."""
    func = click.option(
        "--log-level",
        "-l",
        type=click.Choice(_LOG_LEVELS, case_sensitive=False),
        default="NONE",
        show_default=True,
        help="Console log verbosity.",
    )(func)
    return func


def print_header():
    """Print the application header using Rich, with a daily update check."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    from src.config import get_config_dir

    log_file = get_config_dir() / "reMarkablesync.log"
    console = Console(highlight=False)

    # Create header panel - using brand blue color
    brand_blue = "rgb(107,159,255)"
    header = Text()
    header.append("reMarkableSync", style=f"bold {brand_blue}")
    header.append(f" v{__version__} ", style="white")
    header.append("📝🔄", style="")
    header.append(" by Jeff Steinbok\n", style="dim")
    header.append("https://jeffsteinbok.github.io/reMarkableSync", style="link https://jeffsteinbok.github.io/reMarkableSync dim")

    console.print(Panel(header, border_style=brand_blue, padding=(0, 2)))
    console.print(f"[dim]Log file:[/dim] [link=file://{log_file}]{log_file}[/link]")
    console.print()

    # Non-blocking daily update check (errors are silently ignored)
    try:
        from src.update_checker import check_for_update, format_update_message

        latest = check_for_update()
        if latest:
            click.echo(format_update_message(latest))
    except Exception:
        pass


def check_config_compatibility() -> bool:
    """Check if config is compatible with this version.

    Returns True if OK, False if user needs to re-run config.
    Prints an error message if config is outdated.
    """
    from src.config import check_config_version

    is_valid, message = check_config_version()
    if not is_valid:
        click.echo()
        click.secho("[CONFIG OUTDATED]", fg="yellow", bold=True)
        click.echo(message)
        click.echo()
        return False
    return True


def version_callback(ctx, param, value):
    """Display version information."""
    if not value or ctx.resilient_parsing:
        return
    print_header()
    ctx.exit()


@click.group(invoke_without_command=False)
@click.option(
    "--version",
    is_flag=True,
    callback=version_callback,
    expose_value=False,
    is_eager=True,
    help="Show version and repository information",
)
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(_LOG_LEVELS, case_sensitive=False),
    default="NONE",
    show_default=True,
    help="Log verbosity: DBG, INF, WRN, ERR.",
)
@click.pass_context
def cli(ctx, log_level):
    """reMarkableSync - Backup and convert reMarkable tablet files.

    A unified tool to backup your reMarkable tablet via USB or Wi-Fi and
    convert notebooks to PDF format with template support. Notebooks can
    also be exported directly to a Markdown output directory with
    AI-transcribed text.
    """
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    # Print header for all commands (unless it's --version which handles it itself)
    if ctx.invoked_subcommand and not ctx.resilient_parsing:
        print_header()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--backup-dir",
    "-d",
    type=click.Path(path_type=Path),
    default=Path("./remarkable_backup"),
    help="Directory to store backup files",
)
@click.option("--password", "-p", type=str, help="reMarkable SSH password")
@add_log_level_option
@click.option("--skip-templates", is_flag=True, help="Skip backing up template files")
@click.option("--force", "-f", is_flag=True, help="Force backup all files (ignore sync status)")
@add_connection_options
def backup(
    backup_dir: Path,
    password: Optional[str],
    log_level: str,
    skip_templates: bool,
    force: bool,
    host: str,
    use_wifi: bool,
    wifi_host: str,
):
    """Backup files from reMarkable tablet via USB or Wi-Fi.

    Connects to your reMarkable tablet and backs up all files with incremental
    sync.  Template files are backed up by default unless --skip-templates is
    specified.
    """
    from src.commands.backup_command import run_backup_command

    sys.exit(
        run_backup_command(
            backup_dir,
            password,
            log_level,
            skip_templates,
            force,
            host=host,
            use_wifi=use_wifi,
            wifi_host=wifi_host,
        )
    )


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


@cli.command(name="pdf")
@click.option(
    "--backup-dir",
    "-d",
    type=click.Path(path_type=Path),
    default=Path("./remarkable_backup"),
    help="Directory containing reMarkable backup files",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Directory to save PDF files (default: backup_dir/pdfs_final)",
)
@add_log_level_option
@click.option("--force-all", "-f", is_flag=True, help="Convert all notebooks (ignore sync status)")
@click.option("--sample", "-s", type=int, help="Convert only first N notebooks (for testing)")
@click.option("--notebook", "-n", type=str, help="Convert only this notebook (by UUID or name)")
def pdf(
    backup_dir: Path,
    output_dir: Optional[Path],
    log_level: str,
    force_all: bool,
    sample: Optional[int],
    notebook: Optional[str],
):
    """Convert backed up notebooks to PDF format.

    Converts reMarkable notebooks to PDF with template backgrounds.
    By default, only converts notebooks that were updated in the last backup.
    """
    from src.commands.convert_command import run_convert_command

    sys.exit(run_convert_command(backup_dir, output_dir, log_level, force_all, sample, notebook))


# ---------------------------------------------------------------------------
# sync  (backup + convert)
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--backup-dir",
    "-d",
    type=click.Path(path_type=Path),
    default=Path("./remarkable_backup"),
    help="Directory to store backup files",
)
@click.option("--password", "-p", type=str, help="reMarkable SSH password")
@add_log_level_option
@click.option("--skip-templates", is_flag=True, help="Skip backing up template files")
@click.option("--force-backup", is_flag=True, help="Force backup all files")
@click.option("--force-convert", is_flag=True, help="Force convert all notebooks")
@add_connection_options
def sync(
    backup_dir: Path,
    password: Optional[str],
    log_level: str,
    skip_templates: bool,
    force_backup: bool,
    force_convert: bool,
    host: str,
    use_wifi: bool,
    wifi_host: str,
):
    """Backup and convert in one command (default workflow).

    This is the most common use case: backup your tablet and then convert
    any notebooks that were updated during the backup.
    """
    # Check config version compatibility
    if not check_config_compatibility():
        sys.exit(1)

    from src.commands.sync_command import run_sync_command

    sys.exit(
        run_sync_command(
            backup_dir,
            password,
            log_level,
            skip_templates,
            force_backup,
            force_convert,
            host=host,
            use_wifi=use_wifi,
            wifi_host=wifi_host,
        )
    )


# ---------------------------------------------------------------------------
# md  (backup + convert + OCR/AI + Markdown export)
# ---------------------------------------------------------------------------


@cli.command(name="md")
@click.option(
    "--backup-dir",
    "-d",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory to store backup files (default: from config)",
)
@click.option(
    "--vault-dir",
    "-V",
    type=click.Path(path_type=Path),
    default=None,
    help="Markdown output directory (default: from config)",
)
@click.option("--password", "-p", type=str, help="reMarkable SSH password")
@add_log_level_option
@click.option("--with-backup", is_flag=True, help="Also run tablet backup before export")
@click.option("--with-pdf", is_flag=True, help="Also run PDF conversion before export")
@click.option("--force-backup", is_flag=True, help="Force full backup")
@click.option("--force-convert", is_flag=True, help="Force convert all notebooks")
@click.option("--force-export", is_flag=True, help="Re-export all notes even if unchanged")
@click.option(
    "--ai-provider",
    default=None,
    type=click.Choice(["", "claude", "anthropic", "github", "github_models", "google", "gemini"], case_sensitive=False),
    help="AI provider for handwriting recognition",
)
@click.option("--ai-model", default="", help="Override AI model (provider-specific)")
@click.option(
    "--ai-api-key",
    default="",
    envvar="reMarkable_AI_KEY",
    help="AI API key (falls back to config / env-vars)",
)
@click.option(
    "--use-ai-ocr",
    is_flag=True,
    default=True,
    show_default=True,
    help="Use AI vision for handwriting recognition (requires --ai-provider)",
)
@click.option("--notebook", "-n", type=str, help="Export only this notebook (by name or UUID)")
@click.option("--page", type=int, help="Export only this page number (requires --notebook)")
@click.option(
    "--tags", default="reMarkable", help="Comma-separated tags to add to note frontmatter"
)
@click.option(
    "--no-images",
    "embed_images",
    is_flag=True,
    default=None,
    flag_value=False,
    help="Do not embed page images in notes",
)
@add_connection_options
def md(
    backup_dir: Optional[Path],
    vault_dir: Optional[Path],
    password: Optional[str],
    log_level: str,
    with_backup: bool,
    with_pdf: bool,
    force_backup: bool,
    force_convert: bool,
    force_export: bool,
    ai_provider: Optional[str],
    ai_model: str,
    ai_api_key: str,
    use_ai_ocr: bool,
    notebook: Optional[str],
    page: Optional[int],
    tags: str,
    embed_images: bool,
    host: str,
    use_wifi: bool,
    wifi_host: str,
):
    """Export existing PDFs to Markdown with optional AI OCR.

    By default only runs the Markdown export step.  Use --with-backup
    and/or --with-pdf to include earlier pipeline stages.

    Reads saved config for defaults (backup dir, output dir, AI provider,
    connection mode).  CLI flags override config values.

    \b
    Examples:
      # Export from existing PDFs (using saved config)
      RemarkableSync md

      # Full pipeline: backup + pdf + md
      RemarkableSync md --with-backup --with-pdf
    """
    # Check config version compatibility
    if not check_config_compatibility():
        sys.exit(1)

    from src.commands.pipeline import run_pipeline
    from src.config import load_config

    cfg = load_config()

    # Apply config defaults where CLI didn't provide a value
    if backup_dir is None:
        backup_dir = Path(cfg.get("backup_dir", "./remarkable_backup"))
    output_dir = vault_dir or Path(cfg.get("output_dir", ""))
    if not str(output_dir):
        click.echo(
            "[ERROR] No output directory specified. Use -V or run: python RemarkableSync.py config"
        )
        sys.exit(1)

    if ai_provider is None:
        ai_provider = cfg.get("ai_provider", "github")
    if not ai_model:
        ai_model = cfg.get("ai_model", "")
    if not ai_api_key:
        from src.keyring_store import (
            KEY_CLAUDE_API_KEY,
            KEY_GITHUB_TOKEN,
            KEY_GOOGLE_API_KEY,
            get_secret,
        )

        if ai_provider == "claude":
            ai_api_key = get_secret(KEY_CLAUDE_API_KEY)
        elif ai_provider in ("google", "gemini"):
            ai_api_key = get_secret(KEY_GOOGLE_API_KEY)
        else:
            ai_api_key = get_secret(KEY_GITHUB_TOKEN)

    if embed_images is None:
        embed_images = cfg.get("embed_images", True)

    # Connection defaults from config
    cfg_conn = cfg.get("connection_mode", "usb")
    if not use_wifi and cfg_conn == "wifi":
        use_wifi = True
    if not wifi_host:
        wifi_host = cfg.get("wifi_host", "")
    sys.exit(
        run_pipeline(
            backup_dir=backup_dir,
            output_dir=output_dir,
            password=password,
            log_level=log_level,
            skip_backup=not with_backup,
            skip_convert=not with_pdf,
            force_backup=force_backup,
            force_convert=force_convert,
            force_export=force_export or (not with_backup and not with_pdf),
            ai_provider=ai_provider,
            ai_model=ai_model,
            ai_api_key=ai_api_key,
            use_ai_ocr=use_ai_ocr,
            notebook_filter=notebook,
            page_filter=page,
            tags=tags,
            embed_images=embed_images,
            host=host,
            use_wifi=use_wifi,
            wifi_host=wifi_host,
        )
    )


# ---------------------------------------------------------------------------
# config  (interactive configuration wizard)
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--show",
    is_flag=True,
    help="Display current configuration without editing.",
)
@add_log_level_option
def config(show: bool, log_level: str):
    """Interactive configuration wizard.

    Walks through connection mode, credentials, folder selection, and
    sync actions using an interactive terminal UI.

    Use --show to view current settings without making changes.
    """
    if show:
        from src.commands.config_command import print_config_summary
        from src.config import get_config_path, load_config

        config_path = get_config_path()
        if not config_path.exists():
            click.echo("[ERROR] No configuration found.", err=True)
            click.echo("Run 'RemarkableSync config' to create one.", err=True)
            sys.exit(1)

        cfg = load_config()
        print_config_summary(cfg, config_path)
        sys.exit(0)

    from src.commands.config_command import run_config_command

    sys.exit(run_config_command(log_level=log_level))


# ---------------------------------------------------------------------------
# test-md  (test PDF -> Markdown conversion on a single file)
# ---------------------------------------------------------------------------


@cli.command("test-md")
@click.argument("pdf_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Save markdown output to file (default: print to stdout)",
)
@click.option(
    "--keep-images",
    "-k",
    type=click.Path(file_okay=False, path_type=Path),
    help="Save rasterized images to this directory (for debugging)",
)
@click.option(
    "--dpi",
    type=int,
    default=300,
    show_default=True,
    help="DPI for rasterizing PDF pages",
)
@click.option(
    "--chunks",
    type=int,
    default=0,
    help="Split page into N vertical chunks (0=auto based on page height)",
)
@click.option(
    "--ai-provider",
    type=click.Choice(["", "claude", "anthropic", "github", "github_models", "google", "gemini"]),
    default=None,
    help="AI provider for handwriting recognition",
)
@click.option(
    "--ai-model",
    default="",
    help="Override AI model (provider-specific)",
)
@click.option(
    "--ai-api-key",
    default="",
    help="AI API key (falls back to config / env-vars)",
)
@add_log_level_option
def test_md(
    pdf_file: Path,
    output: Optional[Path],
    keep_images: Optional[Path],
    dpi: int,
    chunks: int,
    ai_provider: Optional[str],
    ai_model: str,
    ai_api_key: str,
    log_level: str,
):
    """Test PDF to Markdown conversion on a single file.

    Useful for debugging the OCR pipeline without a full backup.
    Runs the PDF through the AI OCR engine and outputs the transcribed text.

    Examples:

      # Quick test with default settings
      RemarkableSync test-md ~/Downloads/page.pdf

      # Save output to file
      RemarkableSync test-md ~/Downloads/page.pdf -o output.md

      # Keep rasterized images for debugging
      RemarkableSync test-md page.pdf -k ./debug_images -l dbg

      # Use specific AI provider
      RemarkableSync test-md page.pdf --ai-provider github
    """
    import shutil
    import tempfile

    from src.ai import get_provider as get_ai_provider
    from src.config import get_config_dir, load_config
    from src.ocr.ocr_engine import OCREngine
    from src.utils.logging import setup_logging

    setup_logging(log_level, log_dir=get_config_dir())

    # Check config version compatibility
    if not check_config_compatibility():
        sys.exit(1)

    # Resolve AI settings from config if not provided
    cfg = load_config()
    if ai_provider is None:
        ai_provider = cfg.get("ai_provider", "github")
    if not ai_model:
        ai_model = cfg.get("ai_model", "")
    if not ai_api_key:
        from src.keyring_store import (
            KEY_CLAUDE_API_KEY,
            KEY_GITHUB_TOKEN,
            KEY_GOOGLE_API_KEY,
            get_secret,
        )

        if ai_provider == "claude":
            ai_api_key = get_secret(KEY_CLAUDE_API_KEY)
        elif ai_provider in ("google", "gemini"):
            ai_api_key = get_secret(KEY_GOOGLE_API_KEY)
        else:
            ai_api_key = get_secret(KEY_GITHUB_TOKEN)

    # Create AI provider and OCR engine
    provider = get_ai_provider(ai_provider, model=ai_model, api_key=ai_api_key)
    if not provider or not provider.is_available():
        click.echo(f"[ERROR] AI provider '{ai_provider}' is not available.", err=True)
        click.echo("Check your API key configuration.", err=True)
        sys.exit(1)

    engine = OCREngine(ai_provider=provider, image_dpi=dpi)

    click.echo(f"Processing: {pdf_file}")
    click.echo(f"AI Provider: {ai_provider}")
    click.echo(f"Model: {provider.model}")
    click.echo(f"DPI: {dpi}")
    click.echo("-" * 50)

    # Rasterize to temp or keep_images dir
    if keep_images:
        keep_images.mkdir(parents=True, exist_ok=True)
        image_dir = keep_images
        cleanup_dir = None
    else:
        cleanup_dir = tempfile.mkdtemp(prefix="rs_test_md_")
        image_dir = Path(cleanup_dir)

    try:
        from PIL import Image

        images = engine.pdf_to_images(pdf_file, image_dir)

        # Log image details and determine chunking
        chunk_images = []
        if images:
            for img_path in images:
                with Image.open(img_path) as img:
                    w, h = img.size
                    click.echo(f"Image: {img_path} ({w}x{h})")

                    # Determine number of chunks
                    # Auto: ~800px per chunk is a good target for OCR
                    if chunks == 0:
                        num_chunks = max(1, h // 800)
                    else:
                        num_chunks = chunks

                    if num_chunks > 1:
                        click.echo(f"Splitting into {num_chunks} chunks with 15% overlap")
                        # Split with overlap
                        overlap_pct = 0.15
                        base_chunk_h = h // num_chunks
                        overlap_px = int(base_chunk_h * overlap_pct)

                        for i in range(num_chunks):
                            # Calculate chunk boundaries with overlap
                            y_start = max(0, i * base_chunk_h - (overlap_px if i > 0 else 0))
                            y_end = min(
                                h,
                                (i + 1) * base_chunk_h + (overlap_px if i < num_chunks - 1 else 0),
                            )

                            chunk = img.crop((0, y_start, w, y_end))
                            chunk_path = image_dir / f"{img_path.stem}_chunk{i+1:02d}.png"
                            chunk.save(chunk_path)
                            chunk_images.append(chunk_path)
                            click.echo(f"  Chunk {i+1}: {chunk_path.name} ({w}x{y_end - y_start})")
                    else:
                        chunk_images.append(img_path)

        if keep_images:
            click.echo(f"Images saved to: {keep_images}")

        # Run OCR on the chunk images
        if chunk_images and engine.use_ai and engine.ai_provider:
            from src.ai.base_provider import AIProviderError

            all_text_parts = []
            for i, chunk_path in enumerate(chunk_images):
                click.echo(f"Processing chunk {i+1}/{len(chunk_images)}...")
                try:
                    part_text = engine.ai_provider.transcribe_handwriting(
                        [chunk_path], context=f"{pdf_file.stem} (part {i+1})"
                    )
                    if part_text:
                        all_text_parts.append(part_text)
                except AIProviderError as exc:
                    # Extract clean error message
                    err_msg = str(exc)
                    if "unknown_model" in err_msg.lower():
                        click.echo(f"[ERROR] Unknown model: {provider.model}", err=True)
                        click.echo("Run 'RemarkableSync config' to select a valid model.", err=True)
                    else:
                        click.echo(f"[ERROR] AI provider error: {err_msg}", err=True)
                    sys.exit(1)

            # Join chunks and clean up
            raw_text = "\n\n".join(all_text_parts)
            processed_text = engine.ai_provider.cleanup_text(raw_text, context=pdf_file.stem)
            text = processed_text or raw_text
        else:
            text = ""
            click.echo("[WARN] No AI provider or images - no text extracted")

        if output:
            output.write_text(text, encoding="utf-8")
            click.echo(f"Output saved to: {output}")
        else:
            click.echo(text)
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# check-update  (check for new versions)
# ---------------------------------------------------------------------------


@cli.command("check-update")
def check_update():
    """Check for a newer version of RemarkableSync."""
    from src.update_checker import check_for_update, format_update_message

    click.echo("Checking for updates...")
    latest = check_for_update(force=True)
    if latest:
        click.echo(format_update_message(latest))
    else:
        click.echo(f"✓ You are running the latest version (v{__version__}).")


# ---------------------------------------------------------------------------
# watch  (periodic sync)
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--interval",
    "-i",
    type=int,
    default=None,
    help="Minutes between sync attempts (overrides config)",
)
@click.option(
    "--systray/--no-systray",
    default=True,
    show_default=True,
    help="Show a system tray icon while watch mode is running",
)
@click.option(
    "--foreground", is_flag=True, default=False, help="Run in the foreground instead of detaching"
)
@add_log_level_option
@add_connection_options
def watch(
    interval: Optional[int],
    systray: bool,
    foreground: bool,
    log_level: str,
    host: str,
    use_wifi: bool,
    wifi_host: str,
):
    """Run periodic sync in the background with a system tray icon.

    Reads all settings from the config file (run ``config`` first).
    The tray menu lets you change the interval, trigger an immediate sync,
    pause/resume, toggle run-at-startup, and open output folders.

    By default, detaches from the terminal and runs in the background.
    Use --foreground to keep it attached.
    """
    from src.commands.watch_command import INTERVAL_CHOICES, run_watch_command
    from src.config import load_config, save_config

    cfg = load_config()

    # Determine interval: CLI flag > config > prompt on first run
    saved_interval = cfg.get("watch_interval")  # minutes, or None
    if interval is not None:
        interval_secs = interval * 60
    elif saved_interval is not None:
        interval_secs = saved_interval * 60
    else:
        # First time — ask with InquirerPy like the config wizard
        try:
            from InquirerPy import inquirer

            choices = [{"name": label, "value": secs} for label, secs in INTERVAL_CHOICES]
            interval_secs = inquirer.select(
                message="Sync interval:",
                choices=choices,
                default=30 * 60,
            ).execute()

            if interval_secs is None:
                click.echo("Cancelled.")
                sys.exit(0)
        except ImportError:
            click.echo("Pick a sync interval:\n")
            for i, (label, _secs) in enumerate(INTERVAL_CHOICES, 1):
                click.echo(f"  {i}. {label}")
            click.echo()
            choice = click.prompt(
                "Choice",
                type=click.IntRange(1, len(INTERVAL_CHOICES)),
                default=2,
            )
            _, interval_secs = INTERVAL_CHOICES[choice - 1]

        cfg["watch_interval"] = interval_secs // 60 if interval_secs else 0
        save_config(cfg)
        click.echo()

    # Detach to background unless --foreground
    if not foreground:
        # Check if already running before spawning
        backup_dir = Path(cfg.get("backup_dir", "./remarkable_backup"))
        from src.commands.watch_command import FileLock

        process_lock_path = backup_dir / ".remarkable_watch_process.lock"
        test_lock = FileLock(process_lock_path)
        if not test_lock.acquire():
            click.echo("reMarkableSync watch is already running.")
            click.echo("Use the system tray icon to control it.")
            return
        test_lock.release()  # Release so the child can acquire it

        _detach_watch()
        return

    # --- foreground mode (child process lands here) ---

    # Launch-time values used for the tray label, lock-file placement, and
    # the tray "Open" menu items. The actual sync parameters are reloaded
    # fresh on every cycle (see run_once below) so config edits take effect
    # without restarting the watcher.
    backup_dir = Path(cfg.get("backup_dir", "./remarkable_backup"))
    output_dir_str = cfg.get("output_dir", "")
    output_dir = Path(output_dir_str) if output_dir_str else None
    mode = "md" if ("ocr" in cfg.get("sync_actions", ["backup", "pdf"]) and output_dir) else "sync"

    # CLI flags act as overrides; everything else is read from config per cycle.
    cli_use_wifi = use_wifi
    cli_wifi_host = wifi_host

    from src.keyring_store import KEY_CLAUDE_API_KEY, KEY_GITHUB_TOKEN, get_secret

    def run_once() -> int:
        # Reload config each cycle so edits apply without restarting watch.
        c = load_config()
        bdir = Path(c.get("backup_dir", "./remarkable_backup"))
        out_str = c.get("output_dir", "")
        odir = Path(out_str) if out_str else None
        sync_actions = c.get("sync_actions", ["backup", "pdf"])

        eff_use_wifi = cli_use_wifi
        if not eff_use_wifi and c.get("connection_mode", "usb") == "wifi":
            eff_use_wifi = True
        eff_wifi_host = cli_wifi_host or c.get("wifi_host", "")

        ai_provider = c.get("ai_provider", "")
        if ai_provider == "claude":
            ai_api_key = get_secret(KEY_CLAUDE_API_KEY)
        else:
            ai_api_key = get_secret(KEY_GITHUB_TOKEN)
        tags = c.get("tags", "reMarkable")

        if "ocr" in sync_actions and odir:
            from src.commands.pipeline import run_pipeline

            return run_pipeline(
                backup_dir=bdir,
                output_dir=odir,
                log_level=log_level,
                skip_backup=False,
                skip_convert=False,
                force_backup=False,
                force_convert=False,
                force_export=False,
                ai_provider=ai_provider or "github",
                ai_model=c.get("ai_model", ""),
                ai_api_key=ai_api_key,
                use_ai_ocr=True,
                tags=tags,
                embed_images=c.get("embed_images", True),
                host=host,
                use_wifi=eff_use_wifi,
                wifi_host=eff_wifi_host,
            )

        from src.commands.sync_command import run_sync_command

        return run_sync_command(
            backup_dir=bdir,
            log_level=log_level,
            skip_templates=False,
            force_backup=False,
            force_convert=False,
            host=host,
            use_wifi=eff_use_wifi,
            wifi_host=eff_wifi_host,
        )

    def _get_interval_secs() -> int:
        c = load_config()
        mins = c.get("watch_interval")
        return mins * 60 if mins else 0

    def _save_interval_secs(secs: int) -> None:
        c = load_config()
        c["watch_interval"] = secs // 60 if secs else 0
        save_config(c)

    # Only re-read interval from config when it wasn't overridden on the CLI.
    get_interval = _get_interval_secs if interval is None else None

    sys.exit(
        run_watch_command(
            interval=interval_secs,
            backup_dir=backup_dir,
            run_once=run_once,
            log_level=log_level,
            mode=mode,
            use_systray=systray,
            output_dir=output_dir,
            get_interval=get_interval,
            on_interval_change=_save_interval_secs,
        )
    )


def _detach_watch():
    """Re-launch this script as a detached background process."""
    import subprocess as sp

    from src.commands.watch_command import _build_watch_launch_args

    if sys.platform == "win32":
        args = _build_watch_launch_args()
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        sp.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )
    else:
        args = _build_watch_launch_args()
        sp.Popen(
            args,
            start_new_session=True,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )

    click.echo("reMarkableSync watch started in the background.")
    click.echo("Use the system tray icon to control it.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Entry point for the application.

    When no subcommand is given, reads saved config to determine what to run:
    - If 'ocr' is in sync_actions -> obsidian-sync
    - Otherwise -> sync (backup + convert)

    Config-based defaults (backup_dir, output_dir, connection, etc.) are
    injected as CLI args so the subcommand sees them.
    """
    known_commands = {"backup", "pdf", "sync", "md", "config", "watch", "check-update", "test-md"}
    has_command = any(arg in known_commands for arg in sys.argv[1:])

    if not has_command and "--version" not in sys.argv and "--help" not in sys.argv:
        # Load config to decide which pipeline to run
        from src.config import get_config_path, load_config

        if not get_config_path().exists():
            script_name = Path(sys.argv[0]).name or "reMarkableSync.py"
            click.echo("[ERROR] No configuration found.", err=True)
            click.echo(f"Run: python {script_name} config", err=True)
            sys.exit(1)

        cfg = load_config()
        actions = cfg.get("sync_actions", [])
        extra_args: list[str] = []

        # Connection settings
        conn = cfg.get("connection_mode", "usb")
        if conn == "wifi":
            extra_args.append("--wifi")
            wifi_host = cfg.get("wifi_host", "")
            if wifi_host:
                extra_args.extend(["--wifi-host", wifi_host])

        # Backup directory
        backup_dir = cfg.get("backup_dir", "")
        if backup_dir:
            extra_args.extend(["-d", backup_dir])

        if "ocr" in actions:
            # Full pipeline: backup -> convert -> OCR -> Markdown export
            output_dir = cfg.get("output_dir", "")
            if not output_dir:
                print("[ERROR] Markdown export is enabled but no output directory is configured.")
                print("Run: python RemarkableSync.py config")
                sys.exit(1)
            extra_args.extend(["-V", output_dir])

            ai_provider = cfg.get("ai_provider", "github")
            if ai_provider:
                extra_args.extend(["--ai-provider", ai_provider])
            from src.keyring_store import KEY_CLAUDE_API_KEY, KEY_GITHUB_TOKEN, get_secret

            if ai_provider == "claude":
                ai_token = get_secret(KEY_CLAUDE_API_KEY)
            else:
                ai_token = get_secret(KEY_GITHUB_TOKEN)
            if ai_token:
                extra_args.extend(["--ai-api-key", ai_token])

            sys.argv[1:1] = ["md", "--with-backup", "--with-pdf"] + extra_args
        else:
            sys.argv[1:1] = ["sync"] + extra_args

    cli()


if __name__ == "__main__":
    main()
