"""Tests for Pydantic input model validation."""

import pytest
from pydantic import ValidationError

from syncthing_mcp.models import (
    BrowseFolderInput,
    DeviceInput,
    EmptyInput,
    FileInfoInput,
    FolderInput,
    FolderNeedInput,
    PauseFolderInput,
    SetIgnoresInput,
)


class TestEmptyInput:
    def test_no_args(self):
        m = EmptyInput()
        assert m.instance is None

    def test_with_instance(self):
        m = EmptyInput(instance="mynas")
        assert m.instance == "mynas"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            EmptyInput(instance="a", extra="bad")


class TestFolderInput:
    def test_valid(self):
        m = FolderInput(folder_id="abc-123")
        assert m.folder_id == "abc-123"

    def test_empty_folder_id(self):
        with pytest.raises(ValidationError):
            FolderInput(folder_id="")

    def test_whitespace_stripped(self):
        m = FolderInput(folder_id="  abc  ")
        assert m.folder_id == "abc"


class TestDeviceInput:
    def test_valid(self):
        m = DeviceInput(device_id="ABCDEF-123456")
        assert m.device_id == "ABCDEF-123456"

    def test_empty_device_id(self):
        with pytest.raises(ValidationError):
            DeviceInput(device_id="")


class TestPauseFolderInput:
    def test_valid(self):
        m = PauseFolderInput(folder_id="f1")
        assert m.folder_id == "f1"


class TestSetIgnoresInput:
    def test_valid(self):
        m = SetIgnoresInput(folder_id="f1", patterns=["*.tmp", ".DS_Store"])
        assert len(m.patterns) == 2


class TestBrowseFolderInput:
    def test_defaults(self):
        m = BrowseFolderInput(folder_id="f1")
        assert m.prefix is None
        assert m.levels is None

    def test_with_prefix(self):
        m = BrowseFolderInput(folder_id="f1", prefix="docs/reports", levels=2)
        assert m.prefix == "docs/reports"
        assert m.levels == 2

    def test_negative_levels(self):
        with pytest.raises(ValidationError):
            BrowseFolderInput(folder_id="f1", levels=-1)


class TestFileInfoInput:
    def test_valid(self):
        m = FileInfoInput(folder_id="f1", file_path="docs/readme.md")
        assert m.file_path == "docs/readme.md"

    def test_empty_file_path(self):
        with pytest.raises(ValidationError):
            FileInfoInput(folder_id="f1", file_path="")


class TestFolderNeedInput:
    def test_defaults(self):
        m = FolderNeedInput(folder_id="f1")
        assert m.page == 1
        assert m.per_page == 50

    def test_custom_pagination(self):
        m = FolderNeedInput(folder_id="f1", page=3, per_page=100)
        assert m.page == 3
        assert m.per_page == 100

    def test_page_must_be_positive(self):
        with pytest.raises(ValidationError):
            FolderNeedInput(folder_id="f1", page=0)

    def test_per_page_max(self):
        with pytest.raises(ValidationError):
            FolderNeedInput(folder_id="f1", per_page=501)
