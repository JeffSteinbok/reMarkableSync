"""Tests for watch_utils module."""

from datetime import datetime

from src.utils.watch_utils import (
    calculate_backoff,
    extract_notebook_uuid,
    format_interval,
    is_file_in_allowed_uuids,
    next_run_time,
    parse_interval,
)


class TestFormatInterval:
    """Tests for format_interval function."""

    def test_zero_returns_manual(self):
        """Zero seconds returns 'manual'."""
        assert format_interval(0) == "manual"

    def test_negative_returns_manual(self):
        """Negative seconds returns 'manual'."""
        assert format_interval(-100) == "manual"

    def test_seconds_under_minute(self):
        """Seconds under 60 show as seconds."""
        assert format_interval(30) == "30s"
        assert format_interval(59) == "59s"

    def test_minutes(self):
        """60-3599 seconds show as minutes."""
        assert format_interval(60) == "1m"
        assert format_interval(300) == "5m"
        assert format_interval(1800) == "30m"

    def test_hours_without_minutes(self):
        """Exact hours show without minutes."""
        assert format_interval(3600) == "1h"
        assert format_interval(7200) == "2h"

    def test_hours_with_minutes(self):
        """Hours with leftover minutes show both."""
        assert format_interval(5400) == "1h 30m"
        assert format_interval(9000) == "2h 30m"
        assert format_interval(3660) == "1h 1m"


class TestParseInterval:
    """Tests for parse_interval function."""

    def test_empty_returns_zero(self):
        """Empty string returns 0."""
        assert parse_interval("") == 0

    def test_manual_returns_zero(self):
        """'manual' returns 0."""
        assert parse_interval("manual") == 0
        assert parse_interval("MANUAL") == 0

    def test_seconds(self):
        """Seconds are parsed correctly."""
        assert parse_interval("30s") == 30
        assert parse_interval("90s") == 90

    def test_minutes(self):
        """Minutes are converted to seconds."""
        assert parse_interval("5m") == 300
        assert parse_interval("30m") == 1800

    def test_hours(self):
        """Hours are converted to seconds."""
        assert parse_interval("1h") == 3600
        assert parse_interval("2h") == 7200

    def test_combined_units(self):
        """Combined units are summed."""
        assert parse_interval("1h30m") == 5400
        assert parse_interval("2h 30m") == 9000
        assert parse_interval("1h 30m 30s") == 5430

    def test_bare_number_treated_as_seconds(self):
        """Number without unit treated as seconds."""
        assert parse_interval("300") == 300


class TestNextRunTime:
    """Tests for next_run_time function."""

    def test_adds_interval_to_now(self):
        """Adds interval to current time."""
        now = datetime(2026, 6, 16, 22, 0, 0)
        result = next_run_time(1800, now=now)
        assert result == "06/16/2026 22:30"

    def test_crosses_hour(self):
        """Handles crossing hour boundary."""
        now = datetime(2026, 6, 16, 23, 45, 0)
        result = next_run_time(1800, now=now)
        assert result == "06/17/2026 00:15"


class TestCalculateBackoff:
    """Tests for calculate_backoff function."""

    def test_zero_failures_returns_zero(self):
        """No failures means no backoff."""
        assert calculate_backoff(0) == 0

    def test_first_failure_returns_initial(self):
        """First failure returns initial backoff."""
        assert calculate_backoff(1) == 60

    def test_exponential_growth(self):
        """Backoff grows exponentially."""
        assert calculate_backoff(1) == 60
        assert calculate_backoff(2) == 120
        assert calculate_backoff(3) == 240
        assert calculate_backoff(4) == 480

    def test_capped_at_max(self):
        """Backoff is capped at max_backoff."""
        assert calculate_backoff(10) == 3600  # Would be 30720 without cap
        assert calculate_backoff(100) == 3600

    def test_custom_parameters(self):
        """Custom parameters are respected."""
        assert calculate_backoff(1, initial_backoff=10) == 10
        assert calculate_backoff(3, initial_backoff=10, backoff_factor=3) == 90
        assert calculate_backoff(10, max_backoff=100) == 100


class TestExtractNotebookUuid:
    """Tests for extract_notebook_uuid function."""

    def test_extracts_from_metadata_file(self):
        """Extracts UUID from .metadata file path."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        assert extract_notebook_uuid(f"{uuid}.metadata") == uuid

    def test_extracts_from_content_file(self):
        """Extracts UUID from .content file path."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        assert extract_notebook_uuid(f"{uuid}.content") == uuid

    def test_extracts_from_subdirectory(self):
        """Extracts UUID from subdirectory path."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        assert extract_notebook_uuid(f"{uuid}/page1.rm") == uuid

    def test_returns_none_for_version(self):
        """Returns None for 'version' file."""
        assert extract_notebook_uuid("version") is None

    def test_returns_none_for_templates(self):
        """Returns None for 'templates' directory."""
        assert extract_notebook_uuid("templates") is None

    def test_returns_none_for_short_name(self):
        """Returns None for non-UUID names."""
        assert extract_notebook_uuid("somefile.txt") is None


class TestIsFileInAllowedUuids:
    """Tests for is_file_in_allowed_uuids function."""

    def test_allowed_uuid_returns_true(self):
        """File with allowed UUID returns True."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        allowed = {uuid}
        assert is_file_in_allowed_uuids(f"{uuid}.metadata", allowed) is True

    def test_disallowed_uuid_returns_false(self):
        """File with non-allowed UUID returns False."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        other = "xyz12345-1234-1234-1234-123456789012"
        allowed = {other}
        assert is_file_in_allowed_uuids(f"{uuid}.metadata", allowed) is False

    def test_non_uuid_file_returns_true(self):
        """Non-UUID files (version, etc.) always return True."""
        allowed = set()  # No UUIDs allowed
        assert is_file_in_allowed_uuids("version", allowed) is True

    def test_empty_allowed_with_uuid_file(self):
        """Empty allowed set rejects UUID files."""
        uuid = "abc12345-1234-1234-1234-123456789012"
        assert is_file_in_allowed_uuids(f"{uuid}.metadata", set()) is False
