# T-002 legacy tracking removal candidates (main.py)

## 目的
`main.py` 内の旧 tracking（handoff / session_log / checkpoints）関連の削除・置換対象を特定する。

## 入力
- `ticket_T-001_inventory.md`

## 対象ファイル
- `src/agentops_mcp_server/main.py`

---

## 削除・置換候補（関数・定義単位）

### 1) 旧ファイルパスのグローバル定義
- `_set_repo_root()` 内の以下
  - `HANDOFF = REPO_ROOT / ".agent" / "handoff.md"`
  - `SESSION_LOG = REPO_ROOT / ".agent" / "session-log.jsonl"`
  - `CHECKPOINTS_DIR = REPO_ROOT / ".agent" / "checkpoints"`
- 置換先: `journal.jsonl` / `snapshot.json` / `checkpoint.json` の新I/O管理へ差し替え。

### 2) handoff.md 読み書き系
- `_parse_handoff_sections()`
- `_render_handoff()`
- `_default_handoff_template()`
- `_event_section()` / `_upsert_event_section()` / `_deterministic_handoff()`
- `handoff_update()` / `handoff_read()` / `handoff_update_structured()` / `handoff_normalize()`
- 旧 `handoff.md` を前提とするため、廃止 or 新スナップショット機構へ置換対象。

### 3) session-log 追記系
- `log_append()`
- `session_log_append()`
- `session_capture_context()` の `log_append("session_capture", ...)`
- 旧 `.agent/session-log.jsonl` を前提とするため、`journal.jsonl` へのイベント記録へ統合予定。

### 4) checkpoints ベースの差分記録
- `session_checkpoint()` / `session_diff_since_checkpoint()`
- `.agent/checkpoints/` JSON スナップショットを使う旧設計。
- v0.1.0 では `snapshot.json` / `checkpoint.json` を使うため廃止 or 再設計対象。

### 5) ツール公開・互換マッピング
- `TOOL_REGISTRY` 内の以下
  - `handoff_read`, `handoff_update`, `handoff_normalize`
  - `log_append`, `session_log_append`
  - `session_checkpoint`, `session_diff_since_checkpoint`
- `tools_call()` の `alias_map` 内
  - `handoff.read`, `handoff.update`, `handoff.normalize`
  - `session.log_append`, `session.checkpoint`, `session.diff_since_checkpoint`
- 旧ツールの削除・新ツール（journal/snapshot/checkpoint）へ差し替え対象。

---

## 備考（置換の方向性）
- handoff/WIP/session_log を廃止し、`journal.jsonl` + `snapshot.json` + `checkpoint.json` へ統合。
- `session_capture_context` のログ出力は、`journal.jsonl` へのイベント記録に置き換える想定。

---

## 次アクション
- T-009 で実際の削除・置換を実施。
- T-003/4/5 で新I/O層が入った後、ここで列挙した旧関数・ツールを整理する。