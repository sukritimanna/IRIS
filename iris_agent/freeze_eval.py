"""Freeze the evaluation inputs: write eval/FROZEN.sha256 (one line per file) once, before any model
run; later runs call verify() and refuse if an input changed. The hashes go into Methods 4.8.

  python -m iris_agent.freeze_eval eval/              # freeze (refuses to change an existing freeze)
  python -m iris_agent.freeze_eval eval/ --check      # verify only
  python -m iris_agent.freeze_eval eval/ --refreeze   # deliberately replace the freeze (logged in the file)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

FROZEN = "FROZEN.sha256"


def _files(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file() and p.name != FROZEN and not p.name.startswith("."))


def digest(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in _files(d)}


def read(d: Path) -> dict[str, str] | None:
    f = d / FROZEN
    if not f.is_file():
        return None
    out = {}
    for line in f.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            h, rel = line.split(None, 1)
            out[rel] = h
    return out


def verify(d: str | Path) -> tuple[bool | None, list[str]]:
    """(None, []) if not frozen; (True, []) if unchanged; (False, problems) otherwise."""
    d = Path(d)
    frozen = read(d)
    if frozen is None:
        return None, []
    now = digest(d)
    probs = [f"changed: {k}" for k in frozen if k in now and now[k] != frozen[k]]
    probs += [f"missing: {k}" for k in frozen if k not in now]
    probs += [f"added after freeze: {k}" for k in now if k not in frozen]
    return (not probs), probs


AGENT_ROOT = Path(__file__).resolve().parents[1]


def freeze(d: str | Path, refreeze: bool = False, reason: str | None = None) -> Path:
    d = Path(d).resolve()
    if not d.is_relative_to(AGENT_ROOT):
        raise SystemExit(f"refusing to write outside {AGENT_ROOT}: {d}")
    ok, probs = verify(d)
    if ok is not None and not refreeze:
        if ok:
            return d / FROZEN
        raise SystemExit("eval inputs changed since the freeze:\n  " + "\n  ".join(probs)
                         + "\nuse --refreeze only if this change is intended")
    now = digest(d)
    lines = []
    if ok is not None:                                   # a refreeze keeps the earlier log and says why
        if not reason:
            raise SystemExit("--refreeze needs --reason")
        old_text = (d / FROZEN).read_text()
        prev = read(d)
        unchanged = all(now.get(k) == h for k, h in prev.items())
        lines += [x for x in old_text.splitlines() if x.startswith("#")]
        lines.append(f"# refreeze {datetime.now(timezone.utc).isoformat(timespec='seconds')}: {reason}")
        lines.append(f"#   previous FROZEN.sha256 {hashlib.sha256(old_text.encode()).hexdigest()}; "
                     f"all {len(prev)} previously frozen files unchanged: {'yes' if unchanged else 'NO'}; "
                     f"added: {', '.join(sorted(set(now) - set(prev))) or 'none'}")
    else:
        lines.append(f"# frozen {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines += [f"{h}  {rel}" for rel, h in now.items()]
    (d / FROZEN).write_text("\n".join(lines) + "\n")
    return d / FROZEN


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eval_dir")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refreeze", action="store_true")
    ap.add_argument("--reason", default=None, help="why (required with --refreeze; written to the freeze log)")
    a = ap.parse_args(argv)
    if a.check:
        ok, probs = verify(a.eval_dir)
        print({None: "not frozen", True: "frozen, unchanged", False: "CHANGED:\n  " + "\n  ".join(probs)}[ok])
        return 0 if ok else 1
    f = freeze(a.eval_dir, a.refreeze, a.reason)
    print(f.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
