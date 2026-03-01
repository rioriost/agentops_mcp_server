# T-001 旧handoff/WIP/session_log利用箇所インベントリ

## 目的
旧来の `handoff` / `WIP` / `session_log` に関する参照・更新箇所を特定し、撤去対象の全体像を整理する。

## コード参照（実装）
- `src/agentops_mcp_server/main.py`
  - `.agent/handoff.md` と `.agent/session-log.jsonl` のパスを固定で参照・更新する処理が存在。
  - `handoff_read` / `handoff_update` / `handoff_normalize` 系の関数群が `.agent/handoff.md` を読み書き。
  - `log_append` / `session_log_append` が `.agent/session-log.jsonl` を追記。
  - `TOOL_REGISTRY` と `alias_map` で `handoff_*` / `session_log_append` / `log_append` のツール公開が定義。
  - `session_checkpoint` が `.agent/checkpoints/` にJSONスナップショットを書き込み（旧運用関連）。

## スクリプト/スキャフォールド
- `src/agentops_mcp_server/zed-agentops-init.sh`
  - `HANDOFF_REL=.agent/handoff.md` を定義。
  - 初期 `handoff.md` を生成（テンプレート書き込み）。
  - 初期 `work-in-progress.json` を生成（テンプレート書き込み）。
  - `.rules` テンプレート内で handoff/WIP の運用ルールを明示。

## ドキュメント/設定
- `.rules`
  - `${HANDOFF_REL}` を読む/更新するルールを明記。
  - `.agent/work-in-progress.json` 更新ルールを明記。
- `README.md`
  - `.agent/handoff.md` / `.agent/work-in-progress.json` / `.agent/session-log.jsonl` の配置と用途を説明。
- `README-jp.md`
  - 上記と同様に handoff/WIP/session-log を説明。
- `plan.txt`
  - `.agent/handoff.md` の利用を前提にした説明が含まれる。

## データファイル（実体）
- `.agent/handoff.md`
- `.agent/work-in-progress.json`
- `.agent/session-log.jsonl`

## 撤去対象まとめ（T-001結論）
- 実装: `main.py` の handoff / session_log 系関数とツール公開。
- スクリプト: `zed-agentops-init.sh` の handoff/WIP 初期化部分。
- ドキュメント: `.rules`, `README.md`, `README-jp.md`, `plan.txt` の handoff/WIP/session-log 記述。
- データファイル: `.agent/handoff.md`, `.agent/work-in-progress.json`, `.agent/session-log.jsonl`。