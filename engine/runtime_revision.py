"""Revision captured on import, plus an independent view of the checkout on disk."""
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def current_revision() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
                                capture_output=True, text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


RUNNING_REVISION = current_revision()
