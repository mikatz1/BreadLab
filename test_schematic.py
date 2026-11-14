"""회로도 자동 배치 테스트."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if os.path.isdir('C:/Windows/Fonts'):
    os.environ.setdefault('QT_QPA_FONTDIR', 'C:/Windows/Fonts')
from PySide6.QtWidgets import QApplication

from circuit_core import Part, default_instruments, validate_document
from examples import EXAMPLES
import schematic as S

app = QApplication.instance() or QApplication([])


def inst_with(v=6.0, plus='t0:1', minus='b0:20'):
    inst = default_instruments()
    inst['psu']['ch1']['voltage'] = v
    inst['leads'].update({'p:1+': plus, 'p:1-': minus})
    return inst


class Reduce(unittest.TestCase):
    def test_series_like_textbook(self):
        # 6 V, 스위치, 10 Ω, 20 Ω 직렬(보내 주신 그림과 같은 회로)
        parts = [Part(1, 'switch', 't1:1', 't1:6'), Part(2, 'resistor', 't2:6', 't2:12', 10.0),
                 Part(3, 'resistor', 't3:12', 't3:20', 20.0), Part(4, 'wire', 't4:20', 'b1:20')]
        sch = S.Schematic(parts, inst_with())
        self.assertEqual((sch.mode, sch.title), ('loop', '직렬 회로'))
        labels = [a[4] for k, a, *_ in sch.drawing.ops if k == 'text']
        for want in ('R1 = 10 Ω', 'R2 = 20 Ω', 'SW1', '전원 CH1', '6 V'):
            self.assertIn(want, labels)
        # 아래 줄은 왼쪽부터 R1, R2 순서로 읽힘
        pos = {a[4]: (a[0], a[1]) for k, a, *_ in sch.drawing.ops if k == 'text'}
        if abs(pos['R1 = 10 Ω'][1] - pos['R2 = 20 Ω'][1]) < 1:      # 같은 줄이면 왼쪽부터 R1, R2
            self.assertLess(pos['R1 = 10 Ω'][0], pos['R2 = 20 Ω'][0])

    def test_parallel(self):
        parts = [Part(1, 'resistor', 't1:1', 'b1:20', 100.0), Part(2, 'resistor', 't2:1', 'b2:20', 220.0)]
        self.assertEqual(S.Schematic(parts, inst_with()).title, '병렬 회로')

    def test_mixed(self):
        parts = [Part(1, 'resistor', 't1:1', 't1:6', 100.0), Part(2, 'resistor', 't2:6', 'b2:20', 220.0),
                 Part(3, 'resistor', 't3:6', 'b3:20', 330.0)]
        self.assertEqual(S.Schematic(parts, inst_with()).title, '직병렬 회로')

    def test_diode_direction_kept(self):
        e = S.Elem('diode', 'D1', ('x', 'y'))
        expr = S.sp_reduce([e], S.Elem('dc', 'V', ('y', 'x')))     # 전원 +가 캐소드 쪽
        self.assertEqual(expr, ('leaf', e, True))

    def test_transistor_goes_ladder(self):
        doc = next(d for t, _, d in EXAMPLES if t == '어두우면 켜지는 등')
        parts, inst = validate_document(json.loads(json.dumps(doc)))
        sch = S.Schematic(parts, inst)
        self.assertEqual((sch.mode, sch.title), ('ladder', '트랜지스터 회로'))

    def test_empty(self):
        self.assertTrue(S.Schematic([], default_instruments()).empty)


class Layout(unittest.TestCase):
    def test_all_examples_render_and_export(self):
        tmp = Path(tempfile.mkdtemp())
        for i, (title, _, doc) in enumerate(EXAMPLES):
            with self.subTest(title):
                parts, inst = validate_document(json.loads(json.dumps(doc)))
                sch = S.Schematic(parts, inst)
                self.assertFalse(sch.empty)
                for ext, fn in (('png', sch.save_png), ('svg', sch.save_svg), ('pdf', sch.save_pdf)):
                    f = tmp / f'{i}.{ext}'
                    self.assertTrue(fn(f))
                    self.assertGreater(f.stat().st_size, 500)
                self.assertIn('<svg', (tmp / f'{i}.svg').read_text(encoding='utf-8')[:400])
                self.assertEqual((tmp / f'{i}.pdf').read_bytes()[:4], b'%PDF')


if __name__ == '__main__':
    unittest.main()
