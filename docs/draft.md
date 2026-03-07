# Draft for 0.4.5: bug fixes

## Background
- 0.4.3で導入した、CWDが"/"の時にはエラーとする仕様では、複数のプロジェクトからMCPサーバが起動しない。おそらく、　Zedのバグあるいは仕様に起因するもので、agentops_mcp_serverとしては、ad-hocに対応せざるを得ない。
- CWDが"/"の場合には、AIエージェントが送ってくるworkspace_rootをCWDとしてパスを展開することで対応する。
- MCPサーバのtoolのうち、ファイルのread/writeが必要なものは、workspace_rootを基準としてパスを展開する。展開する関数は共通化されている必要がある。
- .rulesで、上記workspace_rootが必要なtoolに対し、必ずCWDをworkspace_rootとして送信するように強制する。

## Goal
- 複数のプロジェクトからMCPサーバが起動出来る。

## Acceptance criteria
- カバレッジ90%以上
