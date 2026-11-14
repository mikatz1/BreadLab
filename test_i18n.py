"""영어 화면 번역 시험."""
import ast
import json
import re
from pathlib import Path
import unittest

import i18n

ROOT = Path(__file__).resolve().parent
NOT_UI = {'맑은 고딕', '힣', '옴', '이가', '은는', '을를', '와과', '으로', '가', '과', '는', '로', '를', '와', '은', '을', '이',
          '한국어', '[가-힣]', '십시오', '단락', '망가', '초과', '넘습니다', '역전압'}


def source_strings():
    """소스의 한글 문자열(docstring 제외). f-string은 {} 틀로."""
    files = [p for p in ROOT.glob('*.py') if not p.name.startswith(('test_', 'e2e_'))] + \
        list((ROOT / 'arduino_lab').glob('*.py'))
    plain, fstr = set(), set()
    for f in files:
        tree = ast.parse(f.read_text(encoding='utf-8'))
        docs, inner = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and \
                    isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                docs.add(id(node.body[0].value))
            if isinstance(node, ast.JoinedStr):
                inner.update(id(v) for v in node.values)
                t = ''.join(str(v.value).replace('{', '{{').replace('}', '}}') if isinstance(v, ast.Constant)
                            else '{}' for v in node.values)
                if i18n.HANGUL.search(t):
                    fstr.add(t)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                    and id(node) not in inner and i18n.HANGUL.search(node.value):
                plain.add(node.value)
    return plain, fstr


class English(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        i18n.load('en')
        cls.data = json.loads((ROOT / 'i18n_en.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        i18n.load('ko')

    def test_every_ui_string_has_english(self):
        plain, fstr = source_strings()
        missing = sorted(s for s in plain - NOT_UI if s not in self.data['exact'])
        missing += sorted(s for s in fstr if s not in self.data['patterns'])
        self.assertEqual(missing, [], '번역이 없는 문구가 있습니다')

    def test_patterns_have_matching_placeholders(self):
        for ko, en in self.data['patterns'].items():
            n = len(re.findall(r'(?<!\{)\{\}(?!\})', ko))
            used = {int(x) for x in re.findall(r'(?<!\{)\{(\d+)\}(?!\})', en)}
            with self.subTest(ko):
                self.assertTrue(used <= set(range(n)), en)
                en.format(*['x'] * n)

    def test_runtime_messages(self):
        tr = i18n.tr
        self.assertEqual(tr('저항'), 'Resistor')
        out = tr('전류가 20 mA를 넘습니다 (310 mA). LED가 망가질 수 있습니다. 저항을 더 큰 값으로 바꾸십시오.')
        self.assertIn('310 mA', out)
        self.assertIsNone(i18n.HANGUL.search(out), out)
        multi = tr('R1  저항  1 kΩ\n전원에 이어지지 않았습니다.')
        self.assertIsNone(i18n.HANGUL.search(multi), multi)
        html = tr('<b>광저항(LDR)</b> <span style="color:#888">Shift+R</span><br>빛이 밝을수록 저항이 작아집니다.')
        self.assertIsNone(i18n.HANGUL.search(html), html)
        self.assertIn('Shift+R', html)

    def test_particle_free_messages(self):
        from arduino_lab.lang import josa
        self.assertEqual(josa('led', '이가'), '')
        msg = f"'led'{josa('led', '이가')} 이미 선언되어 있습니다"
        out = i18n.tr(msg)
        self.assertIn("'led'", out)
        self.assertIsNone(i18n.HANGUL.search(out), out)

    def test_korean_mode_is_untouched(self):
        i18n.load('ko')
        try:
            self.assertEqual(i18n.tr('저항'), '저항')
        finally:
            i18n.load('en')


if __name__ == '__main__':
    unittest.main()
