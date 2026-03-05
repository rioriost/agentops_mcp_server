# Draft: Pass CWD as workspace_root to MCP tools

## Background
The current .rules says to always pass `workspace_root` to MCP tools, but it does not specify what value to pass. This led to passing a relative root name, which caused nested paths such as `<cwd>/<root>/<root>/.agent`.

## Goal
- Update the rule to explicitly pass the **CWD** as `workspace_root`.

## Acceptance criteria
- `.rules` instructs to pass CWD as `workspace_root`.
- No other behavior changes are required.