# Draft for 0.4.2: optimize .rules, zed-agentops-init.sh, and README*

## Background
- 0.4.0でtransaction-aware task managingを導入し、セッション中断後のリストア耐性を改善したが、主にMCPサーバ側(src/agentops_mcp_server/*.py)への実装が先行し、実装された機能を.rules / zed-agentops-init.sh が完全に利用できる状態になっているかを検証する必要がある。
- 併せて、README*の全面的な見直しも必要となる。

## Goal
- MCPサーバの実装と、.rules / zed-agentops-init.shが整合している。
- README*が、Pythonコードの動作と矛盾しておらず、zed-agentops-init.sh、.rulesの使い方を正しく説明していること。

## Acceptance criteria
- カバレッジ90%以上
