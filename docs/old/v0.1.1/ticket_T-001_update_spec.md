# T-001 Update Mode Specification (--update)

## Goal
既存の `agentops_mcp_server` 管理ディレクトリを **最新の管理形式に安全に移行**するため、`zed-agentops-init.sh --update` の動作仕様を定義する。

## Scope
- 対象スクリプト: `src/agentops_mcp_server/zed-agentops-init.sh`
- 対象ディレクトリ: 既存の AgentOps 管理プロジェクト
- 実行内容:
  - legacy ファイル削除
  - `.agent/` 内の新しい状態ファイル作成
  - `.rules` の更新
- **破壊的操作は最小限**で、再実行可能（idempotent）にする

## CLI / Usage
- 既存:
  - `zed-agentops-init.sh <root>`
- 追加:
  - `zed-agentops-init.sh <root> --update`
  - `zed-agentops-init.sh --update <root>` も許容（順不同）

## Detection / Safety Checks
`--update` 実行時は以下を必須チェック:

1. **root は既存ディレクトリであること**
   - `root` が存在しない場合はエラー終了
2. **AgentOps 管理ディレクトリか判定**
   - 例: `.agent/` と `.zed/` が存在、または `.rules` が存在
   - 判定に失敗した場合は **警告 + 明示的確認**
3. **ユーザー確認**
   - 既存ディレクトリに対する更新であることを明示し、`[y/N]` 確認

## Update Flow (Step-by-Step)
1. **存在確認 & 事前チェック**
   - `root` がディレクトリであることを確認
   - `.agent/` が無い場合は作成
2. **legacy cleanup**
   - 以下が存在すれば削除
     - `.agent/handoff.md`
     - `.agent/snapshot-log.jsonl`
     - `.agent/work-in-progress.md`
3. **new persistence files**
   - `.agent/journal.jsonl` が無ければ作成
   - `.agent/snapshot.json` が無ければ初期作成
   - `.agent/checkpoint.json` が無ければ初期作成
4. **.rules update**
   - `.rules` を **最新テンプレートで更新**
   - 既存の手書き修正がある場合に備え、下記の方針を推奨
     - 更新前に `.rules.bak` を作る
     - もしくは `--update` 時は上書き許可を確認

## Idempotency
- 既に存在するファイルは基本 **skipping**
- 削除対象ファイルが無くても問題なく進行
- `--update` を複数回実行しても同じ結果に収束

## Error Handling
- 削除対象が存在しない → 続行
- 作成失敗 → エラー終了（原因を出力）
- `.rules` の更新で権限エラー → エラー終了

## User Messaging (Example)
- `Updating AgentOps scaffold in: <root>`
- `Removed legacy: .agent/handoff.md`
- `Created: .agent/journal.jsonl`
- `Updated: .rules`
- `Done.`

## Acceptance Criteria
- `--update` 実行後、以下が満たされる
  - legacy ファイルが削除されている
  - `.agent/journal.jsonl`, `.agent/snapshot.json`, `.agent/checkpoint.json` が存在
  - `.rules` が最新テンプレート内容になっている
- 既存プロジェクトのデータを不要に削除しない
- 再実行可能

## Notes
- `.zed/` や `.git` は更新対象外（既存を尊重）
- `.gitignore` は必要に応じて追記のみ（削除しない）