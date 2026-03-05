# AgentOps v0.2.0 実装プラン（MCP/Zed前提）

## 目的
現行の「MCPツール + ルール + verifyスクリプト」という枠組みを維持したまま、  
AgentOpsとして不足している「運用の自動化」「状態の意味付け」「観測性」を補強する。  
外部ツールへの過度な依存は避け、MCPサーバ内のロジック強化で実現する。

## 制約
- Zed + MCPサーバの構成は維持する
- Zed側にSkillsはない
- 外部サービスや重い依存を前提にしない
- 既存の`.agent`永続化ファイル形式を尊重する

## v0.2.0で満たしたい要件
1. セッション切替時の引き継ぎ強化（コンテキスト枯渇対策）
2. セッション内の自走性向上（手動トリガーで自己再開できる）
3. `.rules`によるワークフロー制御の改善
4. 消費トークンの低減
5. 最小限の「運用オーケストレーション」をMCPサーバ内で提供
6. 状態モデルの拡張（タスク・フェーズ・成果物・失敗理由の明文化）
7. 低コストな観測性（ログ要約・集計・再現性向上）
8. 既存運用（journal/snapshot/checkpoint）との後方互換

---

## 実装スコープ

### 1. 状態モデルの拡張
現行の`state`は最小限の要素だけを保持しているため、次の属性を追加する。

- `task_id` / `task_title` / `task_status`
- `plan_steps`: 実行予定の手順配列
- `artifact_summary`: 生成・変更された成果物の要約
- `last_verification`: 直近のverify結果（ok, returncode, stdout/stderr要約）
- `failure_reason`: 失敗時の理由（verify失敗, commit失敗, toolエラーなど）

これらは`continue_state_rebuild`による再構成に含める。

### 2. イベント・ジャーナル拡張
`journal_append`を軸に、運用上必要なイベント種別を規定する。

追加イベント例:
- `plan.start` / `plan.step` / `plan.end`
- `task.created` / `task.progress` / `task.blocked`
- `artifact.summary`
- `verify.result`（`verify.end`を補助する意図）
- `context.compact`（継続用の短い要約を記録）
- `session.handoff`（新セッション向けの引き継ぎ情報）

既存イベントとの互換は維持し、未知イベントは無視する。

### 3. 高レベルMCPツールの追加
Zed側のSkillが無い前提で、MCP側で「運用一連の実行」を扱えるようにする。

新規ツール案:
- `ops_start_task(title, plan_steps?, session_id?)`
- `ops_update_task(status, note?, artifacts?)`
- `ops_end_task(summary, next_action?)`
- `ops_capture_state()`  ※snapshot+checkpointをまとめて実行
- `ops_task_summary()`  ※journalから人間向け要約を生成
- `ops_compact_context(max_chars?, include_diff?)`  ※継続用の短い要約を生成
- `ops_handoff_export(format?, path?)`  ※人間向け引き継ぎ要約を出力
- `ops_resume_brief()`  ※再開時の短いブリーフを返す

いずれも内部では`journal_append`、`snapshot_save`、`checkpoint_update`を組み合わせる。

### 4. 観測性（軽量）
外部サービス不要で以下を実現する。

- `journal`からの「最近のイベント要約」
- 直近セッションの失敗要因まとめ
- 成果物サマリと差分のリンク（パスのみ）

### 5. verify/commitループ補強
`commit_if_verified` / `repo_commit`はあるが、運用上の「繰り返し実行」に弱い。

v0.2.0では以下を追加する:
- verify失敗時の`failure_reason`記録
- verify結果の`last_verification`格納（stdout/stderrは要約）
- commit成功時に`artifact_summary`を更新
- `ops_*`経由では必ず`state`更新とジャーナル記録をセットで行う

### 6. セッション引き継ぎ（コンテキスト枯渇対策）
- `ops_compact_context`で「最小継続コンテキスト」を生成し、`state.compact_context`として保存
- `journal`に`context.compact`イベントを追記し、要約の生成時刻/対象範囲を記録
- `ops_handoff_export`で人間向けの短いハンドオフ要約を生成（標準は返却のみ、任意で`.agent/handoff.md`に書き出し）

### 7. セッション内自走性の向上
- `ops_resume_brief`で「前回の状態」「未完了タスク」「次の一手」を即時提示
- `continue_state_rebuild`の出力を短文化したテンプレートを用意し、長文にならないよう制限

### 8. `.rules`ワークフロー改善
- “ハンドオフ前チェック”の追加（`ops_compact_context` → `ops_capture_state`）
- “タスク終了時のまとめ”の追加（`ops_task_summary`）
- トークン節約の運用指針（差分最小・長文出力の抑制・要約優先）

### 9. トークン消費低減
- 既存の`_truncate_text`上限をツール引数で上書き可能にし、要約サイズを制御
- `journal`要約時は差分統計のみ（`git diff --stat`相当）を優先し、全文diffを避ける
- `ops_task_summary`は定型テンプレートで短文化し、過度な生成を抑制

---

## 実装タスク（詳細）

### A. スキーマ拡張
- `state`のデフォルト値定義を拡張（`compact_context`, `last_verification`など）
- `_apply_event_to_state`を追加イベントに対応

### B. 新規ツール実装
- `ops_start_task`, `ops_update_task`, `ops_end_task`, `ops_capture_state`, `ops_task_summary`
- `ops_compact_context`, `ops_handoff_export`, `ops_resume_brief`
- `tools_list`に登録
- `tools_call`のalias対応も必要に応じ追加

### C. 要約・観測ロジック
- journalから「直近N件」または「直近セッション」のサマリ生成
- `ops_task_summary`は簡易テンプレートでOK
- `ops_compact_context`はサイズ上限と差分統計優先で短文化

### D. 互換性
- 旧フォーマットの`state`が存在しても`_init_replay_state`で補完
- 新イベントが存在しても古いバージョンが破綻しないように冗長性を保持

### E. セッション引き継ぎ支援
- `ops_handoff_export`で新セッション向けの要点を出力
- `ops_resume_brief`で再開時の簡易ブリーフを生成
- `.agent/handoff.md`は任意生成（既存運用を壊さない）

### F. `.rules`/トークン節約の運用改善
- `.rules`テンプレートに「ハンドオフ前チェック」「タスク終了まとめ」を追加
- `ops_compact_context`/`ops_capture_state`を手動トリガーとして明示
- 生成時のトークン節約ガイドラインを追記

---

## 成果物
- `src/agentops_mcp_server/main.py` への機能追加
- 追加MCPツールのテスト
- 変更後のREADMEに簡単な使用例追記
- `v0.2.0/implementation_plan.md`（本ファイル）

---

## テスト計画
- `tests/test_persistence.py` に新規イベント再構成のテスト追加
- `tests/test_main.py` に新規ツールの入出力検証追加
- `ops_compact_context`のサイズ上限・要約内容のテスト
- `ops_resume_brief`の短文化テンプレート検証
- `.agent/handoff.md`の任意生成（有効/無効の両ケース）
- 既存テストの後方互換を維持

---

## 非目標（v0.2.0でやらないこと）
- 外部UI/ダッシュボードの提供
- 分散/並列マルチエージェント管理
- クラウド依存の可観測性基盤

---

## マイグレーション方針
- `.agent`既存ファイルは破壊しない
- 追加キーは補完的に扱う
- 既存Zed運用はそのまま継続可能

---

## スケジュール例
1. 状態モデル拡張（A）: 1日
2. 新規ツール実装（B）: 2日
3. 観測ロジック（C）: 1日
4. テスト拡充（D + テスト計画）: 1日
5. ドキュメント更新: 半日

---

## 期待効果
- MCPだけで「簡易運用オーケストレーション」が完結
- 状態の意味が増えて、ログや復元の実用性が向上
- セッション切替時の引き継ぎが安定し、途中生成の断絶を減らせる
- `.rules`の運用ガイドにより、セッション内の自走性が高まる
- 既存のシンプルさを壊さず、AgentOpsとして一段深くなる