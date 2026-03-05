# .rulesの整理と強化

## 作業フローの強化
現在の.rulesで定義しているWork loopは以下。
```markdown
## Work loop (mandatory)
- For any code change:
  1) Implement smallest safe change
  2) Run "${VERIFY_REL}"
  3) If it fails: fix and repeat
  4) If it passes: commit changes
  5) Update snapshot/checkpoint as needed
```

しかし実際のWork loopは以下になっているので、これを.rulesに反映し、自動化したい。
1. userが、docs/draft.mdを執筆する
2. userが、AIエージェントに以下の作業を指示する。
  - docs/draft.mdを熟読して、実装作業を複数のフェーズに分割したdocs/plan.mdを生成する
3. userが、AIエージェントに以下の作業を指示する。
  - docs/plan.mdの各フェーズを、複数のタスクに分割する
  - 各タスクをチケットにする。docs/tickets_list.jsonに各チケットのメタ情報、docs/p1-t1.json, p1-t2.json...p2-t1.json, p2-t2.json...pN-tM.jsonに各チケットの詳細を記述する

  tickets_list.jsonの例:
  ```json
  {
    "version": "0.1.0",
    "source": "plan.md",
    "tickets": [
      {
        "id": "p1-t01",
        "priority": "P1",
        "title": "Compact context and handoff export for session transitions",
        "status": "planned",
        "file": "v0.1.0/ticket-p1-t01.json"
      },
  ......
  ```

  - 各チケットは、status(planned/in-progress/done/blocked)、inputs/outputs、dependencies等を管理できるJSONにチケットとして出力する
  
  ticket.jsonの例:
  ```json
  {
  "id": "p1-t01",
  "priority": "P1",
  "title": "Compact context and handoff export for session transitions",
  "scope": "session handoff",
  "description": "Implement compact context generation and JSON handoff export to reduce context loss between sessions while keeping output minimal and reusable.",
  "acceptance_criteria": [
    "A compact context is generated and stored in state under compact_context",
    "A context.compact journal event is recorded with metadata",
    "Handoff export returns a short JSON summary and can optionally write .agent/handoff.json",
    "Unknown events remain safely ignored"
  ],
  "inputs": [
    ""
  ],
  "outputs": [
    "src/agentops_mcp_server/main.py",
    "tests/test_main.py",
    "tests/test_persistence.py"
  ],
  "dependencies": []
}
```

4. このチケットを順に消化していくのが、上記の`Work Loop`となっている。`1) Implement smallest safe change`で、statusを"in-progress"に変更する。
5. `Work Loop`の`3) If it fails: fix and repeat`の後に、statusを"verified"に変更する。
6. 現在のWork Loopに含まれないが、`3)`と`4)`の間に、もう1つ作業を追加する。statusを"checking"に変更してから、チケットのacceptance_criteriaだけでは実装漏れがある可能性が高いため、plan.mdを参照して実装漏れがないことを確認する。
7. `4)`の後に、statusを"committed"に、`5)`の後に、statusを"done"に変更する。

## ログの統合
現在は、journal / snapshot / checkpoint / handoffの4つを利用しているが、.rulesで書き出すタイミングが厳密に定義されていない。また、指示の箇所も分散しており、優先度が明確になっていない。読み出すタイミングについても、より厳密に定義し、v0.2.0/implementation_plan.mdで意図したように、セッション開始時あるいは切り替え時に、4つのログを正しい順で解釈し、仕掛かり中の作業の有無、仕掛かり中の作業があったのであれば、その作業の状態を把握し、作業を引き継げるようにする。

この統合にあたっては、agentops_mcp_serverが提供するtoolが、journal / snapshot / checkpoint / handoffの4つに何を記録しているのかを慎重に検討する必要がある。また、もし直前の状態が把握できないのであれば、journal / snapshot / checkpoint / handoffのいずれかに、何を追加すれば良いのかも検討に値する。

## .rulesの軽量化
.rulesが、セッション開始時のみに参照されるのであれば、軽量化は必要が無い。一方、AIエージェントが指示を受けた際に、毎回.rulesを参照しているのであれば、軽量化の必要がある。
