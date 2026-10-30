"""Parser and vector builder for the stored ISODISTORT responses (fixtures copied from the 12 Sep run)."""
import numpy as np
import pytest

from iris_agent.engines.stored_isodistort import StoredIsodistort, free_components

from .conftest import FIX


@pytest.fixture(scope="module")
def iso():
    return StoredIsodistort(FIX / "04_raw_isodistort")


def test_subgroup_string(iso):
    sub = iso.subgroup()
    assert sub["sg"] == 62 and sub["s"] == 4 and sub["i"] == 24
    assert sub["basis"] == [[1, 0, -1], [0, 2, 0], [1, 0, 1]] and sub["origin"] == [0, 0, 0]
    assert round(np.linalg.det(np.array(sub["basis"]))) == sub["s"]


def test_isotropy_and_dimensions(iso):
    t = iso.isotropy_by_irrep()
    disp = {k: v["sg"] for k, v in t.items() if not k.startswith("GM")}
    assert disp == {"R4+": 74, "R5+": 74, "X5+": 63, "M2+": 127, "M3+": 127}
    assert {k: v["sg"] for k, v in t.items() if k.startswith("GM")} == {"GM1+": 221, "GM3+": 123, "GM5+": 65}
    assert free_components(t["M3+"]["direction"]) == 1 and free_components(t["R4+"]["direction"]) == 1
    assert free_components("(a,b,0)") == 2


def test_vectors_reproduce_isodistort_amplitudes(iso):
    r0, fields, groups = iso.irrep_fields()
    L = r0.lattice.matrix
    assert len(r0) == 20 and r0.lattice.abc == pytest.approx((8.89007, 12.57246, 8.89007))
    As = {"M3+": 1.68616, "R4+": 0.45721, "R5+": 0.17211, "X5+": 0.08956, "M2+": 0.00604}
    for ir, a in As.items():
        assert np.linalg.norm(fields[ir] @ L) == pytest.approx(a, abs=2e-4)
        assert np.abs(fields[ir].mean(axis=0)).max() < 1e-12          # zone-boundary: no translation
    assert np.linalg.norm(fields["M3+"] @ L, axis=1).max() == pytest.approx(0.59615, abs=1e-4)   # ISODISTORT dmax
    assert iso.max_displacement() == pytest.approx(0.59292)


def test_single_mode_frames_have_isotropy_symmetry(iso):
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    r0, fields, _ = iso.irrep_fields()
    for ir, sg in (("M3+", 127), ("R4+", 74), ("X5+", 63)):
        s = r0.copy()
        for j in range(len(s)):
            s.replace(j, s[j].species, r0.frac_coords[j] + fields[ir][j])
        assert SpacegroupAnalyzer(s, symprec=1e-2).get_space_group_number() == sg
