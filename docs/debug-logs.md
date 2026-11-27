# How to Get DEBUG Logs

When filing a bug report, a DEBUG log helps us diagnose the issue quickly. The log captures detailed information about every step reMarkableSync performs.

## Getting a DEBUG Log

Re-run the command that caused the issue with `--log-level DBG`:

```bash
# Examples:
reMarkableSync sync --log-level DBG
reMarkableSync sync --wifi --log-level DBG
reMarkableSync convert --log-level DBG
```

This does two things:

1. **Prints** detailed debug output to the console
2. **Writes** a full log to the machine-local `remarkablesync.log` file

## Finding the Log File

Logs stay outside your backup and export directories so cloud sync is not blocked by open runtime files:

| Platform | Default Location |
|----------|-----------------|
| macOS    | `~/Library/Caches/remarkablesync/logs/remarkablesync.log` |
| Windows  | `%LOCALAPPDATA%\remarkablesync\logs\remarkablesync.log` |
| Linux    | `~/.local/state/remarkablesync/logs/remarkablesync.log` |

On Linux, `XDG_STATE_HOME` overrides `~/.local/state`. The CLI header and the tray's **Open Log File** item point to the current log.

## Attaching to a Bug Report

1. Copy the console output or open the `remarkablesync.log` file
2. Paste it into the **Debug Log** field in the bug report template
3. For long logs, attach the file directly to the GitHub issue

## Sensitive Information

The DEBUG log may contain file paths and notebook names from your reMarkable tablet. It does **not** log passwords or API tokens. Review the log before posting if you're concerned about privacy.
