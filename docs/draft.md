# Draft for 0.4.3: fix path resolution

## Background
- Zedによって起動したMCPサーバツール群は、起動したディレクトリのnon-interactive shellとして起動し、起動されたディレクトリをCWDとして動作する。
- しかし、0.4.2のツールに、このパスを適切に展開していない問題がある。例えば、以下のメッセージを出力する。
  ops_start_task failed with a read‑only filesystem error on `/.agent`.
  これは本来なら、CWD/.agentと展開されなければならない。
- あるいは以下のようなエラーになる。
```quot
ツール実行結果
- `ops_capture_state` が `/.agent/tx_event_log.jsonl` 参照で失敗（read‑only filesystem）
- `ops_handoff_export` が `/.agent` への書き込みで失敗（read‑only filesystem）
```
- ツール群のパスの展開ロジックが**1箇所に集約されている**かチェックし、されていなければ修正する。
- 唯一のパスの展開ロジックが、正しくパスを展開するようにする。

## Goal
- MCPサーバ起動時にCWDをチェックし、"/"だった場合はエラーとする。
- ツールが正常に動作する。

## Acceptance criteria
- カバレッジ90%以上
