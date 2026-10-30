"""Build-step-4 entry point, kept for convenience: the nine seed faults now live in eval/faults.yaml
and run through iris_agent.inject.

  python -m iris_agent.faultinject --config configs/cssni3.yaml   # = inject --tag FI (gated)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .inject import AGENT_ROOT, run_all


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="configs/<system>.yaml (its folder holds the system configs)")
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    cfg = Path(a.config).resolve()
    results, out = run_all(AGENT_ROOT / "eval" / "faults.yaml", cfg.parent, "FI",
                           set(a.only.split(",")) if a.only else None, system=cfg.stem)
    print((out / "inject_report.md").read_text())
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
