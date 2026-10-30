"""Read-only access to stored run folders inside .tgz packages (no extraction to disk).

The BiFeO3 6D campaign keeps its inputs as data/bfo6d_production_inputs.tgz and bfo6d_extra_inputs.tgz on the
Mac (the folders were transferred to Perlmutter and are not unpacked locally). IRIS reads members straight from
the archives: point_info.json, manifest.json, orbits.npz (and, in B3, POSCAR / INCAR / KPOINTS).
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import numpy as np

_CACHE: dict = {}


class TarStore:
    """All small members of one or more archives, loaded once into memory (the production package is 6 MB
    compressed; members are a few kB each). Keys are archive member names without a leading './'."""

    def __init__(self, archives: list[str | Path], suffixes=("point_info.json", "manifest.json", "orbits.npz",
                                                          "POSCAR", "INCAR", "KPOINTS")):
        self.archives = [str(a) for a in archives]
        self.data: dict[str, bytes] = {}
        for a in self.archives:
            with tarfile.open(a, "r:gz") as tf:
                for m in tf:
                    if m.isfile() and m.name.rsplit("/", 1)[-1] in suffixes:
                        self.data[m.name.lstrip("./")] = tf.extractfile(m).read()

    def json(self, name: str):
        return json.loads(self.data[name])

    def npz(self, name: str):
        return np.load(io.BytesIO(self.data[name]))

    def text(self, name: str) -> str:
        return self.data[name].decode()

    def folders(self, prefix: str, leaf: str = "point_info.json") -> list[str]:
        """Run folders under prefix (any depth) that contain `leaf`, sorted."""
        p = prefix.rstrip("/") + "/"
        return sorted(k[: -len(leaf) - 1] for k in self.data if k.startswith(p) and k.endswith("/" + leaf))


def open_store(archives) -> TarStore:
    key = tuple(str(a) for a in archives)
    if key not in _CACHE:
        _CACHE[key] = TarStore(archives)
    return _CACHE[key]
