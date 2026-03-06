import subprocess
from types import SimpleNamespace

from agentops_mcp_server.verify_runner import VerifyRunner


def _write_verify_script(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    path.chmod(0o755)


def test_run_verify_timeout_returns_error(repo_context, state_store, monkeypatch):
    _write_verify_script(repo_context.verify)
    runner = VerifyRunner(repo_context, state_store)

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=[str(repo_context.verify)], timeout=3, output="out"
        )

    monkeypatch.setattr(subprocess, "run", boom)

    result = runner.run_verify(timeout_sec=3)
    assert result["ok"] is False
    assert "timed out" in result["stderr"]


def test_run_verify_success_records_journal(repo_context, state_store, monkeypatch):
    _write_verify_script(repo_context.verify)
    runner = VerifyRunner(repo_context, state_store)

    def ok_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", ok_run)

    result = runner.run_verify(timeout_sec=3)
    assert result["ok"] is True
