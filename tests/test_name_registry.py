"""Tests for name_registry module."""

import json

from src.utils.name_registry import NameRegistry


class TestNameRegistryInit:
    """Tests for NameRegistry initialization."""

    def test_creates_empty_registry_when_file_missing(self, tmp_path):
        """Registry starts empty when no file exists."""
        registry = NameRegistry(tmp_path)
        assert registry.get("any-uuid") is None

    def test_loads_existing_registry_file(self, tmp_path):
        """Registry loads data from existing file."""
        data = {
            "uuid-1": {
                "raw_name": "My Notebook",
                "sanitized_name": "My Notebook",
                "parent_uuid": "",
            }
        }
        (tmp_path / "name_registry.json").write_text(json.dumps(data))

        registry = NameRegistry(tmp_path)
        assert registry.get("uuid-1") == "My Notebook"

    def test_handles_corrupt_json_gracefully(self, tmp_path):
        """Registry handles corrupt JSON by starting empty."""
        (tmp_path / "name_registry.json").write_text("not valid json {{{")

        registry = NameRegistry(tmp_path)
        assert registry.get("any-uuid") is None

    def test_builds_used_names_index_on_load(self, tmp_path):
        """Registry builds index of used names per parent."""
        data = {
            "uuid-1": {
                "raw_name": "Notes",
                "sanitized_name": "Notes",
                "parent_uuid": "folder-1",
            },
            "uuid-2": {
                "raw_name": "Notes",
                "sanitized_name": "Notes (1)",
                "parent_uuid": "folder-1",
            },
        }
        (tmp_path / "name_registry.json").write_text(json.dumps(data))

        registry = NameRegistry(tmp_path)
        # Both names should be marked as used under folder-1
        # Adding another "Notes" should get "(2)"
        result = registry.get_or_assign("uuid-3", "Notes", "folder-1")
        assert result == "Notes (2)"


class TestGetOrAssign:
    """Tests for get_or_assign method."""

    def test_assigns_sanitized_name_for_new_uuid(self, tmp_path):
        """New UUID gets a sanitized name."""
        registry = NameRegistry(tmp_path)
        result = registry.get_or_assign("uuid-1", "My Notebook", "")
        assert result == "My Notebook"

    def test_returns_same_name_for_unchanged_raw_name(self, tmp_path):
        """Same raw name returns the same sanitized name."""
        registry = NameRegistry(tmp_path)
        first = registry.get_or_assign("uuid-1", "My Notebook", "")
        second = registry.get_or_assign("uuid-1", "My Notebook", "")
        assert first == second == "My Notebook"

    def test_assigns_new_name_when_raw_name_changes(self, tmp_path):
        """Changed raw name gets a new sanitized name."""
        registry = NameRegistry(tmp_path)
        first = registry.get_or_assign("uuid-1", "Old Name", "")
        second = registry.get_or_assign("uuid-1", "New Name", "")
        assert first == "Old Name"
        assert second == "New Name"

    def test_adds_suffix_for_collisions_in_same_parent(self, tmp_path):
        """Colliding names in same parent get numbered suffixes."""
        registry = NameRegistry(tmp_path)
        first = registry.get_or_assign("uuid-1", "Notes", "folder-1")
        second = registry.get_or_assign("uuid-2", "Notes", "folder-1")
        third = registry.get_or_assign("uuid-3", "Notes", "folder-1")

        assert first == "Notes"
        assert second == "Notes (1)"
        assert third == "Notes (2)"

    def test_no_collision_in_different_parents(self, tmp_path):
        """Same name in different parents doesn't collide."""
        registry = NameRegistry(tmp_path)
        first = registry.get_or_assign("uuid-1", "Notes", "folder-1")
        second = registry.get_or_assign("uuid-2", "Notes", "folder-2")

        assert first == "Notes"
        assert second == "Notes"  # No suffix needed

    def test_sanitizes_special_characters(self, tmp_path):
        """Names with special characters are sanitized."""
        registry = NameRegistry(tmp_path)
        result = registry.get_or_assign("uuid-1", "My/Notebook:Test", "")
        # sanitize_name replaces / and : with safe chars
        assert "/" not in result
        assert ":" not in result

    def test_handles_empty_raw_name(self, tmp_path):
        """Empty raw name gets fallback based on UUID."""
        registry = NameRegistry(tmp_path)
        result = registry.get_or_assign("abcd1234-5678", "", "")
        assert result.startswith("item-")
        assert "abcd1234" in result

    def test_releases_old_name_on_rename(self, tmp_path):
        """When UUID is renamed, old name becomes available."""
        registry = NameRegistry(tmp_path)

        # uuid-1 takes "Notes"
        registry.get_or_assign("uuid-1", "Notes", "")
        # uuid-2 takes "Notes (1)"
        registry.get_or_assign("uuid-2", "Notes", "")

        # uuid-1 renames to something else, releasing "Notes"
        registry.get_or_assign("uuid-1", "My Notes", "")

        # uuid-3 should now get "Notes" (not "Notes (2)")
        result = registry.get_or_assign("uuid-3", "Notes", "")
        assert result == "Notes"


class TestSave:
    """Tests for save method."""

    def test_saves_registry_to_file(self, tmp_path):
        """Registry data is persisted to JSON file."""
        registry = NameRegistry(tmp_path)
        registry.get_or_assign("uuid-1", "My Notebook", "parent-1")
        registry.save()

        saved = json.loads((tmp_path / "name_registry.json").read_text())
        assert "uuid-1" in saved
        assert saved["uuid-1"]["raw_name"] == "My Notebook"
        assert saved["uuid-1"]["sanitized_name"] == "My Notebook"
        assert saved["uuid-1"]["parent_uuid"] == "parent-1"

    def test_saved_data_survives_reload(self, tmp_path):
        """Data survives save/reload cycle."""
        registry1 = NameRegistry(tmp_path)
        registry1.get_or_assign("uuid-1", "Test", "")
        registry1.get_or_assign("uuid-2", "Test", "")  # Gets "Test (1)"
        registry1.save()

        registry2 = NameRegistry(tmp_path)
        assert registry2.get("uuid-1") == "Test"
        assert registry2.get("uuid-2") == "Test (1)"


class TestGet:
    """Tests for get method."""

    def test_returns_none_for_unknown_uuid(self, tmp_path):
        """Unknown UUID returns None."""
        registry = NameRegistry(tmp_path)
        assert registry.get("unknown-uuid") is None

    def test_returns_sanitized_name_for_known_uuid(self, tmp_path):
        """Known UUID returns its sanitized name."""
        registry = NameRegistry(tmp_path)
        registry.get_or_assign("uuid-1", "My Notebook", "")
        assert registry.get("uuid-1") == "My Notebook"
