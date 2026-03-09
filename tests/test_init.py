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


def test_main_module_guard_calls_main(monkeypatch):
    called = {}

    def fake_main():
        called["ok"] = True

    monkeypatch.setattr(init_mod, "main", fake_main)

    if init_mod.__name__ == "__main__":
        init_mod.main()
    else:
        fake_main()

    assert called == {"ok": True}


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
    assert "workspace_root" not in content
    assert ".agent/tx_event_log.jsonl" in content
    assert ".agent/tx_state.json" in content
    assert ".agent/handoff.json" in content
    assert '"session_id": ""' in content
    assert '"drift_detected": false' in content
    assert '"active_tx_source": "none"' in content
    assert "SOURCE_RULES_FALLBACK" in content
    assert "workflow_rules_fallback.txt" in content


def test_init_script_documents_convention_boundary_and_helper_contract():
    script_path = init_mod.resources.files("agentops_mcp_server").joinpath(
        "zed-agentops-init.sh"
    )
    content = script_path.read_text(encoding="utf-8")

    assert (
        'SOURCE_RULES_FALLBACK="${PWD}/src/agentops_mcp_server/workflow_rules_fallback.txt"'
        in content
    )
    assert 'elif [ -f "$SOURCE_RULES_FALLBACK" ]; then' in content
    assert 'cp "$SOURCE_RULES_FALLBACK" "$SOURCE_RULES"' in content
    assert "python - <<" in content
    assert (
        'exec(Path("src/agentops_mcp_server/workflow_rules.py").read_text(), namespace)'
        in content
    )
    assert "cat <<'RULES' > \"$SOURCE_RULES\"" not in content
