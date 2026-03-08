# Draft for 0.4.6: multiple MCP servers with Zed

## Background
- 0.4.3で、CWDが"/"の場合はエラーとして扱う変更を行ったが、Zedは複数のプロジェクト（ディレクトリ）がある場合には、それぞれのプロジェクトでMCPサーバをforkして実行する際にCWDを"/"に設定したままにしてしまう不具合があるため（https://github.com/zed-industries/zed/pull/51002）、2つ目以降のプロジェクトでMCPサーバ（src/以下のPython実装、agentops_mcp_server）が起動しない。
- 0.4.3での変更以前には、例えば、"/Users/rifujita/ownCloud/bin/my_project/.agent/"のartifactsをRead / Writeすべきところ、"/.agent/"としてパスを展開し、当然のことながらパーミッションエラーになる不具合が発生していた。
- CWDが"/"の場合に、エラーとして扱うのではなく、プロジェクト（ディレクトリ）のファイルのRead/Writeを伴うtoolの実行時に、AIエージェントにCWDを渡す変更案が考えられる。Zedのバグに対するworkaroundなので、他に良い実装案がないかも検討したい。

## Goal
- Zedの複数のプロジェクトで同時にMCPサーバ（agentops_mcp_server）が起動すること。

## Acceptance criteria
- カバレッジ90%以上
