# Draft for 0.5.1: make `zed-agentops-init` write `.rules` reliably from packaged installs

## Background

Version 0.5.0 introduced a stronger single-source-of-truth model for workflow rules:

- the repository-level `.rules` reflects the intended AgentOps operating contract,
- `workflow_rules.py` provides the canonical generated rules text,
- `workflow_rules_fallback.txt` is packaged for fallback use,
- and `zed-agentops-init.sh` is responsible for writing `.rules` into initialized workspaces.

In principle, this should allow both source-tree usage and installed-package usage to provision the same rules content into target projects.

However, the current bootstrap path still depends on how `zed-agentops-init.sh` resolves its rule source files at runtime.

## Problem

The current `zed-agentops-init.sh` implementation resolves rule inputs using `${PWD}`:

- `${PWD}/.rules`
- `${PWD}/src/agentops_mcp_server/workflow_rules.py`
- `${PWD}/src/agentops_mcp_server/workflow_rules_fallback.txt`

This works when the script is executed from the repository root, because those paths exist there.

It is not reliable when the packaged `zed-agentops-init` command is run from an arbitrary working directory after installation.

In the installed case:

- the shell script is loaded from package resources,
- the current working directory is usually the user’s project or some unrelated directory,
- `${PWD}` does not point to the package resource location,
- and the workflow rules source files cannot be resolved from `${PWD}`.

As a result, `.rules` may fail to be written even though the package contains the required rule assets.

## Root cause

The shell script is using the caller’s current directory as the lookup base for packaged assets.

That is the wrong anchor for installed execution.

The correct anchor is the directory that contains the script itself, because:

- `zed-agentops-init.sh`
- `workflow_rules_fallback.txt`

are packaged together as resources,
and script-relative resolution remains valid regardless of where the command is invoked.

## Goal

For 0.5.1, make `.rules` generation reliable for both:

1. repository-local execution of `src/agentops_mcp_server/zed-agentops-init.sh`
2. installed execution via `zed-agentops-init`

without requiring the user to run the command from the repository root.

## Proposed fix

Adopt approach 1:

- resolve resource paths relative to `BASH_SOURCE[0]`,
- stop using `${PWD}` as the primary source base for workflow rules,
- preserve the existing fallback behavior,
- and keep `.rules` writing behavior unchanged from the user’s perspective.

## Detailed design

### 1. Compute the script directory from `BASH_SOURCE[0]`

The shell script should determine its own physical directory early in execution.

That directory should become the base for packaged resource lookup.

Conceptually:

- determine the absolute path of the current script,
- derive its containing directory,
- use that directory to locate adjacent packaged assets.

This is the correct runtime anchor for installed package resources.

### 2. Use script-relative lookup for packaged rule assets

The current logic should be revised so that packaged assets are discovered relative to the script directory, not `${PWD}`.

Expected resolution model:

- packaged fallback rules:
  - `<script_dir>/workflow_rules_fallback.txt`
- optional Python rule source:
  - `<script_dir>/workflow_rules.py` or another script-relative equivalent if that file is actually packaged

If only the fallback text is packaged in release artifacts, the script should prefer that packaged fallback directly.

### 3. Keep source-tree compatibility

The repository source-tree flow should continue to work.

That means the implementation should still support development-time execution from the checked-out repository.

A practical interpretation is:

- if script-relative packaged assets exist, use them,
- otherwise use a source-tree-compatible fallback if needed.

This preserves local development usability while fixing installed behavior.

### 4. Preserve update semantics for target `.rules`

The target workspace behavior should remain the same:

- skip if `root/.rules` exists and is not a file,
- skip existing `.rules` on non-update initialization,
- back up existing `.rules` on update mode,
- write the resolved rules file into `root/.rules`.

The issue is path resolution, not overwrite policy.

## Acceptance criteria

The 0.5.1 fix should satisfy all of the following:

### Installed command behavior
- Running `zed-agentops-init <project>` from an arbitrary current working directory writes `<project>/.rules`.
- Running `zed-agentops-init --update <project>` from an arbitrary current working directory updates `<project>/.rules` as intended.

### Source-tree behavior
- Running `src/agentops_mcp_server/zed-agentops-init.sh <project>` from the repository still writes `<project>/.rules`.
- Existing initialization behavior for `.agent`, `.gitignore`, and `.zed` scaffolding remains intact.

### Path resolution correctness
- Rule asset discovery no longer depends on `${PWD}`.
- Packaged assets are resolved from the script’s own location.

### Packaging compatibility
- Release artifacts continue to include the rule content needed to generate `.rules`.
- The installed command does not require repository-only paths like `src/agentops_mcp_server/...` to exist in the caller’s current directory.

## Non-goals

This draft does not propose:

- changing the content of the canonical workflow rules,
- redesigning the `.rules` overwrite policy,
- changing transaction semantics,
- changing `.agent` initialization behavior,
- or introducing a new environment-variable-based resource contract.

The scope is specifically to fix `.rules` generation reliability through script-relative resolution.

## Implementation notes

The most important implementation choice is to make the script self-locating.

That is preferable to `${PWD}` because:

- it matches how packaged resources are actually laid out,
- it is stable under arbitrary invocation directories,
- it avoids accidental coupling to repository structure,
- and it removes the assumption that users run the command from the source checkout.

The fallback text file is especially important here because it is already part of the package surface and is sufficient to write `.rules` without needing dynamic repository reads.

## Test impact

The fix should be accompanied by tests that cover the installed-resource path assumption more directly.

Useful coverage includes:

1. verifying the init script no longer contains `${PWD}`-based rule-source paths for packaged assets,
2. verifying the script uses a script-relative path strategy,
3. verifying that the package-level init entrypoint can execute successfully when the current working directory is unrelated to the repository layout,
4. verifying `.rules` is created in the target workspace under that invocation pattern.

## Risks

### Low functional risk
The change is localized to resource path resolution in the init shell script.

### Medium packaging risk
If the script-relative asset path is implemented incorrectly, installed bootstrap could still fail.
This risk is mitigated by keeping the fallback rules text packaged and testing invocation outside the repository root.

### Low behavioral risk
Target workspace semantics should not change aside from fixing the missing `.rules` issue.

## Expected outcome

After 0.5.1:

- `zed-agentops-init` should reliably create `.rules`,
- installed usage should behave the same as repository-local usage,
- the bootstrap process should no longer depend on where the user happens to run the command from,
- and the packaged initialization path should become consistent with the release model introduced in earlier versions.

## Summary

The 0.5.1 release should fix a bootstrap bug in `zed-agentops-init.sh` by replacing `${PWD}`-based workflow rules lookup with script-relative lookup based on `BASH_SOURCE[0]`.

This is the right fix because the failure is not in `.rules` content generation itself, but in how the script locates packaged rule assets during installed execution.