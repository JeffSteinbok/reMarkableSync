"""Tests for the read-only reMarkable Cloud connection adapter."""

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from src.backup.cloud_connection import ReMarkableCloudConnection


class FakeClient:
    def __init__(self):
        self.folder = SimpleNamespace(
            id="folder-uuid",
            hash="folder-hash",
            type="CollectionType",
            visibleName="Work",
            parent="",
            lastModified="1720000000000",
        )
        self.document = SimpleNamespace(
            id="11111111-2222-3333-4444-555555555555",
            hash="document-hash",
            type="DocumentType",
            visibleName="Meeting Notes",
            parent="folder-uuid",
            lastModified="1720000000000",
        )
        self.files = {
            self.folder.id: {
                "folder-uuid.metadata": json.dumps(
                    {
                        "type": "CollectionType",
                        "visibleName": "Work",
                        "parent": "",
                    }
                ).encode(),
                "folder-uuid.content": b'{"tags": []}',
            },
            self.document.id: {
                f"{self.document.id}.metadata": json.dumps(
                    {
                        "type": "DocumentType",
                        "visibleName": "Meeting Notes",
                        "parent": "folder-uuid",
                    }
                ).encode(),
                f"{self.document.id}.content": b'{"fileType": "notebook"}',
                f"{self.document.id}/page-1.rm": b"raw strokes",
            },
        }
        self.closed = False

    def list_hydrated_items(self, refresh=False):
        assert refresh is True
        return [self.folder, self.document]

    def get_entries(self, item_hash, manifest_id=None):
        del item_hash
        entries = [
            SimpleNamespace(id=name, size=len(data))
            for name, data in self.files[manifest_id].items()
        ]
        return SimpleNamespace(entries=entries)

    def get_document(self, item_id):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in self.files[item_id].items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def close(self):
        self.closed = True


def test_cloud_connection_exposes_tablet_compatible_paths(tmp_path):
    client = FakeClient()
    connection = ReMarkableCloudConnection(client=client)

    assert connection.connect() is True
    files = connection.list_files("/home/root/.local/share/remarkable/xochitl")
    paths = {file["path"] for file in files}

    assert any(path.endswith("folder-uuid.metadata") for path in paths)
    assert any(path.endswith("11111111-2222-3333-4444-555555555555.content") for path in paths)
    assert any(path.endswith("11111111-2222-3333-4444-555555555555/page-1.rm") for path in paths)

    destination = tmp_path / "page.rm"
    page_path = next(path for path in paths if path.endswith("/page-1.rm"))
    connection.get(page_path, str(destination))
    assert destination.read_bytes() == b"raw strokes"


def test_cloud_connection_supports_folder_metadata_scan():
    connection = ReMarkableCloudConnection(client=FakeClient())
    connection.connect()

    stdout, stderr, exit_code = connection.execute_command(
        'for f in /home/root/.local/share/remarkable/xochitl/*.metadata; do cat "$f"; done'
    )

    assert exit_code == 0
    assert stderr == ""
    assert "FILE:folder-uuid" in stdout
    assert '"visibleName": "Work"' in stdout


def test_cloud_connection_does_not_expose_system_templates():
    connection = ReMarkableCloudConnection(client=FakeClient())
    connection.connect()

    assert connection.list_files("/usr/share/remarkable/templates") == []


def test_cloud_connection_missing_file_does_not_touch_destination(tmp_path):
    connection = ReMarkableCloudConnection(client=FakeClient())
    connection.connect()
    destination = tmp_path / "existing.metadata"
    destination.write_text("keep")

    with pytest.raises(FileNotFoundError):
        connection.get(
            "/home/root/.local/share/remarkable/xochitl/missing.metadata",
            str(destination),
        )

    assert destination.read_text() == "keep"
