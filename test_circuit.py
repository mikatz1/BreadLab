import json
import math
import unittest

from circuit_core import (Part, Simulator, dc, default_instruments, designators, format_si, fg_value,
                          make_document, net_map, parse_beta, parse_capacitance, parse_resistance,
                          resistor_bands, validate_document, BLACK, RED, WHITE)
from examples import EXAMPLES


def psu(*rows):
    """CH1 +를 t0:0 줄에, CH1 −를 t0:2 줄에 연결한 부품 목록."""
    return [Part(100, 'wire', 'p:1+', 't4:0', color=RED), Part(101, 'wire', 'p:1-', 't4:2', color=BLACK)] + list(rows)


def run(parts, v=5.0, limit=1.0):
    return dc(psu(*parts), voltage=v, limit=limit)


class Units(unittest.TestCase):
    def test_resistance(self):
        self.assertEqual(parse_resistance('1MΩ'), 1e6)
        self.assertEqual(parse_resistance('4.7k'), 4700)
        self.assertEqual(parse_resistance('4.7K'), 4700)
        self.assertAlmostEqual(parse_resistance('10m'), 0.01)
        with self.assertRaises(ValueError):
            parse_resistance('abc')

    def test_capacitance_and_beta(self):
        self.assertAlmostEqual(parse_capacitance('1000uF'), 1e-3)
        self.assertAlmostEqual(parse_capacitance('4.7µ'), 4.7e-6)
        self.assertAlmostEqual(parse_capacitance('10n'), 1e-8)
        self.assertAlmostEqual(parse_capacitance('0.001'), 1e-3)
        with self.assertRaises(ValueError):
            parse_capacitance('2')
        with self.assertRaises(ValueError):
            parse_beta('5')

    def test_format(self):
        self.assertEqual(format_si(1000), '1 kΩ')
        self.assertEqual(format_si(1e6), '1 MΩ')
        self.assertEqual(format_si(2e-11, 'A'), '0 A')

    def test_bands(self):
        self.assertEqual(resistor_bands(1000), (1, 0, 2))
        self.assertEqual(resistor_bands(4700), (4, 7, 2))
        self.assertEqual(resistor_bands(100e3), (1, 0, 4))   # 갈색 검정 노랑
        self.assertEqual(resistor_bands(1e6), (1, 0, 5))     # 갈색 검정 초록
        self.assertEqual(resistor_bands(330), (3, 3, 1))
        self.assertEqual(resistor_bands(10), (1, 0, 0))
        self.assertEqual(resistor_bands(999.6), (1, 0, 2))
        self.assertIsNone(resistor_bands(0.01))

    def test_designators(self):
        tags = designators([Part(3, 'resistor', 'a', 'b'), Part(1, 'resistor', 'a', 'b'), Part(2, 'npn', 'a', 'b')])
        self.assertEqual(tags, {1: 'R1', 2: 'Q1', 3: 'R2'})


class DC(unittest.TestCase):
    def test_resistor(self):
        r = run([Part(1, 'resistor', 't1:0', 't1:2', 1000)])
        self.assertAlmostEqual(r['psu']['ch1']['current'], .005, places=7)
        self.assertEqual(r['psu']['ch1']['mode'], 'CV')

    def test_series_parallel(self):
        r = run([Part(1, 'resistor', 't1:0', 't1:1', 1000), Part(2, 'resistor', 't2:1', 't1:2', 1000)])
        self.assertAlmostEqual(r['psu']['ch1']['current'], .0025, places=7)
        r = run([Part(1, 'resistor', 't1:0', 't1:2', 1000), Part(2, 'resistor', 't2:0', 't2:2', 1000)])
        self.assertAlmostEqual(r['psu']['ch1']['current'], .01, places=7)

    def test_led(self):
        r = run([Part(1, 'resistor', 't1:0', 't1:1', 330), Part(2, 'led', 't2:1', 't1:2')])
        self.assertAlmostEqual(r['parts'][2]['current'], (5 - 1.9) / 340, places=6)
        self.assertEqual(r['warnings'], [])

    def test_white_led_vf(self):
        r = run([Part(1, 'resistor', 't1:0', 't1:1', 330), Part(2, 'led', 't2:1', 't1:2', color=WHITE)])
        self.assertAlmostEqual(r['parts'][2]['current'], (5 - 3.0) / 340, places=6)

    def test_reverse_led(self):
        r = run([Part(1, 'led', 't1:2', 't1:0')], v=9)
        self.assertTrue(any('역전압' in s for s in r['warnings']))

    def test_cc(self):
        r = run([Part(1, 'resistor', 't1:0', 't1:2', 10)], limit=.1)
        ch = r['psu']['ch1']
        self.assertEqual(ch['mode'], 'CC')
        self.assertAlmostEqual(ch['voltage'], 1, places=5)
        self.assertAlmostEqual(ch['current'], .1, places=7)

    def test_short(self):
        r = run([Part(1, 'wire', 't1:0', 't1:2')], limit=.2)
        self.assertEqual(r['psu']['ch1']['mode'], 'CC')
        self.assertAlmostEqual(r['psu']['ch1']['current'], .2, places=6)
        self.assertTrue(any('단락' in w for w in r['warnings']))

    def test_overload_and_open(self):
        self.assertTrue(run([Part(1, 'resistor', 't1:0', 't1:2', 10)])['warnings'])
        r = run([Part(1, 'switch', 't1:0', 't1:2', closed=False)])
        self.assertLess(r['psu']['ch1']['current'], 1e-8)

    def test_floating(self):
        r = run([Part(1, 'resistor', 'b0:8', 'b0:9')])
        self.assertIn('b1:8', r['floating'])
        self.assertNotIn('t3:0', r['floating'])

    def test_ldr(self):
        self.assertAlmostEqual(Part(1, 'ldr', 't0:0', 't0:1', light=100).resistance(), 100)
        self.assertAlmostEqual(Part(1, 'ldr', 't0:0', 't0:1', light=0).resistance(), 1e6)

    def test_npn_conducts(self):
        q = Part(3, 'npn', 't3:1', 't3:3', value=100, c='t3:2')
        r = run([Part(1, 'resistor', 't1:0', 't1:1', 330), Part(2, 'resistor', 't2:0', 't2:3', 10000), q])
        self.assertGreater(r['parts'][3]['current'], .01)

    def test_two_channels_in_series(self):
        # CH1(5 V) 위에 CH2(3 V)를 직렬로 쌓으면 8 V
        parts = psu(Part(1, 'wire', 'p:2-', 't3:0'), Part(2, 'wire', 'p:2+', 't3:5'),
                    Part(3, 'resistor', 't2:5', 't2:2', 800))
        inst = default_instruments()
        inst['psu']['ch2'].update(on=True, voltage=3.0, limit=1.0)
        r = dc(parts, inst, voltage=5.0, limit=1.0)
        self.assertAlmostEqual(r['parts'][3]['voltage'], 8.0, places=4)
        self.assertAlmostEqual(r['psu']['ch2']['current'], .01, places=6)

    def test_channel_off(self):
        r = dc(psu(Part(1, 'resistor', 't1:0', 't1:2', 1000)))
        self.assertEqual(r['psu']['ch1']['mode'], 'OFF')
        self.assertAlmostEqual(r['parts'][1]['current'], 0, places=9)


class Transient(unittest.TestCase):
    def inst(self, limit=1.0):
        i = default_instruments()
        i['psu']['ch1'].update(on=True, voltage=5.0, limit=limit)
        return i

    def rc(self, r=1000):
        return psu(Part(1, 'resistor', 't1:0', 't1:1', r), Part(2, 'capacitor', 't2:1', 't1:2', 1e-3, rating=16))

    def test_rc_backward_euler(self):
        sim = Simulator()
        r, _ = sim.step(self.rc(), self.inst(), .005, 200)
        expected = 5 * (1 - (1 / (1 + .005)) ** 200)
        self.assertAlmostEqual(r["parts"][2]["voltage"], expected, places=4)  # 노드 기생 용량 1 nF 영향
        self.assertAlmostEqual(r['parts'][2]['voltage'], 5 * (1 - math.exp(-1)), places=2)
        self.assertAlmostEqual(sim.t, 1.0, places=9)

    def test_series_currents_match(self):
        sim = Simulator()
        for _ in range(5):
            r, _ = sim.step(self.rc(), self.inst(), .005, 4)
        self.assertAlmostEqual(r['parts'][1]['current'], r['parts'][2]['current'], places=7)

    def test_cc_limits_charging(self):
        sim = Simulator()
        r, _ = sim.step(self.rc(10), self.inst(limit=.01), .005, 4)
        self.assertEqual(r['psu']['ch1']['mode'], 'CC')
        self.assertAlmostEqual(r['psu']['ch1']['current'], .01, places=6)
        self.assertAlmostEqual(sim.caps[2], .01 * .02 / 1e-3, places=4)   # ΔV = I·t / C = 0.2 V

    def test_cc_returns_to_cv(self):
        sim = Simulator()
        r = None
        for _ in range(100):
            r, _ = sim.step(self.rc(10), self.inst(limit=.1), .05, 4)
        self.assertEqual(r['psu']['ch1']['mode'], 'CV')
        self.assertAlmostEqual(r['psu']['ch1']['voltage'], 5.0, places=3)

    def test_scope_samples(self):
        sim = Simulator()
        inst = self.inst()
        inst['scope'].update(ch1='t3:0', ch2='t3:1')
        _, samples = sim.step(self.rc(), inst, .001, 10)
        self.assertEqual(len(samples), 10)
        t, v1, v2 = samples[-1]
        self.assertAlmostEqual(t, .01, places=9)
        self.assertAlmostEqual(v1, 5.0, places=3)
        self.assertGreater(v2, 0)
        self.assertLess(v2, .1)


class FunctionGenerator(unittest.TestCase):
    def test_waves(self):
        fg = dict(wave='sine', freq=10.0, vpp=4.0, offset=1.0, duty=50.0, on=True)
        self.assertAlmostEqual(fg_value(fg, .025), 3.0, places=9)
        fg['wave'] = 'square'
        self.assertEqual(fg_value(fg, .01), 3.0)
        self.assertEqual(fg_value(fg, .06), -1.0)
        fg['duty'] = 20.0
        self.assertEqual(fg_value(fg, .03), -1.0)
        fg['wave'] = 'triangle'
        self.assertAlmostEqual(fg_value(fg, .05), 3.0, places=9)
        fg['wave'] = 'dc'
        self.assertEqual(fg_value(fg, .3), 1.0)

    def test_50_ohm_output(self):
        parts = [Part(1, 'wire', 'g:+', 't0:3'), Part(2, 'wire', 'g:-', 't0:5'),
                 Part(3, 'resistor', 't1:3', 't1:5', 50), Part(4, 'wire', 'p:1-', 't2:5')]
        inst = default_instruments()
        inst['fg'].update(on=True, wave='dc', offset=2.0)
        r = dc(parts, inst)
        self.assertAlmostEqual(r['parts'][3]['voltage'], 1.0, places=5)
        self.assertAlmostEqual(r['fg']['current'], .02, places=6)


class Validation(unittest.TestCase):
    def test_roundtrip(self):
        parts = [Part(1, 'wire', 't0:5', 't0:9', color=WHITE), Part(2, 'npn', 't1:1', 't1:3', 100, c='t1:2')]
        inst = default_instruments()
        inst['scope']['ch1'] = 't3:1'
        inst['leads'].update({'p:1+': 't4:5', 'g:-': 'b0:0'})
        d = json.loads(json.dumps(make_document(parts, inst)))
        loaded, inst2 = validate_document(d)
        self.assertEqual([vars(p) for p in loaded], [vars(p) for p in parts])
        self.assertEqual(inst2, inst)

    def test_version1_converted(self):
        d = {'version': 1, 'parts': [vars(Part(1, 'resistor', 't0:1', 't0:3', 1000)).copy()],
             'positive': 't2:1', 'ground': 't2:3', 'voltage': 9.0, 'limit': .2}
        d['parts'][0].pop('c')
        parts, inst = validate_document(d)
        self.assertEqual(inst['psu']['ch1']['voltage'], 9.0)
        self.assertEqual((inst['leads']['p:1+'], inst['leads']['p:1-']), ('t2:1', 't2:3'))
        self.assertEqual([p.kind for p in parts], ['resistor'])
        inst['psu']['ch1']['on'] = True
        self.assertAlmostEqual(dc(parts, inst)['parts'][1]['current'], 9e-3, places=6)

    def test_terminal_wires_become_leads(self):
        rows = [Part(1, 'wire', 'p:1+', 't0:2'), Part(2, 'wire', 't1:7', 'p:1+'), Part(3, 'wire', 'g:+', 't0:9'),
                Part(4, 'resistor', 't2:2', 't2:7', 100)]
        parts, inst = validate_document(make_document(rows, default_instruments()))
        self.assertEqual(inst['leads']['p:1+'], 't0:2')
        self.assertEqual(inst['leads']['g:+'], 't0:9')
        self.assertFalse(any(h.startswith(('p:', 'g:')) for p in parts for h in p.pins()))
        bridge = [p for p in parts if p.kind == 'wire']
        self.assertEqual([(p.a, p.b) for p in bridge], [('t0:2', 't1:7')])   # 같은 단자의 두 번째 선은 보드 위 점퍼선으로

    def test_leads_drive_circuit(self):
        inst = default_instruments()
        inst['leads'].update({'p:1+': 't0:0', 'p:1-': 't0:2'})
        inst['psu']['ch1'].update(on=True, voltage=5.0, limit=1.0)
        r = dc([Part(1, 'resistor', 't1:0', 't1:2', 1000)], inst)
        self.assertAlmostEqual(r['psu']['ch1']['current'], .005, places=7)
        self.assertEqual(net_map([], inst['leads'])['p:1+'], net_map([], inst['leads'])['t4:0'])

    def test_bad_pins(self):
        base = make_document([], default_instruments())
        for p in (Part(1, 'resistor', 't0:0', 't0:0'), Part(1, 'npn', 't0:0', 't0:1', 100, c='t0:0'),
                  Part(1, 'resistor', 'p:1+', 't0:1')):
            with self.subTest(p):
                d = dict(base, parts=[vars(p).copy()])
                with self.assertRaises(ValueError):
                    validate_document(d)

    def test_unknown_key_and_kind(self):
        d = make_document([Part(1, 'resistor', 't0:0', 't0:1')], default_instruments())
        d['parts'][0]['bogus'] = 1
        with self.assertRaises(ValueError):
            validate_document(d)
        d = make_document([Part(1, 'transformer', 't0:0', 't0:1')], default_instruments())
        with self.assertRaises(ValueError):
            validate_document(d)

    def test_net_map(self):
        m = net_map([Part(1, 'wire', 'p:1+', 't0:4')])
        self.assertEqual(m['p:1+'], m['t3:4'])
        self.assertNotEqual(m['t3:4'], m['b0:4'])


class Examples(unittest.TestCase):
    """예제 10개가 설명대로 동작하는지(교과서 값과 비교)."""

    def load(self, i, on=True):
        parts, inst = validate_document(json.loads(json.dumps(EXAMPLES[i][2])))
        for ch in ('ch1', 'ch2'):
            inst['psu'][ch]['on'] = on and bool(inst['leads'][f'p:{ch[-1]}+'])
        inst['fg']['on'] = on and bool(inst['leads']['g:+'])
        return parts, inst

    def find(self, title):
        return next(i for i, (t, _, _) in enumerate(EXAMPLES) if t == title)

    @staticmethod
    def v(r, parts, inst, hole):
        return r['nodes'].get(hole)

    def run_for(self, i, seconds, h, probe='ch2'):
        """일정 시간 진행하며 스코프 프로브 전압을 모읍니다."""
        parts, inst = self.load(i)
        sim = Simulator()
        out = []
        for _ in range(int(seconds / h)):
            r, samples = sim.step(parts, inst, h, 1)
            self.assertTrue(r['ok'], r['warnings'])
            t, v1, v2 = samples[-1]
            out.append((t, v1, v2, r))
        return parts, inst, out

    def test_ten_examples_in_order(self):
        self.assertEqual(len(EXAMPLES), 10)
        self.assertEqual(EXAMPLES[0][0], 'LED 켜기')

    def test_all_examples_solve_without_warnings(self):
        for i, (title, _, _) in enumerate(EXAMPLES):
            with self.subTest(title):
                parts, inst = self.load(i)
                sim = Simulator()
                for _ in range(10):
                    r, _ = sim.step(parts, inst, .002, 4)
                    self.assertTrue(r['ok'], r['warnings'])
                self.assertEqual(r['warnings'], [], title)

    def test_led(self):
        parts, inst = self.load(0)
        r = dc(parts, inst)
        self.assertAlmostEqual(r['psu']['ch1']['current'], 3.1 / 340, delta=2e-4)

    def test_divider(self):
        parts, inst = self.load(self.find('전압 나누기'))
        r = dc(parts, inst)
        self.assertAlmostEqual(r['nodes'][inst['scope']['ch1']], 9 * 4.7 / 14.7, delta=0.01)

    def test_pot_changes_led_current(self):
        parts, inst = self.load(self.find('가변저항으로 밝기 조절'))
        led = next(p for p in parts if p.kind == 'led')
        pot = next(p for p in parts if p.kind == 'pot')
        currents = []
        for pos in (10, 50, 90):
            pot.pos = pos
            currents.append(dc(parts, inst)['parts'][led.id]['current'])
        self.assertGreater(currents[0], currents[1])
        self.assertGreater(currents[1], currents[2])

    def test_rc_time_constant(self):
        parts, inst, out = self.run_for(self.find('커패시터 충전과 방전'), 1.0, 0.005)
        self.assertAlmostEqual(out[-1][1], 5 * (1 - math.exp(-1)), delta=0.15)

    def test_night_light(self):
        parts, inst = self.load(self.find('어두우면 켜지는 등'))
        led = next(p for p in parts if p.kind == 'led')
        ldr = next(p for p in parts if p.kind == 'ldr')
        self.assertLess(dc(parts, inst)['parts'][led.id]['current'], 1e-4)       # 밝으면 꺼짐
        ldr.light = 15
        self.assertGreater(dc(parts, inst)['parts'][led.id]['current'], 5e-3)    # 어두우면 켜짐

    def test_zener_regulates(self):
        parts, inst = self.load(self.find('제너 다이오드 정전압'))
        outs = []
        for v in (9.0, 15.0):
            inst['psu']['ch1']['voltage'] = v
            outs.append(dc(parts, inst)['nodes'][inst['scope']['ch1']])
        for o in outs:
            self.assertAlmostEqual(o, 5.1, delta=0.35)
        self.assertLess(abs(outs[1] - outs[0]), 0.4)

    def test_rectifier_smooths(self):
        parts, inst, out = self.run_for(self.find('반파 정류와 평활'), 0.2, 2e-4)
        tail = [o[2] for o in out[len(out) // 2:]]
        self.assertGreater(min(tail), 3.0)
        self.assertLess(max(tail) - min(tail), 1.5)

    def test_555_blinks(self):
        i = self.find('555 타이머로 LED 깜빡이기')
        parts, inst, out = self.run_for(i, 3.0, 0.005)
        u = next(p for p in parts if p.kind == 'timer555')
        states = [o[3]['parts'][u.id]['state'] for o in out]
        rises = [out[k][0] for k in range(1, len(states)) if states[k] and not states[k - 1]]
        self.assertGreaterEqual(len(rises), 3)
        period = (rises[-1] - rises[1]) / (len(rises) - 2)
        self.assertAlmostEqual(period, 0.693 * (1e3 + 2 * 47e3) * 10e-6, delta=0.15)

    def test_common_emitter_gain(self):
        parts, inst, out = self.run_for(self.find('공통 이미터 증폭기'), 0.4, 5e-5)
        tail = out[-40:]                                   # 커플링 커패시터가 자리 잡은 뒤 마지막 두 주기
        vin = max(o[1] for o in tail) - min(o[1] for o in tail)
        vout = max(o[2] for o in tail) - min(o[2] for o in tail)
        self.assertAlmostEqual(vout / vin, 3.0, delta=0.6)
        k = max(range(len(tail)), key=lambda j: tail[j][1])      # 입력이 가장 클 때 출력은 낮은 쪽(반전)
        self.assertLess(tail[k][2], 0)

    def test_inverting_opamp_gain(self):
        parts, inst, out = self.run_for(self.find('연산 증폭기 반전 증폭기'), 0.004, 1e-5)
        tail = out[len(out) // 2:]
        for t, vin, vout, _r in tail:
            if abs(vin) > 0.1:
                self.assertAlmostEqual(vout / vin, -10, delta=0.3)


if __name__ == '__main__':
    unittest.main()
