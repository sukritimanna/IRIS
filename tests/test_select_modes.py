"""R1-R5 + primary labelling (Methods 4.2, agreed 16 Oct)."""
from iris_agent.rules.select_modes import select, sg_is_polar


def _run(c, t):
    return select(c["As"], {s["irrep"]: s["amplitude"] for s in c["strain"]}, t,
                  a_thr=0.05, r5_margin=0.1, polar_irreps=set(c["polar_modes"]))


def test_cssni3_matches_paper(cssni3_step3):
    out = _run(*cssni3_step3)
    assert out["code"] == "OK"
    assert out["primaries"] == ["M3+", "R4+"]          # #127 then #127 ∩ #74 = #62
    assert out["active"] == ["M3+", "R4+"]
    assert out["held_at_zero"] == ["R5+", "X5+"]       # secondaries above A_thr, held by R2
    assert out["c1_generates_H"] and out["c1_intersection_sg"] == 62
    by = {r["irrep"]: r for r in out["irreps"]}
    assert by["M3+"]["isotropy_sg"] == 127 and by["R4+"]["isotropy_sg"] == 74
    assert by["X5+"]["isotropy_sg"] == 63
    assert not by["M2+"]["active"] and any("below A_thr" in x for x in by["M2+"]["rules"])
    assert all(by[s]["role"] == "strain" and not by[s]["active"] for s in ("GM1+", "GM3+", "GM5+"))
    assert abs(out["r5_gap"] - (0.4572 - 0.1721)) < 1e-9        # no R5: 0.285 > 0.1
    assert all(r["rules"] for r in out["irreps"])                 # every irrep says why


def _tree(parent, child, nodes):
    return {"parent": parent, "child": child,
            "chain": [{"sg": sg, "i": i, "order_parameters": ops} for sg, i, ops in nodes]}


def test_r3_fail_when_list_runs_out():
    # no tree node contains {A, B}: the walk cannot reach H
    t = _tree(100, 50, [(100, 1, ""), (80, 2, "A"), (70, 2, "B"), (50, 8, "A, C")])
    out = select({"A": 0.5, "B": 0.3}, {}, t, a_thr=0.05, r5_margin=0.1)
    assert out["code"] == "R3_FAIL"


def test_r3_adds_subthreshold_primary():
    # H needs B, but B is below A_thr -> R3 adds it
    t = _tree(100, 50, [(100, 1, ""), (80, 2, "A"), (70, 2, "B"), (50, 4, "A, B")])
    out = select({"A": 0.5, "B": 0.03}, {}, t, a_thr=0.05, r5_margin=0.01)
    assert out["code"] == "OK" and out["active"] == ["A", "B"]
    assert any("R3" in r for r in next(x for x in out["irreps"] if x["irrep"] == "B")["rules"])


def test_r4_and_r5_hexagonal_manganite_pattern():
    # synthetic numbers shaped like InMnO3 (Methods example): K3 primary alone reaches #185;
    # GM2- is a secondary kept by R4 (polar child); margin 0.101 - 0.023 = 0.078 < 0.1 -> R5
    t = _tree(194, 185, [(194, 1, "GM1+"), (186, 2, "GM1+, GM2-"), (193, 3, "GM1+, K1"),
                         (185, 6, "GM1+, K1, K3, GM2-")])
    assert sg_is_polar(185) and not sg_is_polar(194)
    out = select({"K3": 1.3, "GM2-": 0.101, "K1": 0.023}, {"GM1+": 0.01}, t,
                 a_thr=0.05, r5_margin=0.1, polar_irreps={"GM2-"})
    assert out["primaries"] == ["K3"]
    assert out["active"] == ["K3", "GM2-"]
    by = {r["irrep"]: r for r in out["irreps"]}
    assert by["GM2-"]["role"] == "secondary" and any("R4" in x for x in by["GM2-"]["rules"])
    assert out["code"] == "R5_BORDERLINE" and abs(out["r5_gap"] - 0.078) < 1e-9
    assert set(out["borderline"]) == {"GM2-", "K1"}


def test_hold_at_zero_overrides_R4_and_is_recorded():
    from iris_agent.rules.select_modes import select
    tree = {"parent": 139, "child": 36, "chain": [
        {"sg": 42, "i": 4, "order_parameters": "GM5-"}, {"sg": 64, "i": 4, "order_parameters": "X2+"},
        {"sg": 63, "i": 4, "order_parameters": "X3-"}, {"sg": 36, "i": 8, "order_parameters": "GM5-, X2+, X3-"}]}
    amps = {"X3-": 1.163, "GM5-": 0.559, "X2+": 0.847}
    base = select(amps, {}, tree, a_thr=0.05, r5_margin=0.1, polar_irreps={"GM5-"})
    assert base["primaries"] == ["X3-", "X2+"] and "GM5-" in base["active"]          # R4 adds the polar axis
    held = select(amps, {}, tree, a_thr=0.05, r5_margin=0.1, polar_irreps={"GM5-"},
                  hold_at_zero=("GM5-",), hold_reason="manuscript plane")
    assert held["active"] == ["X3-", "X2+"] and held["held_at_zero"] == ["GM5-"]
    assert held["policy_overrides"][0]["rule"] == "R4" and held["code"] == "OK"


def _mn_tree():
    return _tree(194, 185, [(194, 1, "GM1+"), (186, 2, "GM1+, GM2-"), (193, 3, "GM1+, K1"),
                            (185, 6, "GM1+, K1, K3, GM2-")])


def test_r5_decision_is_applied_to_the_active_set():
    """R5 operational: include keeps the borderline active irrep as an axis and adds nothing; exclude removes it and
    holds it at zero (K3 alone still generates #185); anchor_only does the same and asks for an anchor frame."""
    amps = {"K3": 1.3, "GM2-": 0.101, "K1": 0.023}
    kw = dict(a_thr=0.05, r5_margin=0.1, polar_irreps={"GM2-"})
    inc = select(amps, {"GM1+": 0.01}, _mn_tree(), r5_decision="include", **kw)
    assert inc["code"] == "OK" and inc["active"] == ["K3", "GM2-"] and inc["r5_decision"] == "include"
    assert inc["r5_anchors"] == [] and set(inc["borderline"]) == {"GM2-", "K1"}
    exc = select(amps, {"GM1+": 0.01}, _mn_tree(), r5_decision="exclude", **kw)
    assert exc["code"] == "OK" and exc["active"] == ["K3"] and exc["c1_generates_H"]
    assert "GM2-" in exc["held_at_zero"] and exc["policy_overrides"][0]["rule"] == "R5"
    anc = select(amps, {"GM1+": 0.01}, _mn_tree(), r5_decision="anchor_only", **kw)
    assert anc["active"] == ["K3"] and anc["r5_anchors"] == ["GM2-"]
    # the same case without a decision still stops at R5_BORDERLINE
    assert select(amps, {"GM1+": 0.01}, _mn_tree(), **kw)["code"] == "R5_BORDERLINE"


def test_r5_exclude_that_breaks_H_fails():
    # here B is the borderline active irrep and H needs it: exclude must fail, not silently build a wrong grid
    t = _tree(100, 50, [(100, 1, ""), (80, 2, "A"), (70, 2, "B"), (50, 4, "A, B")])
    out = select({"A": 0.5, "B": 0.12, "C": 0.05}, {}, t, a_thr=0.05, r5_margin=0.1)
    assert out["code"] == "R5_BORDERLINE" and set(out["borderline"]) == {"B", "C"}
    bad = select({"A": 0.5, "B": 0.12, "C": 0.05}, {}, t, a_thr=0.05, r5_margin=0.1, r5_decision="exclude")
    assert bad["code"] == "R5_EXCLUDE_BREAKS_H" and bad["active"] == ["A"]
