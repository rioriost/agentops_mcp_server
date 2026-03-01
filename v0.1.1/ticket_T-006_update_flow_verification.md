# T-006 Update Flow Manual Verification Checklist

## Summary
`zed-agentops-init.sh --update` の手動検証を実施し、legacy ファイルの削除、新規 state ファイル作成、`.rules` 更新が期待通りであることを確認した。

## Environment
- OS: macOS
- Script: `src/agentops_mcp_server/zed-agentops-init.sh`
- Test target: 既存管理ディレクトリを模した一時ディレクトリ

## Checklist & Results

### 1) 既存管理ディレクトリの検出と確認
- [x] 既存ディレクトリを指定すると確認プロンプトが表示される
- [x] `y` 入力で更新処理が継続される

### 2) legacy cleanup
- [x] `.agent/handoff.md` が削除される
- [x] `.agent/snapshot-log.jsonl` が削除される
- [x] `.agent/work-in-progress.md` が削除される

### 3) new persistence files
- [x] `.agent/journal.jsonl` が作成される
- [x] `.agent/snapshot.json` が作成される
- [x] `.agent/checkpoint.json` が作成される

### 4) `.rules` update
- [x] `.rules` が最新テンプレートで上書きされる
- [x] 既存 `.rules` が `.rules.bak` として退避される

### 5) `.zed` scaffold
- [x] `--update` では `.zed` 生成をスキップする

## Evidence (observed outcomes)
- `Removed legacy: .agent/handoff.md`
- `Removed legacy: .agent/snapshot-log.jsonl`
- `Removed legacy: .agent/work-in-progress.md`
- `.agent/` 配下に `journal.jsonl`, `snapshot.json`, `checkpoint.json` を確認
- `.rules` が更新され `.rules.bak` が作成されたことを確認
- `Skipping .zed scaffold (update mode).`

## Conclusion
`--update` 実行時の更新フローは仕様通りに動作することを確認した。