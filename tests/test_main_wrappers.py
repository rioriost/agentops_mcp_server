import agentops_mcp_server.main as main


def test_main_wrapper_delegates(monkeypatch):
    calls = {}

    class DummyRepoContext:
        def resolve_workspace_root(self, value):
            calls["resolve_workspace_root"] = value
            return f"resolved:{value}"

    class DummyStore:
        def journal_append(self, **kwargs):
            calls["journal_append"] = kwargs
            return {"journal": kwargs}

        def snapshot_save(self, **kwargs):
            calls["snapshot_save"] = kwargs
            return {"snapshot_save": kwargs}

        def snapshot_load(self):
            return {"snapshot_load": True}

        def checkpoint_update(self, **kwargs):
            calls["checkpoint_update"] = kwargs
            return {"checkpoint_update": kwargs}

        def checkpoint_read(self):
            return {"checkpoint_read": True}

    class DummyRebuilder:
        def roll_forward_replay(self, **kwargs):
            return {"roll_forward_replay": kwargs}

        def continue_state_rebuild(self, **kwargs):
            return {"continue_state_rebuild": kwargs}

    class DummyVerifyRunner:
        def run_verify(self, timeout_sec=None):
            return {"verify": timeout_sec}

    class DummyCommitManager:
        def commit_if_verified(self, message, timeout_sec=None):
            return {"commit_if_verified": message, "timeout_sec": timeout_sec}

        def repo_commit(self, **kwargs):
            return {"repo_commit": kwargs}

    class DummyRepoTools:
        def repo_verify(self, timeout_sec=None):
            return {"repo_verify": timeout_sec}

        def repo_status_summary(self):
            return {"repo_status_summary": True}

        def repo_commit_message_suggest(self, diff=None):
            return {"repo_commit_message_suggest": diff}

        def session_capture_context(self, run_verify=False, log=False):
            return {"run_verify": run_verify, "log": log}

    class DummyTestSuggester:
        def tests_suggest(self, diff=None, failures=None):
            return {"diff": diff, "failures": failures}

        def tests_suggest_from_failures(self, log_path):
            return {"log_path": log_path}

    class DummyOpsTools:
        def ops_compact_context(self, max_chars=None, include_diff=None):
            return {"ops_compact_context": (max_chars, include_diff)}

        def ops_handoff_export(self):
            return {"ops_handoff_export": True}

        def ops_resume_brief(self, max_chars=None):
            return {"ops_resume_brief": max_chars}

        def ops_start_task(self, **kwargs):
            return {"ops_start_task": kwargs}

        def ops_update_task(self, **kwargs):
            return {"ops_update_task": kwargs}

        def ops_end_task(self, **kwargs):
            return {"ops_end_task": kwargs}

        def ops_capture_state(self, session_id=None):
            return {"ops_capture_state": session_id}

        def ops_task_summary(self, session_id=None, max_chars=None):
            return {"ops_task_summary": (session_id, max_chars)}

        def ops_observability_summary(self, **kwargs):
            return {"ops_observability_summary": kwargs}

    class DummyToolRouter:
        def tools_list(self):
            return {"tools": ["ok"]}

        def tools_call(self, name, arguments):
            return {"tool": name, "args": arguments}

    class DummyRpc:
        def __init__(self):
            self.ran = False

        def handle_request(self, req):
            return {"req": req}

        def run(self):
            self.ran = True

    dummy_rpc = DummyRpc()

    monkeypatch.setattr(main, "_REPO_CONTEXT", DummyRepoContext())
    monkeypatch.setattr(main, "_STATE_STORE", DummyStore())
    monkeypatch.setattr(main, "_STATE_REBUILDER", DummyRebuilder())
    monkeypatch.setattr(main, "_VERIFY_RUNNER", DummyVerifyRunner())
    monkeypatch.setattr(main, "_COMMIT_MANAGER", DummyCommitManager())
    monkeypatch.setattr(main, "_REPO_TOOLS", DummyRepoTools())
    monkeypatch.setattr(main, "_TEST_SUGGESTER", DummyTestSuggester())
    monkeypatch.setattr(main, "_OPS_TOOLS", DummyOpsTools())
    monkeypatch.setattr(main, "_TOOL_ROUTER", DummyToolRouter())
    monkeypatch.setattr(main, "_RPC_SERVER", dummy_rpc)

    assert main._resolve_workspace_root("root") == "resolved:root"
    assert calls["resolve_workspace_root"] == "root"

    assert (
        main.journal_append("kind", {"a": 1}, "s", "a", "e")["journal"]["kind"]
        == "kind"
    )
    assert main.snapshot_save({"state": 1}, "s1", 1, "snap")["snapshot_save"][
        "state"
    ] == {"state": 1}
    assert main.snapshot_load()["snapshot_load"] is True
    assert (
        main.checkpoint_update(1, "snap.json", "cp")["checkpoint_update"][
            "last_applied_seq"
        ]
        == 1
    )
    assert main.checkpoint_read()["checkpoint_read"] is True
    assert (
        main.roll_forward_replay(start_seq=1)["roll_forward_replay"]["start_seq"] == 1
    )
    assert (
        main.continue_state_rebuild(session_id="s1")["continue_state_rebuild"][
            "session_id"
        ]
        == "s1"
    )
    assert main.run_verify(timeout_sec=3)["verify"] == 3
    assert main.commit_if_verified("msg", timeout_sec=2)["commit_if_verified"] == "msg"
    assert main.repo_commit(message="m")["repo_commit"]["message"] == "m"
    assert main.repo_verify(timeout_sec=5)["repo_verify"] == 5
    assert main.repo_status_summary()["repo_status_summary"] is True
    assert (
        main.repo_commit_message_suggest(diff="d")["repo_commit_message_suggest"] == "d"
    )
    assert main.session_capture_context(run_verify=True, log=True)["run_verify"] is True
    assert main.tests_suggest(diff="d", failures="f")["failures"] == "f"
    assert main.tests_suggest_from_failures("log.txt")["log_path"] == "log.txt"
    assert main.ops_compact_context(10, True)["ops_compact_context"] == (10, True)
    assert main.ops_handoff_export()["ops_handoff_export"] is True
    assert main.ops_resume_brief(20)["ops_resume_brief"] == 20
    assert main.ops_start_task(title="t")["ops_start_task"]["title"] == "t"
    assert main.ops_update_task(status="s")["ops_update_task"]["status"] == "s"
    assert main.ops_end_task(summary="done")["ops_end_task"]["summary"] == "done"
    assert main.ops_capture_state("s1")["ops_capture_state"] == "s1"
    assert main.ops_task_summary("s1", 5)["ops_task_summary"] == ("s1", 5)
    assert (
        main.ops_observability_summary(session_id="s1")["ops_observability_summary"][
            "session_id"
        ]
        == "s1"
    )
    assert main.tools_list()["tools"] == ["ok"]
    assert main.tools_call("tool", {"a": 1})["tool"] == "tool"
    assert main.handle_request({"id": 1})["req"]["id"] == 1

    main.main()
    assert dummy_rpc.ran is True
