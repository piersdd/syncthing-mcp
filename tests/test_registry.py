"""Tests for instance registry loading and resolution."""

import json
import os

import pytest

from syncthing_mcp.client import SyncthingClient
from syncthing_mcp.registry import (
    format_bytes,
    get_instance,
    handle_error_global,
    load_instances,
    reload_instances,
)


class TestFormatBytes:
    def test_zero(self):
        assert format_bytes(0) == "0.0 B"

    def test_bytes(self):
        assert format_bytes(512) == "512.0 B"

    def test_kilobytes(self):
        assert format_bytes(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_bytes(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert format_bytes(3 * 1024**3) == "3.0 GB"

    def test_terabytes(self):
        assert format_bytes(2 * 1024**4) == "2.0 TB"


class TestLoadInstances:
    def test_single_instance_defaults(self, monkeypatch):
        monkeypatch.delenv("SYNCTHING_INSTANCES", raising=False)
        monkeypatch.setenv("SYNCTHING_API_KEY", "mykey")
        monkeypatch.delenv("SYNCTHING_URL", raising=False)
        instances = load_instances()
        assert "default" in instances
        assert instances["default"].url == "http://localhost:8384"
        assert instances["default"].api_key == "mykey"

    def test_single_instance_custom_url(self, monkeypatch):
        monkeypatch.delenv("SYNCTHING_INSTANCES", raising=False)
        monkeypatch.setenv("SYNCTHING_API_KEY", "mykey")
        monkeypatch.setenv("SYNCTHING_URL", "http://nas.local:8384")
        instances = load_instances()
        assert instances["default"].url == "http://nas.local:8384"

    def test_multi_instance(self, monkeypatch):
        cfg = {
            "alpha": {"url": "http://a:8384", "api_key": "ka"},
            "beta": {"url": "http://b:8384", "api_key": "kb"},
        }
        monkeypatch.setenv("SYNCTHING_INSTANCES", json.dumps(cfg))
        instances = load_instances()
        assert len(instances) == 2
        assert instances["alpha"].url == "http://a:8384"
        assert instances["beta"].api_key == "kb"

    def test_invalid_json(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_INSTANCES", "{bad json")
        with pytest.raises(ValueError, match="Invalid SYNCTHING_INSTANCES JSON"):
            load_instances()

    def test_empty_object(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_INSTANCES", "{}")
        with pytest.raises(ValueError, match="non-empty"):
            load_instances()

    def test_non_dict_entry(self, monkeypatch):
        monkeypatch.setenv("SYNCTHING_INSTANCES", json.dumps({"a": "not a dict"}))
        with pytest.raises(ValueError, match="must be a JSON object"):
            load_instances()

    def test_url_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.delenv("SYNCTHING_INSTANCES", raising=False)
        monkeypatch.setenv("SYNCTHING_API_KEY", "k")
        monkeypatch.setenv("SYNCTHING_URL", "http://localhost:8384/")
        instances = load_instances()
        assert instances["default"].url == "http://localhost:8384"


class TestGetInstance:
    def test_auto_select_single(self, monkeypatch, single_instance_env):
        reload_instances()
        inst = get_instance(None)
        assert inst.name == "default"

    def test_explicit_name(self, monkeypatch, multi_instance_env):
        reload_instances()
        inst = get_instance("alpha")
        assert inst.name == "alpha"

    def test_missing_name(self, monkeypatch, multi_instance_env):
        reload_instances()
        with pytest.raises(ValueError, match="not found"):
            get_instance("nonexistent")

    def test_ambiguous_without_name(self, monkeypatch, multi_instance_env):
        reload_instances()
        with pytest.raises(ValueError, match="Multiple instances"):
            get_instance(None)


class TestHandleErrorGlobal:
    def test_value_error(self):
        msg = handle_error_global(ValueError("bad input"))
        assert msg == "Error: bad input"

    def test_generic_error(self):
        msg = handle_error_global(RuntimeError("boom"))
        assert "RuntimeError" in msg
        assert "boom" in msg
