import pytest

from agentops_mcp_server import init as init_mod


def test_script_path_uses_package_resources(monkeypatch, tmp_path):
    script = tmp_path / "zed-agentops-init.sh"

    class DummyFiles:
        def __init__(self, base):
            self._base = base

        def joinpath(self, name):
            return self._base / name

    monkeypatch.setattr(init_mod.resources, "files", lambda _: DummyFiles(tmp_path))
    assert init_mod._script_path() == str(script)


def test_script_path_raises_when_resources_missing(monkeypatch):
    def boom(_):
        raise Exception("nope")

    monkeypatch.setattr(init_mod.resources, "files", boom)
    with pytest.raises(RuntimeError, match="zed-agentops-init.sh is not packaged"):
        init_mod._script_path()


def test_main_raises_when_script_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(init_mod, "_script_path", lambda: str(tmp_path / "missing.sh"))
    monkeypatch.setattr(init_mod.os.path, "exists", lambda _: False)
    with pytest.raises(FileNotFoundError):
        init_mod.main()


def test_main_execv(monkeypatch, tmp_path):
    script = tmp_path / "zed-agentops-init.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    monkeypatch.setattr(init_mod, "_script_path", lambda: str(script))
    monkeypatch.setattr(init_mod.os.path, "exists", lambda _: True)

    called = {}

    def fake_execv(path, args):
        called["path"] = path
        called["args"] = args

    monkeypatch.setattr(init_mod.os, "execv", fake_execv)
    monkeypatch.setattr(init_mod.sys, "argv", ["init.py", "--flag"])

    init_mod.main()

    assert called["path"] == "/usr/bin/env"
    assert called["args"] == ["env", "bash", str(script), "--flag"]
