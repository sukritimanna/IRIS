"""Read-only access to the existing engine code (demo/staged_walkthrough, iris/lib).

Modules are imported from the repo without executing their main() and without writing bytecode.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def walkthrough(paths, name: str):
    """Import demo/staged_walkthrough/<name>.py (its own `from systems import ...` resolves there)."""
    d = str(paths.repo("walkthrough"))
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module(name)


def iris_lib(paths, name: str):
    """Import iris.lib.<name> from repo_root."""
    root = str(paths.repo_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module(f"iris.lib.{name}")


def script(paths, name: str) -> Path:
    return Path(paths.repo("walkthrough")) / name


def toolkit(paths, key: str, name: str):
    """Import <paths[key]>/<name>.py from a flat toolkit folder (e.g. demo/bifeo3/grid6d/bfo6d, whose modules
    import each other as `from basis import ...`)."""
    d = str(paths.repo(key))
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module(name)
