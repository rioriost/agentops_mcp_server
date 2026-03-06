# Draft for 0.4.0: transaction-aware task managing

## Background
- タスク（チケット）に着手すると、status="in-progress"になるが、このstatus中に複数のファイルを生成・更新する。この際、「どのファイルを、どういった目的で生成・更新していた」かは、journal/checkpoint/snapshotには記録されない（粒度が粗い）。
- .rulesにhandoffのルールを追加したが、上記の意図には沿っておらず、結果としてセッションの予期しない中断に対する耐性が向上していない。

```markdown
## Handoff & session safety (mandatory)
- When a tool execution adds/modifies files:
  1) ops_compact_context (compact context)
  2) ops_capture_state (snapshot + checkpoint)
  3) ops_handoff_export (handoff summary, optional file write)
```

- journal.jsonlによるAIエージェントの作業ログと、checkpoint.json　+ snapshot.jsonによるrole forwarding、handoff.jsonによるセマンティックなログ（「予期しない中断の際に、AIエージェントは何を実行中だったか？」が、セッション再開後に引き継げる）の最適化が必要。

- .rulesとagentops_mcp_server両方、あるいはその一方の強化が必要なのかは、検討の余地がある。

- journal / checkpoint / snapshotはRDBMSのACID特性を実装する具体的な手法なので、AIエージェントのタスク（チケット）をトランザクションとして扱うべきなのかも検討の余地がある。

- journal / checkpoint / snapshot / handoffの4つが必要なのかも検討の余地がある。設計変更も考慮する必要がある。

## Goal
- セッションの予期しない中断（例:AIエージェントを実行しているZedの終了、コンテキストウインドウのトークンの枯渇）が発生しても、新しいセッションで確実に作業を再開できる。

## Acceptance criteria
- カバレッジ90%以上
