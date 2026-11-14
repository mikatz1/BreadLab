"""화면 언어(한국어·English).

프로그램 안의 문구는 한국어로 쓰여 있고, 영어를 고르면 화면에 나가는 순간 번역합니다.
- 번역표(i18n_en.json): 'exact'는 문장 그대로, 'patterns'는 f-string 틀({}에 값이 들어감)입니다.
- install()이 Qt 위젯·메뉴·대화 상자·그림(QPainter) 글자를 내보내는 곳에 번역을 끼워 넣습니다.
  그래서 프로그램 내부 논리(경고 판단 등)는 한국어 그대로 동작하고, 사람에게 보이는 글자만 바뀝니다.
언어를 바꾸면 다시 시작해야 모든 화면에 적용됩니다.
"""
import json
import re
import sys
from pathlib import Path

LANGS = {'ko': '한국어', 'en': 'English'}
HANGUL = re.compile('[가-힣]')
_lang = 'ko'
_exact = {}
_patterns = []          # (정규식, 영어 틀)
_subs = []              # 마지막 수단: 짧은 낱말 바꾸기
_cache = {}
missing = set()          # 번역하지 못한 글자(점검용)
SEPARATORS = ('\n', ';;', '<br>', ' · ', '  ', ' — ', ' | ', ': ', ', ', ' (', ')')


def _data_file():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'i18n_en.json'


def saved_language():
    from PySide6.QtCore import QLocale, QSettings
    v = QSettings('BreadLab', 'BreadLab').value('language', '')
    if v in LANGS:
        return v
    return 'ko' if QLocale.system().language() == QLocale.Language.Korean else 'en'


def save_language(code):
    from PySide6.QtCore import QSettings
    QSettings('BreadLab', 'BreadLab').setValue('language', code)


def lang():
    return _lang


def _compile(template, english):
    """'전류 {} 초과' + 'Current over {0}' → (정규식, 영어 틀)."""
    lits = re.split(r'(?<!\{)\{\}(?!\})', template)
    lits = [x.replace('{{', '{').replace('}}', '}') for x in lits]
    rx = '^' + re.escape(lits[0])
    for i, lit in enumerate(lits[1:]):
        # 값 두 개가 붙어 있으면(이름+조사) 앞은 길게, 뒤(조사, 영어에서는 빈칸)는 짧게
        if lit == '' and i + 2 < len(lits):
            rx += '(.+)'
        elif i > 0 and lits[i] == '':
            rx += '(.*?)'
        else:
            rx += '(.*?)'                         # 조사처럼 영어에서 빈 값도 받음
        rx += re.escape(lit)
    return re.compile(rx + '$', re.S), english, len(lits) - 1


def load(code=None):
    global _lang
    _lang = code or saved_language()
    _exact.clear()
    _patterns.clear()
    _subs.clear()
    _cache.clear()
    if _lang == 'ko':
        return
    try:
        data = json.loads(_data_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        _lang = 'ko'
        return
    _exact.update(data.get('exact', {}))
    pats = []
    for ko, en in data.get('patterns', {}).items():
        try:
            pats.append((len(re.sub(r'\{\}', '', ko)),) + _compile(ko, en))
        except re.error:
            continue
    pats.sort(key=lambda x: -x[0])                 # 글자가 많이 고정된(구체적인) 틀부터
    _patterns.extend(p[1:] for p in pats)
    words = [(k, v) for k, v in _exact.items() if 2 <= len(k) <= 12 and '\n' not in k and '{' not in v
             and v.strip() and v != k]
    words.sort(key=lambda kv: -len(kv[0]))
    _subs.extend(words)


def tr_exact(s):
    """통째로 같은 문장만 번역합니다(스케치 코드처럼 일부만 바꾸면 안 되는 글)."""
    if _lang == 'ko' or not isinstance(s, str):
        return s
    return _exact.get(s, s)


def _fill(english, groups):
    vals = [tr(g) for g in groups]
    try:
        return english.format(*vals)
    except (IndexError, KeyError, ValueError):
        return None


def tr(s):
    """보여 줄 글자를 고른 언어로. 한국어 모드이거나 한글이 없으면 그대로."""
    if _lang == 'ko' or not isinstance(s, str) or not HANGUL.search(s):
        return s
    hit = _cache.get(s)
    if hit is not None:
        return hit
    out = _translate(s)
    if HANGUL.search(out):
        missing.add(s)
    if len(_cache) > 50000:
        _cache.clear()
    _cache[s] = out
    return out


TAG_TEXT = re.compile(r'(?<=>)([^<>]+)(?=<)|^([^<>]+)(?=<)|(?<=>)([^<>]+)$')


def _translate(s):
    if s in _exact:
        return _exact[s]
    stripped = s.strip()
    if stripped != s and stripped:                  # 앞뒤 빈칸·줄바꿈은 그대로 두고 알맹이만
        core = tr(stripped)
        if core != stripped:
            return s.replace(stripped, core, 1)
    if '<' in s and '>' in s:                       # HTML: 태그 사이 글자만
        out = TAG_TEXT.sub(lambda m: tr(m.group(0)), s)
        if out != s:
            return out
    for rx, english, n in _patterns:
        m = rx.match(s)
        if m:
            out = _fill(english, m.groups())
            if out is not None:
                return out
    for sep in SEPARATORS:                         # 이어 붙인 문장은 조각마다
        if sep in s:
            pieces = s.split(sep)
            done = [tr(p) for p in pieces]
            if done != pieces:
                return sep.join(done)
    out = s                                         # 마지막: 아는 낱말만이라도
    for k, v in _subs:
        if k in out:
            out = out.replace(k, v)
            if not HANGUL.search(out):
                break
    return out


def _wrap_args(fn, first_only=False):
    def wrapper(*a, **k):
        a = list(a)
        done = False
        for i, x in enumerate(a):
            if isinstance(x, str) and not (first_only and done):
                a[i] = tr(x)
                done = True
            elif isinstance(x, (list, tuple)) and x and all(isinstance(y, str) for y in x) and not first_only:
                a[i] = type(x)(tr(y) for y in x)
        for key, x in list(k.items()):
            if isinstance(x, str) and not first_only:
                k[key] = tr(x)
        return fn(*a, **k)
    wrapper.__wrapped__ = fn
    return wrapper


def install():
    """Qt가 글자를 받는 곳에 번역을 끼워 넣습니다(영어일 때만)."""
    if _lang == 'ko':
        return
    from PySide6 import QtGui, QtWidgets
    W, G = QtWidgets, QtGui
    targets = [
        (W.QWidget, ('setWindowTitle', 'setToolTip', 'setStatusTip', 'setWhatsThis')),
        (W.QLabel, ('__init__', 'setText')),
        (W.QAbstractButton, ('setText',)),
        (W.QPushButton, ('__init__',)), (W.QCheckBox, ('__init__',)), (W.QRadioButton, ('__init__',)),
        (W.QGroupBox, ('__init__', 'setTitle')),
        (W.QMenu, ('__init__', 'setTitle', 'addMenu', 'addAction', 'addSection')),
        (G.QAction, ('__init__', 'setText', 'setToolTip', 'setIconText', 'setStatusTip')),
        (W.QLineEdit, ('setPlaceholderText',)), (W.QPlainTextEdit, ('setPlaceholderText',)),
        (W.QTextEdit, ('setPlaceholderText',)),
        (W.QComboBox, ('addItem', 'insertItem', 'setItemText', 'setPlaceholderText')),
        (W.QListWidget, ('addItem', 'insertItem')), (W.QListWidgetItem, ('__init__', 'setText')),
        (W.QTreeWidgetItem, ('__init__', 'setText', 'setToolTip')),
        (W.QTreeWidget, ('setHeaderLabels', 'setHeaderLabel')),
        (W.QTableWidgetItem, ('__init__', 'setText')),
        (W.QTabBar, ('addTab', 'insertTab', 'setTabText', 'setTabToolTip')),
        (W.QTabWidget, ('addTab', 'insertTab', 'setTabText', 'setTabToolTip')),
        (W.QMessageBox, ('__init__', 'setText', 'setInformativeText', 'setDetailedText', 'addButton')),
        (W.QStatusBar, ('showMessage',)),
        (W.QFormLayout, ('addRow', 'insertRow')),
        (W.QAbstractSpinBox, ('setSpecialValueText',)),
        (W.QSpinBox, ('setSuffix', 'setPrefix')), (W.QDoubleSpinBox, ('setSuffix', 'setPrefix')),
        (W.QGraphicsScene, ('addSimpleText', 'addText')),
        (W.QGraphicsSimpleTextItem, ('__init__', 'setText')),
        (W.QGraphicsItem, ('setToolTip',)),
        (W.QToolTip, ('showText',)),
        (G.QPainter, ('drawText', 'drawStaticText')),
        (G.QFontMetrics, ('horizontalAdvance', 'boundingRect', 'elidedText')),
        (G.QFontMetricsF, ('horizontalAdvance', 'boundingRect', 'elidedText')),
        (G.QTextDocument, ('setHtml', 'setPlainText')),
    ]
    for cls, names in targets:
        for name in names:
            fn = cls.__dict__.get(name) or getattr(cls, name, None)
            if fn is None or getattr(fn, '__wrapped__', None) is not None:
                continue
            try:
                setattr(cls, name, _wrap_args(fn, first_only=name in ('addItem', 'insertItem')))
            except (TypeError, AttributeError):
                pass
    for name in ('information', 'warning', 'question', 'critical', 'about'):
        fn = getattr(W.QMessageBox, name)
        setattr(W.QMessageBox, name, staticmethod(_wrap_args(fn)))
    for name in ('getOpenFileName', 'getSaveFileName', 'getExistingDirectory', 'getOpenFileNames'):
        fn = getattr(W.QFileDialog, name)
        setattr(W.QFileDialog, name, staticmethod(_wrap_args(fn)))
    for name in ('getText', 'getInt', 'getDouble', 'getItem'):
        fn = getattr(W.QInputDialog, name, None)
        if fn is not None:
            setattr(W.QInputDialog, name, staticmethod(_wrap_args(fn)))
