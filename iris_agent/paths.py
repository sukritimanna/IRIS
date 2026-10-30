"""Path resolution and the write guard.

Every file IRIS_AGENT writes goes through `out()`, which refuses any path that is not inside
`agent_root`. Everything under `repo_root` outside `agent_root` is read-only by construction.
"""
from __future__ import annotations

from pathlib import Path


class WriteOutsideAgentRoot(PermissionError):
    pass


class Paths:
    def __init__(self, repo_root: str | Path, agent_root: str | Path, entries: dict[str, str]):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.agent_root = Path(agent_root).expanduser().resolve()
        if self.agent_root == self.repo_root:
            raise ValueError("agent_root must be a sub-folder of repo_root, not repo_root itself")
        self._entries = dict(entries)

    # ---- read side -------------------------------------------------------------------------
    def repo(self, key: str) -> Path:
        """A read-only input, resolved against repo_root (absolute paths are kept)."""
        p = Path(self._entries[key]).expanduser()
        return p if p.is_absolute() else (self.repo_root / p)

    def has(self, key: str) -> bool:
        return key in self._entries

    # ---- write side ------------------------------------------------------------------------
    def out(self, *parts: str | Path) -> Path:
        """A path IRIS_AGENT may write. Raises unless it lies inside agent_root."""
        p = Path(self.agent_root, *parts).resolve()
        if not p.is_relative_to(self.agent_root):
            raise WriteOutsideAgentRoot(f"refusing to write outside {self.agent_root}: {p}")
        return p

    def run_dir(self, thread_id: str) -> Path:
        d = self.out(self._entries.get("test_runs", "test_runs"), thread_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def as_dict(self) -> dict:
        return {"repo_root": str(self.repo_root), "agent_root": str(self.agent_root),
                **{k: str(self.repo(k)) if k != "test_runs" else v for k, v in self._entries.items()}}


def from_config(cfg: dict) -> Paths:
    p = cfg["paths"]
    return Paths(p["repo_root"], p["agent_root"],
                 {k: v for k, v in p.items() if k not in ("repo_root", "agent_root")})
