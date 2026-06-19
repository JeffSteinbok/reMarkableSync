"""
Interactive configuration wizard for RemarkableSync.

Uses InquirerPy to present an interactive TUI that walks the user through
setting up connection mode, credentials, folder selection, and sync actions.
"""

from typing import Any, Dict, List

import click

from src.config import SYNC_ACTIONS, load_config, save_config
from src.utils.console import print_warn


def _print_status_message(message: str, success: bool = True) -> None:
    """Print a styled status message (success or abort)."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console(highlight=False)
    style = "green" if success else "yellow"
    console.print()
    console.print(Panel(message, border_style=style, expand=False))
    console.print()


def print_config_summary(cfg: dict, config_path=None) -> None:
    """Print a formatted config summary with aligned labels and clickable paths."""
    from rich.console import Console
    from rich.text import Text

    from src.config import load_custom_instructions

    console = Console(highlight=False)

    def _path_link(p: str) -> Text:
        """Create a clickable path link."""
        t = Text()
        t.append(str(p), style=f"link file://{p}")
        return t

    def _row(label: str, value) -> None:
        """Print a row with consistent spacing (10 char label width)."""
        console.print(f"  {label:<10} {value}")

    def _row_path(label: str, path: str) -> None:
        """Print a row with a clickable path."""
        console.print(Text(f"  {label:<10} ") + _path_link(path))

    console.print()
    if config_path:
        _row_path("File:", str(config_path))
    _row("Mode:", cfg.get("connection_mode", "usb").upper())
    if cfg.get("connection_mode") == "wifi":
        _row("Host:", cfg.get("wifi_host", "(not set)"))
    _row("Password:", "••••••••" if cfg.get("password") else "(not set)")
    if cfg.get("backup_dir"):
        _row_path("Backup:", cfg.get("backup_dir"))
    if cfg.get("pdf_dir"):
        _row_path("PDFs:", cfg.get("pdf_dir"))
    folders = cfg.get("folders", [])
    _row("Folders:", ", ".join(folders) if folders else "(all)")
    actions = cfg.get("sync_actions", [])
    _row("Actions:", ", ".join(actions))
    if cfg.get("ocr_enabled"):
        if cfg.get("output_dir"):
            _row_path("Markdown:", cfg.get("output_dir"))
        _row("Images:", "yes (_images/ folder)" if cfg.get("embed_images") else "no")
        _row("AI:", f"{cfg.get('ai_provider', 'github')} ({cfg.get('ai_model', '')})")
        # Show custom instructions status
        custom_path = cfg.get("ocr_custom_instructions", "")
        custom_text = load_custom_instructions()
        if custom_path:
            _row_path("Custom:", custom_path)
        elif custom_text:
            _row("Custom:", "(using default location)")
        else:
            _row("Custom:", "(none)")
    if cfg.get("pre_sync_command"):
        _row("Pre:", cfg.get("pre_sync_command"))
    if cfg.get("post_sync_command"):
        _row("Post:", cfg.get("post_sync_command"))
    console.print()


def run_config_command(log_level: str = "NONE") -> int:
    """Run the interactive configuration wizard.

    Args:
        log_level: Log verbosity level (DBG, INF, WRN, ERR, NONE).
    """
    from src.config import get_config_dir
    from src.utils.logging import setup_logging

    log_dir = get_config_dir()
    setup_logging(log_level, log_dir=log_dir)

    try:
        from InquirerPy import inquirer
        from InquirerPy.separator import Separator  # noqa: F401
    except ImportError:
        click.echo("Error: InquirerPy is required for the config wizard.")
        click.echo("Install it with:  pip install InquirerPy")
        return 1

    current = load_config()

    from rich.console import Console
    from rich.rule import Rule

    console = Console(highlight=False)
    console.print()
    console.print(Rule("[bold]Configuration Wizard[/bold]", style="dim"))
    click.echo()
    click.secho("  This wizard will guide you through the setup process.", fg="yellow")
    click.secho("  Press Ctrl+C at any time to abort without saving changes.", fg="yellow")
    click.echo()

    try:
        return _run_wizard(current, inquirer)
    except KeyboardInterrupt:
        _print_status_message("Aborted. No changes saved.", success=False)
        return 0


def _run_wizard(current, inquirer) -> int:
    """Internal wizard logic."""
    # 1. Connection Mode
    connection_mode = inquirer.select(
        message="Connection mode:",
        choices=[
            {"name": "USB  (direct cable connection)", "value": "usb"},
            {"name": "WiFi (wireless network connection)", "value": "wifi"},
        ],
        default=current.get("connection_mode", "usb"),
    ).execute()

    if connection_mode is None:
        _print_status_message("Aborted. No changes saved.", success=False)
        return 0

    # 2. WiFi Host (only if WiFi mode selected)
    wifi_host = current.get("wifi_host", "")
    if connection_mode == "wifi":
        # Offer to enable WiFi SSH via USB if not already enabled
        wifi_ready = inquirer.confirm(
            message="Is WiFi SSH already enabled on your tablet?",
            default=bool(wifi_host),
        ).execute()

        if not wifi_ready:
            click.echo()
            click.echo("  We can enable it for you! Make sure the tablet is")
            click.echo("  connected via USB cable and on the same WiFi network.")
            click.echo()

            enable_now = inquirer.confirm(
                message="Enable WiFi SSH via USB now?",
                default=True,
            ).execute()

            if enable_now:
                # Need password first to connect via USB
                tmp_password = current.get("password", "")
                if not tmp_password:
                    click.echo()
                    click.echo("  SSH password: Settings > Help > Copyright and licenses")
                    tmp_password = inquirer.secret(
                        message="SSH password:",
                        transformer=lambda _: "********" if _ else "(empty)",
                    ).execute()
                    if not tmp_password:
                        click.echo("  Skipped — no password provided.")
                    else:
                        # Save so we don't ask again below
                        password = tmp_password

                if tmp_password:
                    wifi_host = _enable_wifi_ssh(tmp_password)
                    if not wifi_host:
                        click.echo()
                        click.echo("  Could not enable WiFi SSH automatically.")
                        click.secho("  To enable it manually:", fg="yellow")
                        click.secho("    1. Connect tablet via USB", fg="yellow")
                        click.secho("    2. SSH into 10.11.99.1", fg="yellow")
                        click.secho("    3. Run: rm-ssh-over-wlan on", fg="yellow")
                        click.secho("    4. Find IP: ip addr show wlan0", fg="yellow")
                        click.secho("    5. Re-run this wizard", fg="yellow")
                        return 1
            else:
                click.echo()
                click.secho("  To enable WiFi SSH on your reMarkable:", fg="yellow")
                click.secho("    1. Connect tablet to your computer via USB", fg="yellow")
                click.secho("    2. SSH into 10.11.99.1 (password on tablet:", fg="yellow")
                click.secho("       Settings > Help > Copyright and licenses)", fg="yellow")
                click.secho("    3. Run: rm-ssh-over-wlan on", fg="yellow")
                click.secho("    4. Note the WiFi IP: ip addr show wlan0", fg="yellow")
                click.secho("    5. Re-run this wizard with the IP ready", fg="yellow")
                return 1

        # Let user confirm/change the IP (pre-filled from device or config; blank if unknown)
        default_ip = wifi_host or current.get("wifi_host", "") or ""
        wifi_host = inquirer.text(
            message="Tablet WiFi IP address:",
            default=default_ip,
        ).execute()

        if wifi_host is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0

    # 3. Password
    current_password = current.get("password", "")
    if current_password:
        click.echo("  SSH password: (saved)")
        change_pw = inquirer.confirm(
            message="Do you want to change the SSH password?",
            default=False,
        ).execute()
        if change_pw:
            password = inquirer.secret(
                message="New SSH password:",
                transformer=lambda _: "********" if _ else "(empty)",
            ).execute()
            if password is None:
                _print_status_message("Aborted. No changes saved.", success=False)
                return 0
            _offer_keyring_save(password)
        else:
            password = current_password
    else:
        click.echo("  SSH password: (not set)")
        password = inquirer.secret(
            message="SSH password (Settings > Help > Copyright and licenses):",
            transformer=lambda _: "********" if _ else "(empty)",
        ).execute()
        if password is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0
        if password:
            _offer_keyring_save(password)

    # 4. Backup directory (internal data — defaults to AppData)
    from src.config import _default_backup_dir

    current_backup_dir = current.get("backup_dir", "")
    default_backup = current_backup_dir or _default_backup_dir()
    backup_dir = inquirer.text(
        message="Backup directory (internal sync data, blank=default):",
        default=default_backup,
    ).execute()

    if backup_dir is None:
        _print_status_message("Aborted. No changes saved.", success=False)
        return 0
    if not backup_dir.strip():
        backup_dir = _default_backup_dir()
        click.echo(f"  Using default: {backup_dir}")

    # 5. Sync actions — later steps imply earlier ones (backup → pdf → ocr)
    action_order = [value for value, _ in SYNC_ACTIONS]
    current_actions = current.get("sync_actions", ["backup", "pdf", "ocr"])
    if not current_actions:
        current_actions = action_order

    # Build cascade choices: each option enables all steps up to and including it
    cascade_labels = {
        "backup": "Backup only",
        "pdf": "Backup + PDF Conversion",
        "ocr": "Backup + PDF Conversion + AI OCR & Markdown Export",
    }
    highest_current = max(
        (action_order.index(a) for a in current_actions if a in action_order), default=0
    )
    default_action = action_order[highest_current]

    chosen = inquirer.select(
        message="What to do on sync:",
        choices=[{"name": cascade_labels[value], "value": value} for value, _ in SYNC_ACTIONS],
        default=default_action,
    ).execute()

    if chosen is None:
        _print_status_message("Aborted. No changes saved.", success=False)
        return 0

    # Cascade: all steps up to and including the chosen step
    sync_actions = action_order[: action_order.index(chosen) + 1]

    # 6. PDF output directory (if PDF or OCR selected)
    from src.config import _default_documents_dir

    docs = _default_documents_dir()
    pdf_dir = current.get("pdf_dir", "")

    if "pdf" in sync_actions or "ocr" in sync_actions:
        default_pdf_dir = pdf_dir or str(docs / "RemarkableSync" / "PDF")
        pdf_dir = inquirer.text(
            message="PDF output directory (blank=default):",
            default=default_pdf_dir,
        ).execute()

        if pdf_dir is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0
        if not pdf_dir.strip():
            pdf_dir = str(docs / "RemarkableSync" / "PDF")
            click.echo(f"  Using default: {pdf_dir}")

    # 7. Markdown export settings — OCR is implied when export is selected
    ocr_enabled = "ocr" in sync_actions
    output_dir = current.get("output_dir", "")
    embed_images = current.get("embed_images", True)

    if ocr_enabled:
        default_output_dir = output_dir or str(docs / "RemarkableSync" / "Markdown")
        output_dir = inquirer.text(
            message="Markdown output directory (blank=default):",
            default=default_output_dir,
        ).execute()

        if output_dir is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0
        if not output_dir.strip():
            output_dir = str(docs / "RemarkableSync" / "Markdown")
            click.echo(f"  Using default: {output_dir}")

        # 7b. Embed page images with Markdown?
        embed_images = inquirer.confirm(
            message="Include page images alongside Markdown files?",
            default=embed_images,
        ).execute()

        if embed_images is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0

    # 7. AI provider selection (only if OCR is enabled)
    ai_provider = current.get("ai_provider", "github")
    ai_model = current.get("ai_model", "")
    github_token = ""
    claude_api_key = ""

    if ocr_enabled:
        ai_provider = inquirer.select(
            message="AI provider for handwriting recognition:",
            choices=[
                {"name": "GitHub Models", "value": "github"},
                {"name": "Claude / Anthropic  (requires API key)", "value": "claude"},
            ],
            default=ai_provider,
        ).execute()

        if ai_provider is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0

        # Authenticate first so we can fetch models
        if ai_provider == "github":
            from src.keyring_store import KEY_GITHUB_TOKEN, get_secret, set_secret

            existing = get_secret(KEY_GITHUB_TOKEN)
            if existing:
                click.echo("  GitHub token: (saved in keyring)")
                change = inquirer.confirm(
                    message="Re-authenticate with GitHub?",
                    default=False,
                ).execute()
                if change:
                    github_token = _run_device_flow()
                    if github_token:
                        set_secret(KEY_GITHUB_TOKEN, github_token)
                else:
                    github_token = existing
            else:
                click.echo()
                click.secho("  GitHub authentication required for AI OCR.", fg="yellow")
                github_token = _run_device_flow()
                if github_token:
                    set_secret(KEY_GITHUB_TOKEN, github_token)
                else:
                    click.echo(
                        "  Authentication skipped. You can set GITHUB_TOKEN env var instead."
                    )

            # Model selection for GitHub - fetch available models
            from src.ai.github_copilot_provider import get_available_models

            default_model = ai_model if ai_model else "gpt-5-mini"
            models = get_available_models(github_token, vision_only=True) if github_token else []

            if models:
                # Build choices list
                model_choices = [
                    {"name": display, "value": model_id} for model_id, display in models
                ]
                # Find default in list
                default_idx = next(
                    (i for i, (mid, _) in enumerate(models) if mid == default_model), 0
                )
                ai_model = (
                    inquirer.select(
                        message="GitHub Models model:",
                        choices=model_choices,
                        default=(
                            model_choices[default_idx]["value"] if model_choices else default_model
                        ),
                    ).execute()
                    or default_model
                )
            else:
                # Fallback to text input if can't fetch models
                ai_model = (
                    inquirer.text(
                        message="GitHub Models model:",
                        default=default_model,
                    ).execute()
                    or default_model
                )

        elif ai_provider == "claude":
            from src.keyring_store import KEY_CLAUDE_API_KEY, get_secret, set_secret

            existing = get_secret(KEY_CLAUDE_API_KEY)
            if existing:
                click.echo("  Claude API key: (saved in keyring)")
                change = inquirer.confirm(
                    message="Change Claude API key?",
                    default=False,
                ).execute()
                if change:
                    claude_api_key = (
                        inquirer.secret(
                            message="Anthropic API key:",
                            transformer=lambda _: "••••••••" if _ else "(empty)",
                        ).execute()
                        or ""
                    )
                    if claude_api_key:
                        set_secret(KEY_CLAUDE_API_KEY, claude_api_key)
                else:
                    claude_api_key = existing
            else:
                click.echo()
                click.secho("  To use Claude for handwriting recognition you need an", fg="yellow")
                click.secho("  Anthropic API key:", fg="yellow")
                click.echo()
                click.secho("  1. Go to  https://console.anthropic.com/settings/keys", fg="yellow")
                click.secho("  2. Click 'Create Key' and give it a name", fg="yellow")
                click.secho("  3. Copy the key (starts with sk-ant-...)", fg="yellow")
                click.secho("  4. Paste it below — it will be stored securely in", fg="yellow")
                click.secho("     your system keyring (never written to config files)", fg="yellow")
                click.echo()
                claude_api_key = (
                    inquirer.secret(
                        message="Anthropic API key:",
                        transformer=lambda _: "••••••••" if _ else "(empty)",
                    ).execute()
                    or ""
                )
                if claude_api_key:
                    set_secret(KEY_CLAUDE_API_KEY, claude_api_key)
                else:
                    click.echo("  Skipped. You can set ANTHROPIC_API_KEY env var instead.")

            # Model selection for Claude
            default_model = ai_model if ai_model else "claude-sonnet-4-6"
            ai_model = (
                inquirer.text(
                    message="Claude model:",
                    default=default_model,
                ).execute()
                or default_model
            )

    # 8a. Custom OCR instructions (optional)
    ocr_custom_instructions = ""
    if ocr_enabled:
        from src.config import get_custom_instructions_path

        default_instructions_path = get_custom_instructions_path()
        current_instructions = current.get("ocr_custom_instructions", "")

        click.echo()
        click.secho("  Optional: custom instructions for OCR transcription.", fg="yellow")
        click.secho(f"  Default location: {default_instructions_path}", fg="yellow")
        click.secho("  Leave blank to use default location (if file exists).", fg="yellow")
        click.echo()

        ocr_custom_instructions = (
            inquirer.text(
                message="Custom instructions file (blank=default):",
                default=current_instructions,
            ).execute()
            or ""
        )

    # 8b. Pre/post-sync commands (optional)
    pre_sync_command = current.get("pre_sync_command", "")
    post_sync_command = current.get("post_sync_command", "")

    click.echo()
    click.secho("  Optional: shell commands to run before and after sync.", fg="yellow")
    click.secho(
        "  Useful for disabling VPNs, network tools, etc. Leave blank to skip.", fg="yellow"
    )
    click.echo()

    pre_sync_command = (
        inquirer.text(
            message="Pre-sync command (blank=none):",
            default=pre_sync_command,
        ).execute()
        or ""
    )

    post_sync_command = (
        inquirer.text(
            message="Post-sync command (blank=none):",
            default=post_sync_command,
        ).execute()
        or ""
    )

    # 9. Connect to tablet and select folders
    click.echo()
    click.echo("  Connecting to tablet to discover folders...")

    folder_choices = _get_folder_choices_live(
        connection_mode,
        password,
        wifi_host,
        pre_sync_command=pre_sync_command,
        post_sync_command=post_sync_command,
    )
    folders: List[str] = []

    if folder_choices:
        saved_folders = current.get("folders", [])
        # Pre-check previously selected folders
        for choice in folder_choices:
            if isinstance(choice, dict) and choice.get("value") in saved_folders:
                choice["enabled"] = True

        folders = inquirer.checkbox(
            message="Folders to sync (empty = sync all):",
            choices=folder_choices,
        ).execute()

        if folders is None:
            _print_status_message("Aborted. No changes saved.", success=False)
            return 0
    else:
        print_warn("  WRN - Could not connect to tablet. Folder selection skipped.")
        folders = current.get("folders", [])

    # Save password to keyring (not in config file)
    password_saved_to_keyring = False
    if password:
        from src.backup.credential_store import create_credential_store

        store = create_credential_store(use_keyring=True)
        if store.set_password("reMarkableSync", "reMarkable_ssh", password):
            password_saved_to_keyring = True
        else:
            print_warn(
                "  WRN - Could not save password to keyring. You may need to enter it each sync."
            )

    # Save configuration — preserve keys not managed by this wizard
    # Note: password is stored in keyring, not in config file
    config = dict(current)
    config.update(
        {
            "connection_mode": connection_mode,
            "wifi_host": wifi_host,
            "password_in_keyring": password_saved_to_keyring,
            "backup_dir": backup_dir,
            "pdf_dir": pdf_dir,
            "folders": folders,
            "sync_actions": sync_actions,
            "ocr_enabled": ocr_enabled,
            "output_dir": output_dir,
            "embed_images": embed_images,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "ocr_custom_instructions": ocr_custom_instructions,
            "pre_sync_command": pre_sync_command,
            "post_sync_command": post_sync_command,
        }
    )

    path = save_config(config)

    _print_status_message("Configuration saved!")

    from rich.console import Console
    from rich.text import Text

    console = Console(highlight=False)

    def _path_link(p: str) -> Text:
        """Create a clickable path link."""
        t = Text()
        t.append(p, style=f"link file://{p}")
        return t

    console.print(Text("  File:       ") + _path_link(str(path)))
    click.echo(f"  Mode:       {connection_mode.upper()}")
    if connection_mode == "wifi":
        click.echo(f"  Host:       {wifi_host}")
    click.echo(f"  Password:   {'••••••••' if password else '(not set)'}")
    console.print(Text("  Backup:     ") + _path_link(backup_dir))
    if pdf_dir:
        console.print(Text("  PDFs:       ") + _path_link(pdf_dir))
    click.echo(f"  Folders:    {', '.join(folders) if folders else '(all)'}")
    click.echo(f"  Actions:    {', '.join(sync_actions)}")
    if ocr_enabled:
        console.print(Text("  Markdown:   ") + _path_link(output_dir))
        click.echo(f"  Images:     {'yes (_images/ folder)' if embed_images else 'no'}")
        click.echo(f"  AI:         {ai_provider} ({ai_model})")
        has_token = bool(github_token or claude_api_key)
        click.echo(f"  Token:      {'OK - saved in keyring' if has_token else '(not set)'}")
        # Show custom instructions status
        from src.config import load_custom_instructions

        custom_text = load_custom_instructions()
        if ocr_custom_instructions:
            console.print(Text("  Custom:     ") + _path_link(ocr_custom_instructions))
        elif custom_text:
            click.echo("  Custom:     (using default location)")
        else:
            click.echo("  Custom:     (none)")
    if pre_sync_command:
        click.echo(f"  Pre:       {pre_sync_command}")
    if post_sync_command:
        click.echo(f"  Post:      {post_sync_command}")
    click.echo()

    return 0


def _offer_keyring_save(password: str) -> None:
    """Offer to save the SSH password to the system keyring."""
    try:
        from src.backup.connection import KEYRING_AVAILABLE, ReMarkableConnection
    except ImportError:
        return

    if not KEYRING_AVAILABLE:
        return

    try:
        from InquirerPy import inquirer

        save = inquirer.confirm(
            message="Save password to system keyring?",
            default=True,
        ).execute()
        if save:
            conn = ReMarkableConnection.__new__(ReMarkableConnection)
            conn.save_password(password)
            click.echo("  Password saved to keyring.")
    except Exception:
        pass


def _enable_wifi_ssh(password: str) -> str:
    """Connect via USB and enable WiFi SSH on the tablet.

    Runs ``rm-ssh-over-wlan on`` on the device, then reads the WiFi IP.

    Returns:
        The tablet's WiFi IP address, or empty string on failure.
    """
    import re

    try:
        from src.backup.connection import USB_HOST, ReMarkableConnection
    except ImportError:
        click.echo("  WRN - Could not import connection module.")
        return ""

    conn = ReMarkableConnection(password=password, host=USB_HOST)
    click.echo("  Connecting via USB...")

    if not conn.connect():
        print_warn("  WRN - Could not connect via USB. Is the tablet plugged in?")
        return ""

    try:
        # Enable WiFi SSH
        click.echo("  Enabling WiFi SSH...")
        stdout, stderr, exit_code = conn.execute_command("rm-ssh-over-wlan on")
        if exit_code != 0:
            click.echo(f"  WRN - Command failed: {stderr.strip() or stdout.strip()}")
            return ""

        click.echo("  WiFi SSH enabled!")

        # Get the WiFi IP address
        stdout, stderr, exit_code = conn.execute_command(
            "ip -4 addr show wlan0 | awk '/inet / {split($2, a, \"/\"); print a[1]}'"
        )
        if exit_code == 0 and stdout.strip():
            ip = stdout.strip().split("\n")[0]
            # Validate it looks like an IP
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                click.echo(f"  Tablet WiFi IP: {ip}")
                return ip

        click.echo("  WRN - Could not determine WiFi IP. Is the tablet on WiFi?")
        return ""

    except Exception as exc:
        click.echo(f"  WRN - Error enabling WiFi SSH: {exc}")
        return ""
    finally:
        conn.disconnect()


def _get_folder_choices_live(
    connection_mode: str,
    password: str,
    wifi_host: str,
    pre_sync_command: str = "",
    post_sync_command: str = "",
) -> List[Dict[str, Any]]:
    """Connect to the tablet and discover top-level folders.

    Returns a list of choices for InquirerPy, or an empty list on failure.
    """
    import logging

    try:
        from src.backup.connection import USB_HOST, ReMarkableConnection
    except ImportError:
        return []

    use_wifi = connection_mode == "wifi"
    host = wifi_host if use_wifi else USB_HOST

    conn = ReMarkableConnection(
        password=password,
        host=host,
        use_wifi=use_wifi,
        wifi_host=wifi_host,
        pre_sync_command=pre_sync_command,
        post_sync_command=post_sync_command,
    )

    try:
        if not conn.connect():
            print_warn("  WRN - Could not connect to tablet.")
            return []
        xochitl = "/home/root/.local/share/remarkable/xochitl"

        # Use a single command to dump all metadata files efficiently
        # Output format: one JSON object per line, prefixed with filename
        stdout, stderr, exit_code = conn.execute_command(
            f"for f in {xochitl}/*.metadata; do "
            f'[ -f "$f" ] && echo "FILE:$f" && cat "$f"; '
            f"done"
        )
        if exit_code != 0:
            click.echo("  WRN - Failed to read metadata from tablet.")
            return []

        # Parse the output — each metadata block starts with FILE: line
        folders: List[str] = []
        current_json = []
        for line in stdout.split("\n"):
            if line.startswith("FILE:"):
                # Process previous block
                if current_json:
                    _parse_folder_metadata("\n".join(current_json), folders)
                current_json = []
            else:
                current_json.append(line)
        # Process last block
        if current_json:
            _parse_folder_metadata("\n".join(current_json), folders)

        if not folders:
            click.echo("  No top-level folders found on tablet.")
            return []

        click.echo(f"  Found {len(folders)} folders on tablet.")
        folders.sort()
        choices = [{"name": "(Root) - notebooks not in any folder", "value": "(Root)"}]
        choices += [{"name": f, "value": f} for f in folders]
        return choices

    except Exception as exc:
        logging.debug("Failed to list folders from tablet: %s", exc)
        click.echo(f"  WRN - Error reading folders: {exc}")
        return []
    finally:
        conn.disconnect()


def _parse_folder_metadata(json_text: str, folders: List[str]) -> None:
    """Parse a metadata JSON block and append folder name if it's a top-level collection."""
    import json

    json_text = json_text.strip()
    if not json_text:
        return
    try:
        meta = json.loads(json_text)
        if meta.get("type") == "CollectionType" and meta.get("parent", "") == "":
            name = meta.get("visibleName", "")
            if name:
                folders.append(name)
    except (json.JSONDecodeError, ValueError):
        pass


def _run_device_flow() -> str:
    """Run GitHub device code flow and return the token, or empty string on failure."""
    try:
        from src.auth.github_device_flow import device_flow_authenticate
    except ImportError:
        click.echo("  Error: requests library required for GitHub auth.")
        return ""

    click.echo()

    def on_code(uri, code):
        # Copy code to clipboard for easy pasting
        try:
            import subprocess

            subprocess.run(
                ["clip"],
                input=code.encode(),
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            copied = " (copied to clipboard)"
        except Exception:
            copied = ""

        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console(highlight=False)
        content = Text()
        content.append("Visit: ", style="bold")
        content.append(uri, style="bold link " + uri)
        content.append(f"\nEnter code: {code}{copied}", style="bold cyan")
        console.print()
        console.print(Panel(content, title="GitHub Authorization", border_style="cyan"))
        click.echo()
        click.secho("  Waiting for authorization...", fg="yellow", nl=False)

    try:
        token, error = device_flow_authenticate(on_code_received=on_code)
    except Exception as e:
        click.echo(f"\n  Error during authentication: {e}")
        return ""

    if token:
        click.echo(" OK")
        click.echo("  Authenticated successfully!")
        return token
    else:
        click.echo(f"\n  {error}")
        return ""
