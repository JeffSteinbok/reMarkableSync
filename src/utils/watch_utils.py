"""Pure utility functions for watch command.

These functions contain no I/O or threading — they're pure calculations
that can be easily tested.
"""

from datetime import datetime, timedelta


def format_interval(seconds: int) -> str:
    """Format seconds into human-readable interval string.

    Args:
        seconds: Number of seconds (0 or negative means "manual")

    Returns:
        Human-readable string like "5m", "1h", "2h 30m", or "manual"

    Examples:
        >>> format_interval(0)
        'manual'
        >>> format_interval(300)
        '5m'
        >>> format_interval(3600)
        '1h'
        >>> format_interval(5400)
        '1h 30m'
    """
    if seconds <= 0:
        return "manual"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m" if m else f"{h}h"


def parse_interval(value: str) -> int:
    """Parse interval string into seconds.

    Accepts formats like "30s", "5m", "1h", "2h30m", "manual".

    Args:
        value: Interval string to parse

    Returns:
        Number of seconds (0 for "manual" or invalid input)

    Examples:
        >>> parse_interval("30s")
        30
        >>> parse_interval("5m")
        300
        >>> parse_interval("1h")
        3600
        >>> parse_interval("2h30m")
        9000
        >>> parse_interval("manual")
        0
    """
    value = value.strip().lower()
    if not value or value == "manual":
        return 0

    total = 0
    current_num = ""

    for char in value:
        if char.isdigit():
            current_num += char
        elif char == "s" and current_num:
            total += int(current_num)
            current_num = ""
        elif char == "m" and current_num:
            total += int(current_num) * 60
            current_num = ""
        elif char == "h" and current_num:
            total += int(current_num) * 3600
            current_num = ""
        # Ignore other characters (spaces, etc.)

    # Handle trailing number with no unit (assume seconds)
    if current_num:
        total += int(current_num)

    return total


def next_run_time(seconds: int, now: datetime = None) -> str:
    """Calculate human-readable timestamp for next scheduled run.

    Args:
        seconds: Interval in seconds until next run
        now: Current time (defaults to datetime.now())

    Returns:
        Formatted timestamp string like "06/16/2026 23:45"
    """
    if now is None:
        now = datetime.now()
    t = now + timedelta(seconds=seconds)
    return t.strftime("%m/%d/%Y %H:%M")


def calculate_backoff(
    consecutive_failures: int,
    initial_backoff: int = 60,
    max_backoff: int = 3600,
    backoff_factor: int = 2,
) -> int:
    """Calculate exponential backoff delay after failures.

    Args:
        consecutive_failures: Number of consecutive failures (1-based)
        initial_backoff: Starting backoff in seconds (default 60)
        max_backoff: Maximum backoff in seconds (default 3600 = 1 hour)
        backoff_factor: Exponential growth factor (default 2)

    Returns:
        Backoff delay in seconds

    Examples:
        >>> calculate_backoff(0)
        0
        >>> calculate_backoff(1)
        60
        >>> calculate_backoff(2)
        120
        >>> calculate_backoff(3)
        240
        >>> calculate_backoff(10)  # capped at max
        3600
    """
    if consecutive_failures <= 0:
        return 0
    backoff = initial_backoff * (backoff_factor ** (consecutive_failures - 1))
    return min(backoff, max_backoff)


def extract_notebook_uuid(relative_path: str) -> str | None:
    """Extract notebook UUID from a relative file path.

    Args:
        relative_path: Path relative to xochitl directory (e.g., "uuid.metadata",
                       "uuid/page.rm", "uuid.content")

    Returns:
        UUID string if found, None otherwise

    Examples:
        >>> extract_notebook_uuid("abc12345-1234-1234-1234-123456789012.metadata")
        'abc12345-1234-1234-1234-123456789012'
        >>> extract_notebook_uuid("abc12345-1234-1234-1234-123456789012/page1.rm")
        'abc12345-1234-1234-1234-123456789012'
        >>> extract_notebook_uuid("version")
        None
    """
    # Normalize path separators for cross-platform
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if not parts:
        return None

    # Extract first component, strip extension
    first = parts[0].split(".")[0]

    # UUID is 36 chars (8-4-4-4-12 with hyphens)
    if len(first) == 36 and first not in ("templates", "version"):
        return first

    return None


def is_file_in_allowed_uuids(relative_path: str, allowed_uuids: set) -> bool:
    """Check if a file belongs to one of the allowed notebook UUIDs.

    Args:
        relative_path: Path relative to xochitl directory
        allowed_uuids: Set of allowed notebook UUIDs

    Returns:
        True if file belongs to an allowed UUID or is a non-UUID file
    """
    uuid = extract_notebook_uuid(relative_path)
    if uuid is None:
        # Non-UUID files (version, etc.) are always allowed
        return True
    return uuid in allowed_uuids
