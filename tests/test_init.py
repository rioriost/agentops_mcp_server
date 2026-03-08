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


def test_init_script_contains_canonical_artifacts_and_rules():
    script_path = init_mod.resources.files("agentops_mcp_server").joinpath(
        "zed-agentops-init.sh"
    )
    content = script_path.read_text(encoding="utf-8")

    assert ".agent/tx_event_log.jsonl" in content
    assert ".agent/tx_state.json" in content
    assert ".agent/handoff.json" in content
    assert ".agent/observability_summary.json" in content
    assert "journal.jsonl" not in content
    assert 'touch "$AGENT_DIR/journal.jsonl"' not in content
    assert "Skipping .agent/journal.jsonl" not in content
    assert "handoff.md" not in content

    assert "work-in-progress.md" not in content
    assert "Treat `.agent/handoff.json` as derived-only" in content
    assert "workspace_root" not in content
    assert "- `tx.begin` before task lifecycle events" in content
    assert "- task lifecycle tools" in content
    assert "- do not call task start/update/end before `tx.begin`" in content
    assert "- semantic_summary is required for non-terminal tx" in content
    assert "- Identify active ticket (status != done) and resume it." in content
    assert "active_tx.next_action is required" not in content
    assert (
        "- Ticket status persistence is mandatory throughout execution, not optional bookkeeping."
        in content
    )
    assert "- Every ticket status change must be persisted to both:" in content
    assert "- the per-ticket JSON file, and" in content
    assert "- docs/__version__/tickets_list.json." in content
    assert (
        "- The per-ticket JSON file and docs/__version__/tickets_list.json must stay synchronized with each other for the same ticket."
        in content
    )
    assert (
        "- Runtime transaction status/phase and persisted ticket-document status must stay synchronized at each ticket lifecycle transition and must not be reconciled later as optional follow-up bookkeeping."
        in content
    )
    assert (
        "- Persist the matching ticket status to both the per-ticket JSON file and docs/__version__/tickets_list.json when work begins."
        in content
    )
    assert (
        "- Persist the terminal ticket status to both the per-ticket JSON file and docs/__version__/tickets_list.json."
        in content
    )
