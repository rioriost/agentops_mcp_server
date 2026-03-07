# Draft for 0.4.1: remove workplace_root

## Background
- .rulesでworkspace_rootを指定しているが、[Zedのコード](https://github.com/zed-industries/zed)を調査すると、CWD については、ContextServerStore::create_context_server で root_path を取り、ローカルプロジェクトならそれを working_directory として MCP サーバに渡す実装になっているため、agentops_mcp_serverではworkspace_rootを指定する必要は無いことが判明した。
- 同じくコードでの調査では、ShellBuilder::new(...).non_interactive()をコールした後、.envs(binary.env.unwrap_or_default()) を追加しているだけなので、.zlogin / .zshrc / .zprofileのいずれも読み込まれず、.zshenvのみが読み込まれる。Homebrewでインストールされたgitコマンド等は、.zprofileによって/opt/homebrew/binがパスに追加されるため、ZedのMCPサーバでは見つけることが出来ないことも判明した。

## Goal
- workspace_rootを指定する必要が無いので.rulesから削除し、併せてsrc/以下のコードからworkspace_rootに関する処理を全て削除する。
- README*中の`setting.json`は以下になる。
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

## Acceptance criteria
- カバレッジ90%以上
