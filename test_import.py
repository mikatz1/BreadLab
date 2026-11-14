"""회로도 가져오기(Falstad CircuitJS) 시험.

circuits_web/ 의 회로도 41개(인터넷에서 받은 교육용 예제)를 모두
읽기 → BreadLab 부품으로 바꾸기 → 브레드보드에 배치 → 연결 검증 → 시뮬레이션 하고,
몇몇 회로는 값까지 확인합니다.
"""
from pathlib import Path
import unittest

import numpy as np

from circuit_core import Simulator, make_document, net_map, validate_document
from circuit_import import GND, import_falstad, make_plan, parse_falstad, place, verify

WEB = Path(__file__).with_name('circuits_web')
FILES = sorted(WEB.glob('*.txt'))


def load(name):
    text = (WEB / f'{name}.txt').read_text(encoding='utf-8')
    plan = make_plan(parse_falstad(text))
    parts, inst = place(plan)
    nm = net_map(parts, inst['leads'])
    board = {}
    by_kind = {}
    for p in parts:
        by_kind.setdefault(p.kind, []).append(p)
    used = {}
    for c in plan.comps:
        p = by_kind[c.kind][used.get(c.kind, 0)]
        used[c.kind] = used.get(c.kind, 0) + 1
        for n, h in zip(c.posts, p.pins()):
            if n is not None:
                board.setdefault(n, nm[h])
    return plan, parts, inst, board


def volt(result, inst, parts, board_net):
    nm = net_map(parts, inst['leads'])
    for h, v in result['nodes'].items():
        if nm[h] == board_net:
            return v
    return None


class AllCircuits(unittest.TestCase):
    def test_at_least_20_circuits(self):
        self.assertGreaterEqual(len(FILES), 20)

    def test_every_circuit_imports_places_and_runs(self):
        for f in FILES:
            with self.subTest(f.stem):
                parts, inst, notes = import_falstad(f.read_text(encoding='utf-8'))
                validate_document(make_document(parts, inst))          # 파일로 저장해도 다시 열림
                sim = Simulator()
                r, _ = sim.step(parts, inst, 1e-4, 60)
                self.assertTrue(r['ok'], f'{f.stem}: {r["warnings"]}')

    def test_connectivity_matches_original(self):
        for f in FILES:
            with self.subTest(f.stem):
                plan = make_plan(parse_falstad(f.read_text(encoding='utf-8')))
                parts, inst = place(plan)
                self.assertEqual(verify(plan, parts, inst), [])

    def test_no_hole_used_twice(self):
        for f in FILES:
            with self.subTest(f.stem):
                parts, inst, _ = import_falstad(f.read_text(encoding='utf-8'))
                holes = [h for p in parts for h in p.pins()]
                self.assertEqual(len(holes), len(set(holes)), f.stem)


class Parsing(unittest.TestCase):
    def test_transistor_pins_from_geometry(self):
        nl = parse_falstad((WEB / 'transswitch.txt').read_text(encoding='utf-8'))
        q = next(c for c in nl.comps if c.kind == 'npn')
        r300 = next(c for c in nl.comps if c.kind == 'resistor' and c.props['value'] == 300)
        self.assertIn(q.posts[0], r300.posts)            # 컬렉터에 300 Ω
        self.assertEqual(nl.dangling, [])

    def test_555_pins_from_chip_geometry(self):
        nl = parse_falstad((WEB / '555square.txt').read_text(encoding='utf-8'))
        t = next(c for c in nl.comps if c.kind == 'timer555')
        self.assertEqual(len(t.posts), 8)
        plan = make_plan(nl)
        u = next(c for c in plan.comps if c.kind == 'timer555')
        self.assertEqual(u.posts[0], plan.ground)       # 1번 GND
        self.assertEqual(u.posts[7], plan.ch1[0])       # 8번 VCC = 전원 +

    def test_opamp_gets_hidden_supplies(self):
        plan = make_plan(parse_falstad((WEB / 'amp-invert.txt').read_text(encoding='utf-8')))
        self.assertIsNotNone(plan.fg)
        self.assertAlmostEqual(plan.ch1[2], 15)
        self.assertAlmostEqual(plan.ch2[2], 15)
        self.assertEqual(plan.ch2[0], plan.ground)       # CH2를 거꾸로 써서 −15 V


def reference_dc(plan):
    """원래 넷리스트를 따로 풀어 본 직류 마디 전압(저항·스위치·직류 전원만)."""
    nets = sorted({n for c in plan.comps for n in c.posts if n is not None} |
                  {n for s in (plan.ch1, plan.ch2) if s for n in s[:2]})
    ref = plan.ground
    unknown = [n for n in nets if n != ref]
    ix = {n: i for i, n in enumerate(unknown)}
    srcs = [s for s in (plan.ch1, plan.ch2) if s] + [(c.posts[0], c.posts[1], c.props['value'])
                                                     for c in plan.comps if c.kind == 'battery']
    size = len(unknown) + len(srcs)
    A = np.zeros((size, size))
    z = np.zeros(size)

    def g(a, b, val):
        for x, y, s in ((a, a, 1), (b, b, 1), (a, b, -1), (b, a, -1)):
            if x in ix and y in ix:
                A[ix[x], ix[y]] += s * val
    for c in plan.comps:
        if c.kind == 'resistor':
            g(c.posts[0], c.posts[1], 1 / c.props['value'])
        elif c.kind == 'switch':
            g(c.posts[0], c.posts[1], 1 / 0.05 if c.props['closed'] else 1e-12)
        elif c.kind == 'pot':
            rt, w = c.props['value'], c.props['pos'] / 100
            g(c.posts[0], c.posts[1], 1 / max(rt * w, 0.5))
            g(c.posts[1], c.posts[2], 1 / max(rt * (1 - w), 0.5))
    for k, (pos, neg, v) in enumerate(srcs):
        r = len(unknown) + k
        for n, s in ((pos, 1), (neg, -1)):
            if n in ix:
                A[ix[n], r] += s
                A[r, ix[n]] += s
        z[r] = v
    A += np.eye(size) * 1e-12
    x = np.linalg.solve(A, z)
    out = {n: x[ix[n]] for n in unknown}
    out[ref] = 0.0
    return out


class Values(unittest.TestCase):
    def test_resistive_circuits_match_independent_solve(self):
        for name in ('ohms', 'voltdivide', 'wheatstone', 'resistors', 'potdivide'):
            with self.subTest(name):
                plan, parts, inst, board = load(name)
                ref = reference_dc(plan)
                sim = Simulator()
                r, _ = sim.step(parts, inst, 1e-3, 30)
                for n, v in ref.items():
                    got = volt(r, inst, parts, board[n]) if n in board else None
                    if got is None:
                        continue
                    self.assertAlmostEqual(got, v, delta=max(0.01, abs(v) * 0.003), msg=f'{name} {n}')

    def test_zener_reference(self):
        plan, parts, inst, board = load('zenerref')
        r, _ = Simulator().step(parts, inst, 1e-3, 20)
        z = next(c for c in plan.comps if c.kind == 'zener')
        vz = abs(volt(r, inst, parts, board[z.posts[0]]) - volt(r, inst, parts, board[z.posts[1]]))
        self.assertAlmostEqual(vz, z.props['value'], delta=0.3)

    def _amp(self, name):
        plan, parts, inst, board = load(name)
        u = next(c for c in plan.comps if c.kind == 'opamp')
        sim = Simulator()
        pairs = []
        for _ in range(250):
            r, _s = sim.step(parts, inst, 1e-4, 1)
            vin = volt(r, inst, parts, board[plan.fg[0]])
            vout = volt(r, inst, parts, board[u.posts[5]])
            pairs.append((vin, vout))
        return pairs

    def test_follower_tracks_input(self):
        for vin, vout in self._amp('amp-follower'):
            if abs(vin) < 10:
                self.assertAlmostEqual(vout, vin, delta=0.05)

    def test_inverting_gain(self):
        ok = 0
        for vin, vout in self._amp('amp-invert'):
            if 0.5 < abs(vin) < 4:
                self.assertAlmostEqual(vout / vin, -3.0, delta=0.05)
                ok += 1
        self.assertGreater(ok, 20)

    def test_555_oscillates(self):
        plan, parts, inst, board = load('555square')
        sim = Simulator()
        states = []
        for _ in range(400):
            r, _s = sim.step(parts, inst, 2e-3, 1)
            u = next(p for p in parts if p.kind == 'timer555')
            states.append(r['parts'][u.id]['state'])
        flips = sum(1 for a, b in zip(states, states[1:]) if a != b)
        self.assertGreaterEqual(flips, 4)

    def test_astable_multivibrator_oscillates(self):
        plan, parts, inst, board = load('multivib-a')
        q = next(c for c in plan.comps if c.kind == 'npn')
        sim = Simulator()
        vs = []
        for _ in range(300):
            r, _s = sim.step(parts, inst, 2e-3, 1)
            vs.append(volt(r, inst, parts, board[q.posts[0]]))
        self.assertGreater(max(vs[50:]) - min(vs[50:]), 2.0)

    def test_half_wave_rectifier(self):
        plan, parts, inst, board = load('rectify')
        d = next(c for c in plan.comps if c.kind == 'diode')
        sim = Simulator()
        outs = []
        for _ in range(400):
            r, _s = sim.step(parts, inst, 1e-4, 1)
            outs.append(volt(r, inst, parts, board[d.posts[1]]))
        self.assertGreater(max(outs), 3.0)
        self.assertGreater(min(outs), -0.1)

    def test_lc_rings(self):
        plan, parts, inst, board = load('lrc')
        cap = next(c for c in plan.comps if c.kind == 'capacitor')
        for p in parts:                       # 원래 회로처럼 스위치를 닫아 충전된 커패시터를 코일에 잇습니다
            if p.kind == 'switch':
                p.closed = True
        sim = Simulator()
        vs = []
        for _ in range(600):
            r, _s = sim.step(parts, inst, 2e-5, 1)
            a = volt(r, inst, parts, board[cap.posts[0]])
            b = volt(r, inst, parts, board[cap.posts[1]])
            if a is not None and b is not None:
                vs.append(a - b)
        self.assertTrue(vs)
        self.assertGreater(max(vs) - min(vs), 0.5)


if __name__ == '__main__':
    unittest.main()
