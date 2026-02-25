#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from importlib import resources


def _script_path() -> str:
    try:
        return str(
            resources.files("agentops_mcp_server").joinpath("zed-agentops-init.sh")
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("zed-agentops-init.sh is not packaged") from exc


def main() -> None:
    script = _script_path()
    if not os.path.exists(script):
        raise FileNotFoundError(f"zed-agentops-init.sh not found at {script}")
    os.execv("/usr/bin/env", ["env", "bash", script, *sys.argv[1:]])


if __name__ == "__main__":
    main()
