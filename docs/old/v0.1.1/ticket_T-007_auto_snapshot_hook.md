# T-007 Post-Commit Snapshot/Checkpoint Hook Plan

## Goal
`commit` 成功後に自動で `snapshot.json` と `checkpoint.json` を更新し、次回の `continue` 再開に必要な状態を確実に保存する。

## Scope
- 対象: `src/agentops_mcp_server/main.py`
- 対象関数: `commit_if_verified`, `repo_commit`
- 期待動作: **commit が成功したときのみ**自動保存を行う
- 失敗時の扱い: **commit 結果を壊さずに警告として扱う**

## Current State
- `snapshot_save` / `checkpoint_update` は **明示的に呼ばれた時のみ**実行される。
- `commit_if_verified` / `repo_commit` は `commit.start/end` を journal に書き込むが、snapshot/checkpoint は更新しない。

## Proposed Behavior
### Hook Placement
- `commit_if_verified` と `repo_commit` の **commit 成功直後**に新しい補助関数を呼び出す。
- 例: `commit.end` を journal に記録した直後に呼ぶ。

### New Helper (proposal)
`_auto_snapshot_checkpoint_after_commit()` を追加し、以下を実行。

#### Algorithm
1. **既存 snapshot / checkpoint を読み取る（存在すれば）**
   - `snapshot.json` があれば `state` と `last_applied_seq` を取得
2. **最新 journal seq を把握する**
   - `_read_journal_events(start_seq=last_applied_seq or 0)` を使用
   - `last_seq` を取得（これが新しい `last_applied_seq`）
3. **state 再構築**
   - `replay_events_to_state(snapshot_state, events, preferred_session_id)` を使用
   - `preferred_session_id` は `snapshot.json` 内の `session_id` を優先
4. **snapshot 保存**
   - `snapshot_save(state, session_id, last_applied_seq=last_seq)`
5. **checkpoint 更新**
   - `checkpoint_update(last_applied_seq=last_seq, snapshot_path="snapshot.json")`

#### Edge Cases
- `journal.jsonl` が存在しない場合:
  - no-op（更新なし）
- `snapshot.json` が存在しない場合:
  - `state` を空から構築して保存（`last_applied_seq` は journal の `last_seq`）
- `replay` が失敗した場合:
  - 例外は捕捉し、**commit の成功を維持**する（警告ログのみ）

## Error Handling / Observability
- `_auto_snapshot_checkpoint_after_commit()` 内で例外を捕捉し、
  - `_journal_safe("error", ...)` 等で記録する（必須ではないが推奨）
  - commit 成功結果は維持
- 失敗時は `return {"ok": False, "reason": ...}` の形で呼び出し側に情報返却するのが望ましい

## Acceptance Criteria
- commit 成功時に `snapshot.json` と `checkpoint.json` が自動更新される
- `last_applied_seq` が journal の最新 seq と一致する
- 失敗時も commit 自体は成功として扱われる
- `commit_if_verified` / `repo_commit` 双方で同一の挙動になる

## Future Notes
- `session_id` の選択は `snapshot.json` の `session_id` を優先し、無い場合は最新 `session.start` を使う。
- もし複数セッションを並列に扱う場合、session 切替えルールを再検討する必要がある。