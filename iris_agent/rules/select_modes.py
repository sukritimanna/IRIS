"""Mode selection for f2 (Methods 4.2, rules R1-R5, check c1). Pure, deterministic.

Primary/secondary labelling (agreed 16 Oct): walk the displacive irreps in order of decreasing
A_s; add an irrep to the primaries only if its isotropy subgroup lowers the symmetry of the running
intersection; stop when the intersection equals H. All other displacive irreps are secondaries.
If the list runs out before H, R3 fails (code R3_FAIL -> recover -> sub-agent/human).

Group intersections are read from the ISODISTORT subgroup tree (step-3 subgroup_tree.json): each
node lists its order parameters, and the intersection of the isotropy subgroups of a set S of
displacive irreps is the highest-symmetry (lowest-index) node whose displacive order parameters
contain S. The built-frame route (spglib on r0 + sum Q_i e_i) cross-checks this in G2 (step 2).

Then:
  R1  strain irreps never become axes (strain policy).
  R2  a primary with A >= A_thr is active; a secondary is held at 0 even above A_thr.
  R3  the active set must generate H; else add the largest sub-threshold primary that restores H.
  R4  a polar child keeps at least one polar irrep (the largest polar one, as polarization axis).
  R5  if min(active A) - max(inactive A) < margin, the selection is borderline -> sub-agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# space groups with a polar point group (1, 2, m, mm2, 4, 4mm, 3, 3m, 6, 6mm)
_POLAR_RANGES = [(1, 1), (3, 9), (25, 46), (75, 80), (99, 110), (143, 146), (156, 161),
                 (168, 173), (183, 186)]


def sg_is_polar(sg: int) -> bool:
    return any(lo <= sg <= hi for lo, hi in _POLAR_RANGES)


@dataclass
class TreeNode:
    sg: int
    index: int
    ops: frozenset          # displacive order parameters only (strain irreps removed)


@dataclass
class IrrepRecord:
    irrep: str
    amplitude: float
    kind: str               # displacive | strain
    role: str = ""          # primary | secondary | strain
    polar: bool = False
    active: bool = False
    isotropy_sg: int | None = None
    rules: list = field(default_factory=list)


def parse_tree(tree: dict, strain_irreps: set[str]) -> tuple[int, int, list[TreeNode]]:
    nodes = []
    for n in tree["chain"]:
        ops = {o.strip() for o in n["order_parameters"].split(",") if o.strip()}
        nodes.append(TreeNode(sg=n["sg"], index=int(n["i"]), ops=frozenset(ops - strain_irreps)))
    return tree["parent"], tree["child"], nodes


def intersection(S: set[str], nodes: list[TreeNode], parent_sg: int) -> TreeNode | None:
    """Highest-symmetry tree node whose displacive order parameters contain S (S empty -> G)."""
    if not S:
        return TreeNode(sg=parent_sg, index=1, ops=frozenset())
    cands = [n for n in nodes if S <= n.ops]
    return min(cands, key=lambda n: (n.index, len(n.ops))) if cands else None


def isotropy(irrep: str, nodes: list[TreeNode]) -> TreeNode | None:
    cands = [n for n in nodes if irrep in n.ops]
    return min(cands, key=lambda n: (len(n.ops), n.index)) if cands else None


def select(amplitudes: dict[str, float], strain: dict[str, float], tree: dict, *,
           a_thr: float, r5_margin: float, polar_irreps: set[str] = frozenset(),
           hold_at_zero: tuple = (), hold_reason: str = "", r5_decision: str | None = None) -> dict:
    """amplitudes: displacive irrep -> A (the policy basis); strain: strain irrep -> amplitude.
    r5_decision: None (a borderline selection stops with R5_BORDERLINE) or the recorded answer include / exclude /
    anchor_only, applied to the borderline irreps (see the R5 block).

    hold_at_zero: irreps the run's policy keeps at 0 whatever R2-R4 say (recorded with its reason in
    `policy_overrides`). Used for Ca3Ti2O7, where the manuscript plane holds the polar GM5- at 0 and
    R4 would otherwise add it as a third axis."""
    # an irrep with both displacive modes and strain (HfO2 T3 GM5+, T5 GM3+) is displacive here: only pure-strain
    # irreps are removed from the tree's order parameters and recorded as strain (R1)
    pure_strain = {i: a for i, a in strain.items() if i not in amplitudes}
    parent_sg, child_sg, nodes = parse_tree(tree, set(pure_strain))
    child_node = max(nodes, key=lambda n: n.index)
    H_index = child_node.index
    recs = {i: IrrepRecord(i, a, "displacive", polar=i in polar_irreps) for i, a in amplitudes.items()}
    for i, a in pure_strain.items():
        recs[i] = IrrepRecord(i, a, "strain", role="strain", rules=["R1: strain irrep, never an axis"])
    for r in recs.values():
        if r.kind == "displacive":
            iso = isotropy(r.irrep, nodes)
            r.isotropy_sg = iso.sg if iso else None

    # ---- primary / secondary labelling ------------------------------------------------------
    order = sorted((r for r in recs.values() if r.kind == "displacive"), key=lambda r: -r.amplitude)
    primaries, running = [], intersection(set(), nodes, parent_sg)
    reached_H, walked = False, set()
    for r in order:
        if reached_H:
            break
        walked.add(r.irrep)
        new = intersection(set(primaries) | {r.irrep}, nodes, parent_sg)
        if new is not None and new.index > running.index:
            primaries.append(r.irrep)
            r.rules.append(f"primary: lowers running intersection #{running.sg} -> #{new.sg}")
            running = new
            reached_H = new.index == H_index and new.sg == child_sg
    for r in order:
        if r.irrep in primaries:
            r.role = "primary"
        else:
            r.role = "secondary"
            r.rules.append("secondary: does not lower the running intersection" if r.irrep in walked
                           else "secondary: H already reached by the primaries")

    out = {"parent_sg": parent_sg, "child_sg": child_sg, "a_thr": a_thr, "r5_margin": r5_margin,
           "primaries": primaries, "status": "OK", "code": "OK", "detail": ""}
    if not reached_H:
        out.update(status="FAIL", code="R3_FAIL",
                   detail=f"primaries {primaries} reach #{running.sg}, not H = #{child_sg}; list exhausted")

    # ---- R2: primaries above threshold are active; secondaries are held at 0 ----------------
    for r in order:
        if r.role == "primary" and r.amplitude >= a_thr:
            r.active = True
            r.rules.append(f"R2: primary, A={r.amplitude:.4f} >= A_thr={a_thr} -> axis")
        elif r.role == "primary":
            r.rules.append(f"R2: primary below A_thr ({r.amplitude:.4f} < {a_thr})")
        elif r.amplitude >= a_thr:
            r.rules.append(f"R2: secondary above A_thr ({r.amplitude:.4f}) -> held at 0 (D4 scan if coupling matters)")
        else:
            r.rules.append(f"below A_thr ({r.amplitude:.4f} < {a_thr}) -> out")

    # ---- R3: active set must generate H ----------------------------------------------------
    active = {r.irrep for r in order if r.active}
    gen = intersection(active, nodes, parent_sg)
    if out["code"] == "OK" and not (gen and gen.sg == child_sg and gen.index == H_index):
        for r in [x for x in order if x.role == "primary" and not x.active]:   # largest first
            trial = intersection(active | {r.irrep}, nodes, parent_sg)
            r.active = True
            active.add(r.irrep)
            r.rules.append("R3: added (largest sub-threshold primary) to restore H")
            if trial and trial.sg == child_sg and trial.index == H_index:
                gen = trial
                break
        else:
            out.update(status="FAIL", code="R3_FAIL", detail=f"active set {sorted(active)} does not generate H")

    # ---- R4: polar child keeps a polar irrep -------------------------------------------------
    overrides = []
    if sg_is_polar(child_sg) and not any(recs[i].polar for i in active):
        polar = [r for r in order if r.polar]
        if polar and polar[0].irrep in hold_at_zero:
            p = polar[0]
            p.rules.append(f"R4 overridden: policy.hold_at_zero keeps {p.irrep} at 0 ({hold_reason or 'no reason given'})")
            overrides.append({"rule": "R4", "irrep": p.irrep, "action": "held at 0 instead of added as axis",
                              "reason": hold_reason})
        elif polar:
            p = polar[0]
            p.active = True
            active.add(p.irrep)
            p.rules.append("R4: polar child -> kept as polarization axis")
        else:
            out.update(status="FAIL", code="R4_NO_POLAR", detail="polar child but no polar irrep in the decomposition")

    # ---- policy: hold_at_zero wins over R2/R3 too (an active held irrep is removed and recorded)
    for r in order:
        if r.irrep in hold_at_zero and r.active:
            r.active = False
            active.discard(r.irrep)
            r.rules.append(f"policy.hold_at_zero: removed from the axes ({hold_reason or 'no reason given'})")
            overrides.append({"rule": "R2/R3", "irrep": r.irrep, "action": "removed from axes", "reason": hold_reason})
    out["policy_overrides"] = overrides

    # ---- R5: borderline margin ---------------------------------------------------------------
    act = [r.amplitude for r in order if r.active]
    inact = [r.amplitude for r in order if not r.active]
    margin = (min(act) - max(inact)) if act and inact else None
    out["r5_gap"] = None if margin is None else round(margin, 6)
    out["r5_decision"] = None
    out["r5_anchors"] = []
    if out["code"] == "OK" and margin is not None and margin < r5_margin:
        lo, hi = max(inact), min(act)
        out["borderline"] = sorted(r.irrep for r in order
                                   if (r.active and r.amplitude < lo + r5_margin)
                                   or (not r.active and r.amplitude > hi - r5_margin))
        if r5_decision is None:
            out.update(status="BORDERLINE", code="R5_BORDERLINE",
                       detail=f"smallest active exceeds largest inactive by {margin:.3f} < {r5_margin} A")
        else:
            # the recorded answer (human or sub-agent) is applied here, so that f2 builds the grid on it, G2
            # checks it and f6 re-derives it:
            #   include      the borderline irreps that the rules made active stay axes; the borderline irreps
            #                below A_thr stay out (the rules' selection is confirmed)
            #   exclude      the borderline active irreps are removed from the axes and held at zero
            #   anchor_only  as exclude, and one anchor frame per removed irrep at the child amplitudes, so
            #                that the energy the irrep releases at the child is measured and reported
            if r5_decision not in ("include", "exclude", "anchor_only"):
                raise ValueError(f"unknown R5 decision {r5_decision!r}")
            out["r5_decision"] = r5_decision
            b_act = [r for r in order if r.active and r.irrep in out["borderline"]]
            if r5_decision == "include":
                for r in b_act:
                    r.rules.append("R5: include -> kept as an axis (decision recorded)")
                for r in order:
                    if not r.active and r.irrep in out["borderline"]:
                        r.rules.append("R5: include -> stays out (below A_thr; the rules' selection is confirmed)")
            else:
                for r in b_act:
                    r.active = False
                    active.discard(r.irrep)
                    r.rules.append(f"R5: {r5_decision} -> removed from the axes, held at zero")
                    overrides.append({"rule": "R5", "irrep": r.irrep, "action": "removed from axes", "reason": r5_decision})
                if r5_decision == "anchor_only":
                    out["r5_anchors"] = [r.irrep for r in b_act]

    # ---- c1 ---------------------------------------------------------------------------------
    gen = intersection(active, nodes, parent_sg)
    out["c1_generates_H"] = bool(gen and gen.sg == child_sg and gen.index == H_index)
    if out["code"] == "OK" and out["r5_decision"] in ("exclude", "anchor_only") and not out["c1_generates_H"]:
        out.update(status="FAIL", code="R5_EXCLUDE_BREAKS_H",
                   detail=f"after R5 {out['r5_decision']}, the active set {sorted(active)} no longer generates H")
    out["c1_intersection_sg"] = gen.sg if gen else None
    out["active"] = [r.irrep for r in order if r.active]
    r5_removed = {o["irrep"] for o in overrides if o["rule"] == "R5"}
    out["held_at_zero"] = [r.irrep for r in order if not r.active and r.amplitude >= a_thr
                           and (r.role == "secondary" or r.irrep in hold_at_zero or r.irrep in r5_removed)]
    out["irreps"] = [asdict(recs[i]) for i in [r.irrep for r in order] + list(pure_strain)]
    return out


def amplitudes_for_policy(irreps: dict, basis: str) -> dict[str, float]:
    """The amplitudes the walk runs on. As_tf = A_s of the translation-free vector (f1 adds it);
    an irrep without that field (no translation computed) falls back to A_s."""
    if basis == "As_tf":
        return {i: abs(v.get("As_tf", v["As"])) for i, v in irreps.items()}
    return {i: abs(v[basis]) for i, v in irreps.items()}


def select_for(dec: dict, pol: dict, r5_decision: str | None = None) -> dict:
    """select() with the run policy, as f2 and f6 both call it; r5_decision is the recorded answer to R5_BORDERLINE
    (state.overrides.f2.r5_decision), applied inside the rules so that f2, G2 and f6 see one active set."""
    irreps = dec["irreps"]
    return select(amplitudes_for_policy(irreps, pol["amplitude_basis"]), dec["strain"], dec["tree"],
                  a_thr=pol["a_thr"], r5_margin=pol["r5_margin"],
                  polar_irreps={i for i in irreps if i.startswith("GM") and i.endswith("-")},
                  hold_at_zero=tuple(pol.get("hold_at_zero") or ()),
                  hold_reason=pol.get("hold_at_zero_reason", ""), r5_decision=r5_decision)
