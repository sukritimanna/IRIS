"""Stage 1.7 cross-check: number of distinct grid points of the 3D Gamma4- grid under Oh
(48 signed permutations), by direct enumeration and by Burnside's lemma. Expect 165 for 17 points/axis."""
import itertools, sys
n = int(sys.argv[1]) if len(sys.argv) > 1 else 17
h = n // 2; pts = range(-h, h + 1)
ops = [(perm, s) for perm in itertools.permutations(range(3)) for s in itertools.product((1, -1), repeat=3)]
canon = {tuple(sorted((abs(v) for v in p), reverse=True)) for p in itertools.product(pts, repeat=3)}
fixed = sum(sum(1 for p in itertools.product(pts, repeat=3) if tuple(s[i] * p[perm[i]] for i in range(3)) == p) for perm, s in ops)
print(f'{n} points/axis: {n**3} nodes, {len(canon)} orbits (enumeration), {fixed // len(ops)} (Burnside)')
