# Zed AgentOps

Zed AgentOps は、Zed 上で edit → verify → commit の流れを回しやすくするための MCP サーバーと、再開しやすい作業用スキャフォールドを提供します。

> 現在の対応環境は macOS のみです。

## できること

- Zed で AgentOps を使うためのプロジェクト雛形を作成
- リポジトリ操作、検証、作業再開を支援するローカル MCP サーバーを提供
- プロジェクトごとに拡張できる標準 `verify` エントリーポイントを追加
- セッション中断後でも作業を再開しやすくするためのローカル状態を保持

この README は利用者向けです。内部実装の詳細は必要最小限に絞っています。

## インストール

Homebrew でインストールします。

```bash
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

これにより、`agentops_mcp_server` と `zed-agentops-init.sh` がインストールされます。

## クイックスタート

新しいプロジェクトディレクトリを初期化する場合:

```bash
zed-agentops-init.sh my_project
```

既存の AgentOps 管理ディレクトリを更新する場合:

```bash
zed-agentops-init.sh --update my_project
```

初期化後の流れ:

1. ディレクトリを Zed で開く
2. Zed の設定に MCP サーバーを登録する
3. Agent Panel を開く
4. リポジトリ上で作業を開始する

## 初期化で作成されるもの

`zed-agentops-init.sh` を実行すると、Zed で AgentOps を使い始めるために必要なファイルが作成されます。

- `.rules`
- `.zed/tasks.json`
- `.zed/scripts/verify`
- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

加えて、次も行います。

- Git リポジトリが無ければ初期化
- `.gitignore` に一般的な除外設定を追記
- 既存ファイルは可能な限り保持
- `--update` により既存セットアップを更新可能

## 推奨される Zed 設定

Zed の設定に MCP サーバーを追加してください。

例:

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

その後、必要に応じて Zed 側でツール権限を設定してください。

## 基本的な使い方

プロジェクトを初期化したあとの基本的な流れは次のとおりです。

1. エージェントに変更を依頼する
2. プロジェクトの検証を実行させる
3. 結果を確認する
4. 変更をコミットする

標準の検証入口は次です。

```bash
.zed/scripts/verify
```

必要に応じて、各リポジトリ向けに内容を拡張してください。  
デフォルトでは、変更されたファイルに応じて、利用可能なツールが入っていれば Python、Swift、Rust、Shell、Bicep などの代表的なチェックを試みます。

## リリース向け検証 / カバレッジ

リリース向けの Python カバレッジ計測には、次を使ってください。

```bash
.zed/scripts/verify-release
```

これには `pytest-cov` が必要です。

## 古いバージョンから更新する場合

すでに Zed AgentOps を使っている場合は、次を実行してください。

```bash
zed-agentops-init.sh --update <project>
```

これにより、主に次の利用者向けセットアップが更新されます。

- `.rules`
- `.agent` の状態ファイルの存在
- 必要に応じた標準の verify / task スキャフォールド

最近のバージョンでは、作業再開まわりと状態整合性も改善されているため、古いスキャフォールドを使っている場合は新しい作業を始める前に更新を推奨します。

## 最近の変更点

### 現在の動作の要点

- スキャフォールド生成時の `.rules` が現在のワークフロー前提に揃うようになりました
- 初期トランザクション状態が現在の基準値に揃いました
- 作業再開はローカルの AgentOps 状態ファイルを中心に扱う前提です
- セッション中断と再開をより安全に扱える初期構成になっています

### 古いスキャフォールドから更新した場合に変わること

次のような更新が入る場合があります。

- `.rules` の更新
- 初期状態デフォルト値の更新
- スキャフォールドと現在の実行時挙動の整合性向上

ほとんどのケースでは `--update` で十分です。

## よく触るファイル

- `.rules` — エージェントのコンテキストに注入されるプロジェクト指示
- `.zed/scripts/verify` — 主な検証エントリーポイント
- `.zed/tasks.json` — 再利用可能な Zed タスク
- `.agent/tx_event_log.jsonl` — ローカルの AgentOps イベントログ
- `.agent/tx_state.json` — 作業再開に使われるローカル状態

利用者の観点では、重要なのはシンプルです。  
最新のスキャフォールドを使うか `--update` を実行して、`.rules` を最新に保ってください。

## 補足

- 現時点では macOS のみ対応
- 生成されるスキャフォールドは、各リポジトリに合わせて調整する前提です
- 標準の verify スクリプトは控えめな初期設定なので、プロジェクトに応じた追加が必要になることがあります

## ライセンス

MIT