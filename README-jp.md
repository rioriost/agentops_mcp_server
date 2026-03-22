# Zed AgentOps

Zed AgentOps は、Zed 上で edit → verify → commit のワークフローを回すためのローカル MCP サーバーと、作業再開しやすいプロジェクト用スキャフォールドを提供します。

> 現在の対応環境は macOS のみです。

## What it does

- Zed で AgentOps を使うためのプロジェクト雛形を作成します
- リポジトリ操作、検証、作業再開を支援するローカル MCP サーバーを提供します
- プロジェクトごとに拡張できる標準 `verify` / `verify-release` エントリーポイントを追加します
- セッション中断後でも作業を再開しやすくするためのローカル状態を保持します
- 生成されるスキャフォールド、runtime の workflow rules、helper behavior を、v0.5.4 でサポートする contract に揃えます

この README は利用者向けです。AgentOps を実際に使い始めるための流れに絞って説明します。

## Installation

Homebrew でインストールします。

```bash
brew intall rioriost/tap/agentops_mcp_server
```

これにより、次がインストールされます。

- `agentops_mcp_server`
- `zed-agentops-init`

## Usage

### Zedの設定

AgentOps を使い始める前に、Zed 側で MCP サーバーを使えるように設定してください。

v0.5.4 のワークフローでは、実質的にこれは必須です。想定されている運用は次を前提にしています。

- MCP サーバーが Zed に登録されていること
- Agent Panel から AgentOps の tool を呼べること
- よく使う AgentOps tool にあらかじめ permission が付与されていること

まず、Zed の設定に MCP サーバーを追加します。

```json
{
  "agentops-server": {
    "command": "/opt/homebrew/bin/agentops_mcp_server",
    "args": [],
    "env": {
      "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
  }
}
```

次に、workflow に必要な MCP tools を許可してください。実用上のベースラインは次のようになります。

```json
{
  "terminal": {
    "default": "allow"
  },
  "mcp:agentops-server:workspace_initialize": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_event_append": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_state_save": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_state_rebuild": {
    "default": "allow"
  },
  "mcp:agentops-server:session_capture_context": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_verify": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_commit": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_status_summary": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_commit_message_suggest": {
    "default": "allow"
  },
  "mcp:agentops-server:tests_suggest": {
    "default": "allow"
  },
  "mcp:agentops-server:tests_suggest_from_failures": {
    "default": "allow"
  },
  "mcp:agentops-server:commit_if_verified": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_compact_context": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_handoff_export": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_resume_brief": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_start_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_update_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_end_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_add_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_update_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_complete_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_capture_state": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_task_summary": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_observability_summary": {
    "default": "allow"
  }
}
```

必要に応じて permission は調整してください。ただし、これらがブロックされていると、v0.5.4 の想定ワークフローは成立しません。

### zed-agentops-initによるプロジェクトの初期化

AgentOps 管理対象のプロジェクトを新規作成または更新します。

```bash
zed-agentops-init my_project
```

既存の AgentOps-managed directory を更新する場合は:

```bash
zed-agentops-init --update my_project
```

古い AgentOps scaffold を現在の workflow contract に合わせたい場合は、`--update` を使ってください。

#### 何が作成されるか

`zed-agentops-init` を実行すると、Zed で AgentOps を使い始めるために必要なファイルが作成されます。

- `.rules`
- `.zed/tasks.json`
- `.zed/scripts/verify`
- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

加えて、次も行います。

- Git リポジトリが無ければ初期化します
- `.gitignore` に一般的な除外設定を追記します
- 既存ファイルは可能な限り保持します
- `--update` により既存セットアップを更新できます

初期生成される `.agent/tx_state.json` は、正規化された empty-transaction state です。通常の runtime 解釈に必要な主な top-level field と metadata を含みます。

- `schema_version`
- `active_tx`
- `last_applied_seq`
- `integrity.state_hash`
- `integrity.rebuilt_from_seq`
- `integrity.drift_detected`
- `integrity.active_tx_source`
- `updated_at`

この baseline は、canonical event replay をしないと分からない runtime-only facts を捏造せずに、runtime で再構築されるより豊かな state shape と整合するように設計されています。

### プロジェクトをZedで開く

初期化後は、次の順で進めるのが基本です。

1. プロジェクトディレクトリを Zed で開く
2. MCP サーバー設定が有効になっていることを確認する
3. Agent Panel を開く
4. Agent が必要な AgentOps tools にアクセスできることを確認する
5. 初期化した repository root から作業を始める

v0.5.4 でサポートされる workflow では、Agent は root-dependent な操作の前に workspace を初期化し、`.agent/tx_state.json` と `.agent/tx_event_log.jsonl` を canonical なローカル workflow state として扱うことが期待されます。

### 必要に応じてverify / verify-releaseの設定

scaffold には次が含まれます。

- `.zed/scripts/verify`
- `.zed/scripts/verify-release`

デフォルトの `verify` は意図的に控えめです。各プロジェクトに合わせて拡張してください。

Python プロジェクトでよくある考え方は次です。

- `verify`: 日常作業向けの軽量チェック
- `verify-release`: リリース向けのより完全な検証

たとえば Python なら、次のような構成が考えられます。

- `.zed/scripts/verify`
  - `ruff check`
  - `ruff format --check`
  - `pytest -q`
- `.zed/scripts/verify-release`
  - `pytest --cov`

デフォルトのリリース向けカバレッジ入口は次です。

```bash
.zed/scripts/verify-release
```

Python の coverage に使う場合は `pytest-cov` が必要です。

### プログラミング言語に応じたプロジェクトの初期化

AgentOps は workflow を scaffold しますが、各言語や package manager の本来の project initialization を置き換えるものではありません。

たとえば Python プロジェクトで `uv` を使う場合は、次のように初期化します。

```bash
uv init
```

その後、プロジェクトに必要なチェックを `.zed/scripts/verify` と `.zed/scripts/verify-release` に追加してください。

他の ecosystem でも同様に、その言語に適したツールで project 自体を初期化してから Agent に実作業を依頼するのが自然です。

### プロジェクトにdocsディレクトリを作成し、draftを書く

### workflow response contract の読み方
AgentOps の lifecycle-aware なレスポンスは、v0.5.4 では machine-readable な workflow guidance を返すことを前提にしています。これにより、agent や client は自然文だけに頼らず、canonical state に基づいて次の操作を判断できます。

成功レスポンスでは、必要に応じて次のような field を返します。

- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `requires_followup`
- `followup_tool`
- `active_tx_id`
- `active_ticket_id`

状況に応じて、追加で次の field が含まれます。

- `current_step`
- `verify_status`
- `commit_status`
- `integrity_status`
- `can_start_new_ticket`
- `resume_required`

これらの field は、tool 実行後の canonical な transaction state を表します。特に `status` / `phase` / `next_action` は、それぞれ「現在どの状態にあるか」「その状態を lifecycle 上どう解釈すべきか」「次に何をするべきか」を分けて理解するために重要です。

失敗レスポンスも、v0.5.4 では free-form な説明だけではなく、structured な recovery guidance を返す前提です。代表的な field は次のとおりです。

- `error_code`
- `reason`
- `recoverable`
- `recommended_next_tool`
- `recommended_action`

状況が分かっている場合は、追加で次のような field も含まれます。

- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `active_tx_id`
- `active_ticket_id`
- `current_step`
- `integrity_status`
- `blocked`

これにより、agent や client は human-readable な文章の解釈だけに頼らず、begin が必要なのか、resume すべきなのか、integrity repair が必要なのかを分岐できます。

helper の成功は、必ずしも terminal completion を意味しません。特に `commit_if_verified` や `repo_commit` が成功しても、canonical state は non-terminal な `committed` にとどまる場合があります。その場合、`next_action` が `tx.end.done` を示し、明示的な終了処理が別途必要です。

逆に `done` や `blocked` は terminal state です。client や agent は、helper の成功可否だけで完了判定をせず、必ず返却された `canonical_status`、`terminal`、`requires_followup` を見て follow-up obligation を判断してください。

v0.5.4 の workflow では、プロジェクトに `docs` ディレクトリを作って、たとえば次のような draft を書くのが有効です。

```text
docs/draft_0.1.0.md
```

この draft には、たとえば次を書きます。

- 目的
- スコープ
- 制約
- 優先順位
- フェーズ
- 想定チケット

この draft は、ユーザーが全部自分で書いてもかまいませんし、AI エージェントと一緒に要件を洗い出しながら作ってもかまいません。どちらも正しい使い方です。

実践的には、次の流れが扱いやすいです。

1. `docs/` を作る
2. まず自分が分かっている要件を書き出す
3. エージェントに draft をもとに、phase を意識した plan へ整理させる
4. 必要に応じて、次のような派生 planning artifact を管理する。この作業もエージェントに依頼できます。
   - `docs/__version__/plan.md`
   - `docs/__version__/tickets_list.json`
   - `docs/__version__/pX-tY.json`
5. 作業中は、それらの planning file を workflow guidance として使う

planning flow を分けて考えると、次のようになります。

- `draft.md`
  - 問題設定
  - 目的
  - スコープ
  - 制約
  - 優先順位
  を書く場所
- `plan.md`
  - draft をもとに、phase ごとの実行計画へ整理する場所
- `tickets_list.json`
  - 進める ticket の一覧と状態を簡潔に持つ index
- `pX-tY.json`
  - 個別 ticket ごとの inputs / outputs / acceptance criteria / notes を持つ任意の詳細記録

ticket artifact を管理する場合、status は次のような set にしておくと扱いやすいです。

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

v0.5.0 で重要な boundary は次です。

- `docs/` 配下の planning files は有用な workflow artifact です
- ただし server が管理する mandatory protocol state ではありません
- server はそれら planning artifact の生成・同期・検証を保証しません
- それらを管理する場合でも、`tickets_list.json` と各 per-ticket file の同期は user / client 側の運用責任です

つまり、これらは user-managed / client-managed な workflow document と理解するのが正確です。

## Updating from older versions

すでに Zed AgentOps を使っている場合は、次を実行してください。

```bash
zed-agentops-init --update <project>
```

これにより、主に次の user-facing scaffold が更新されます。

- `.rules`
- `.agent` の状態ファイルの存在
- 必要に応じた標準の verify / task scaffolding

古い scaffold から移行する場合、更新を推奨します。最近の version では次が強化されています。

- resumability behavior
- transaction/state alignment
- workflow rule clarity
- scaffold/runtime consistency

多くのケースでは `--update` で十分です。

## What's new in v0.5.0

v0.5.0 の user-facing な変化は、主に **分かりやすさと予測可能性** にあります。

### 1. ドキュメントの workflow と、実際にサポートされる workflow が近づいた

v0.5.0 の主目的は、次のズレを減らすことです。

- `.rules`
- 生成される scaffold
- runtime server behavior
- helper tools
- release-facing documentation

ユーザー目線では、「書かれている workflow を以前より信頼しやすくなった」と考えてよいです。

### 2. ticket files は server protocol ではなく convention

次のような planning files を管理していても:

- `docs/__version__/plan.md`
- `docs/__version__/tickets_list.json`
- `docs/__version__/pX-tY.json`

それらは便利な workflow document ですが、canonical な server-managed state ではありません。

実務上は:

- 手で管理してよい
- Agent と一緒に管理してよい
- ただし server が自動生成・同期・検証してくれる前提にはしない

という理解が正しいです。

### 3. canonical なローカル workflow state は `.agent/` 配下にある

実用上、最も重要な canonical artifact は次です。

- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

handoff や planning docs は便利ですが、canonical workflow record ではありません。

### 4. commit workflow がより明示的になった

サポートされる flow は以前より厳密です。

- verify の後に commit
- 変更がなければ commit しない

これにより、空 commit や未検証 commit を減らしやすくなりました。

### 5. file-intent workflow を安全に使いやすくなった

サポートされる helper surface は次です。

- `ops_add_file_intent`
- `ops_update_file_intent`
- `ops_complete_file_intent`

これらにより、canonical transaction rules を緩めずに、一般的な file-intent workflow を扱いやすくしています。

### 6. bootstrap state を理解しやすくなった

初期の `.agent/tx_state.json` baseline がより正規化され、古い scaffold 由来の欠損と runtime 上まだ materialize されていない情報を混同しにくくなりました。

### 7. version concepts は意図的に分かれている

見える version は1種類ではありません。

- package/server version
- transaction/schema version
- draft/release-plan version

これは正常です。`docs` 上の version label と persisted transaction schema version が常に同じとは限りません。

### v0.5.0 における、ユーザー向けの実践的な推奨

日常運用では、次を意識すると扱いやすいです。

1. 必要に応じて `zed-agentops-init --update` で scaffold を最新に保つ
2. `.agent/tx_state.json` と `.agent/tx_event_log.jsonl` を canonical なローカル workflow state とみなす
3. `docs/` 配下の planning files は便利な convention であり、server protocol ではないと理解する
4. `verify` / `verify-release` は自分のプロジェクトに合わせて必ず調整する
5. 大きな作業の前に、`docs/` に小さくてもよいので draft を書く
6. Agent の workflow は以前より initialize → change → verify → commit を厳密に踏む前提で考える

v0.5.0 の client/server contract をもう少し詳しく知りたい場合は、`docs/v0.5.0/interoperability.md` を参照してください。

## Notes

- 現時点では macOS のみ対応
- 生成される scaffold は各リポジトリに合わせて調整する前提です
- デフォルトの verify scripts は意図的に控えめなので、プロジェクトごとの追加設定が必要です
- v0.5.0 では enforced protocol behavior と user-managed workflow convention を意図的に区別しています

## License

MIT
