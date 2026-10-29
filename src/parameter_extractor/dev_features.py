"""
Developer-only features (Mickey, 2026-10-29), never in public builds.

`handoff` (handoff.py): the model steps are answered in a Claude Code session instead of through the
API. Anthropic doesn't allow third-party products to offer claude.ai login or subscription limits
(Agent SDK docs, "Unless previously approved..."), so the shipped app uses API keys only and this
stays a local developer tool:

  - running from source: on only with the environment variable PARAMETER_EXTRACTOR_DEV=1;
  - a built app: on only in a developer build (`packaging/build_macos.sh --dev`, which bundles the
    DEV_BUILD marker and handoff.py). The public build has neither -- the module is excluded from it,
    so the option can't be switched on there.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ENV_VAR = "PARAMETER_EXTRACTOR_DEV"
MARKER = "DEV_BUILD"


def enabled() -> bool:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        if not (base / "parameter_extractor" / MARKER).is_file():
            return False
    elif os.environ.get(ENV_VAR) != "1":
        return False
    try:
        import parameter_extractor.handoff  # noqa: F401 -- absent from public builds
    except ImportError:
        return False
    return True
