"""가상 Arduino UNO 작업 공간."""
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QUndoStack
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QSplitter, QStackedWidget, QTabBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

import theme
from workspace import Workspace

from . import art
from . import board as B
from . import examples as EX
from . import modules as M
from .canvas import MIME, ModuleItem, PropCmd, RemoveCmd, UnoScene, UnoView, WireColorCmd, WireItem
from .editor import CodeEditor, code_font
from .interpreter import Machine
from .lang import SketchError, josa
from .tour import Step, TourOverlay

SPEEDS = [(0.25, '0.25×'), (0.5, '0.5×'), (1.0, '1×'), (2.0, '2×'), (4.0, '4×')]
BAUDS = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
FILE_FILTER = 'Arduino UNO 작업 (*.uno)'


def muted(text, wrap=True):
    lab = QLabel(text)
    lab.setObjectName('muted')
    lab.setWordWrap(wrap)
    return lab


# ---------------------------------------------------------------- 모듈 목록
class Palette(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(10)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setUniformRowHeights(False)
        self.setIconSize(QSize(34, 34))
        for cat, classes in M.ordered_types():
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            top.setForeground(0, QColor(theme.MUTED))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.addTopLevelItem(top)
            for cls in classes:
                it = QTreeWidgetItem([cls.NAME])
                it.setData(0, Qt.ItemDataRole.UserRole, cls.TYPE)
                it.setToolTip(0, cls.DESC)
                it.setIcon(0, art.module_icon(cls.TYPE))
                it.setSizeHint(0, QSize(0, 38))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                top.addChild(it)
            top.setExpanded(True)

    def mimeData(self, items):
        md = QMimeData()
        t = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        if t:
            md.setData(MIME, t.encode())
        return md

    def mimeTypes(self):
        return [MIME]

    def filter(self, text):
        text = text.strip().lower()
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            any_vis = False
            for j in range(top.childCount()):
                ch = top.child(j)
                t = ch.data(0, Qt.ItemDataRole.UserRole) or ''
                hay = ' '.join((ch.text(0), t, M.TYPES[t].DESC if t in M.TYPES else '')).lower()
                vis = not text or text in hay
                ch.setHidden(not vis)
                any_vis |= vis
            top.setHidden(not any_vis)


# ---------------------------------------------------------------- 속성 패널
class Inspector(QWidget):
    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(10, 0, 10, 10)
        self.lay.setSpacing(4)
        self.controls = {}
        self.target = None
        self.show_none()

    def clear(self):
        self.controls = {}
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                sub = it.layout()
                while sub.count():
                    s2 = sub.takeAt(0)
                    if s2.widget() is not None:
                        s2.widget().hide()
                        s2.widget().setParent(None)
                        s2.widget().deleteLater()

    def show_none(self):
        self.clear()
        self.target = None
        self.lay.addWidget(theme.section('선택한 항목'))
        self.lay.addWidget(muted('부품을 캔버스로 끌어 놓습니다.\n핀 두 개를 차례로 누르면 점퍼선이 연결됩니다.\n부품을 선택하면 여기서 설정과 센서 값을 바꿉니다.'))
        self.lay.addStretch(1)

    def show_module(self, mod):
        self.clear()
        self.target = mod
        sc = self.ws.scene
        self.lay.addWidget(theme.section(mod.NAME))
        self.lay.addWidget(muted(mod.DESC))
        for spec in mod.CONTROLS:
            kind, key, label = spec[0], spec[1], spec[2]
            if kind == 'choice':
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                cb = QComboBox()
                for val, text in spec[3]:
                    cb.addItem(text, val)
                idx = max(0, cb.findData(mod.props[key]))
                cb.setCurrentIndex(idx)
                cb.currentIndexChanged.connect(lambda _i, k=key, c=cb: self.change(k, c.currentData()))
                row.addWidget(cb, 1)
                self.lay.addLayout(row)
                self.controls[key] = cb
            elif kind == 'slider':
                lo, hi, unit = spec[3], spec[4], spec[5]
                head = QHBoxLayout()
                head.addWidget(QLabel(label))
                head.addStretch(1)
                val = QLabel()
                head.addWidget(val)
                self.lay.addLayout(head)
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(int(lo), int(hi))
                sl.setValue(int(round(float(mod.props[key]))))
                fmtv = (lambda v, u=unit: f'{v}{(" " + u) if u and u not in ("%", "°C") else u}')
                val.setText(fmtv(sl.value()))
                sl.valueChanged.connect(lambda v, k=key, l=val, f=fmtv: (l.setText(f(v)), self.change(k, v)))
                self.lay.addWidget(sl)
                self.controls[key] = sl
            elif kind == 'check':
                cb = QCheckBox(label)
                cb.setChecked(bool(mod.props[key]))
                cb.toggled.connect(lambda v, k=key: self.change(k, v))
                self.lay.addWidget(cb)
                self.controls[key] = cb
        wires = [w for w in self.ws.board.wires if w.a[0] == mod.id or w.b[0] == mod.id]
        self.lay.addWidget(theme.section('연결'))
        if not wires:
            self.lay.addWidget(muted('연결된 핀이 없습니다.'))
        for name, _x, _y in mod.PINS:
            for w in wires:
                if (mod.id, name) in (w.a, w.b):
                    other = w.b if w.a == (mod.id, name) else w.a
                    self.lay.addWidget(muted(f'{mod.pin_label(name)}  —  {sc.end_label(other)}', wrap=False))
        self.warn_label = QLabel()
        self.warn_label.setObjectName('alerts')
        self.warn_label.setWordWrap(True)
        self.lay.addWidget(self.warn_label)
        self.lay.addStretch(1)
        btn = QPushButton('부품 삭제')
        btn.clicked.connect(lambda: self.ws.undo.push(RemoveCmd(sc, [mod], [])))
        self.lay.addWidget(btn)
        self.refresh_warnings()

    def show_type(self, type_id):
        """부품 목록에서 고른 종류의 설명과 추가 버튼."""
        cls = M.TYPES[type_id]
        self.clear()
        self.target = None
        self.lay.addWidget(theme.section(cls.NAME))
        pic = QLabel()
        pic.setPixmap(art.module_icon(type_id, 64).pixmap(QSize(128, 128)))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(pic)
        self.lay.addWidget(muted(cls.DESC))
        self.lay.addWidget(theme.section('핀'))
        names = [cls.PIN_LABELS.get(n, n) for n, _x, _y in cls.PINS]
        self.lay.addWidget(muted(', '.join(names)))
        self.lay.addStretch(1)
        btn = QPushButton('캔버스에 추가')
        btn.clicked.connect(lambda: self.ws.view.place_module(type_id))
        self.lay.addWidget(btn)

    def show_wire(self, w):
        self.clear()
        self.target = w
        sc = self.ws.scene
        self.lay.addWidget(theme.section('점퍼선'))
        self.lay.addWidget(muted(f'{sc.end_label(w.a)}\n— {sc.end_label(w.b)}'))
        row = QHBoxLayout()
        row.addWidget(QLabel('색'))
        cb = QComboBox()
        for key, name, _hex in art.WIRE_COLORS:
            cb.addItem(name, key)
        cb.setCurrentIndex(max(0, cb.findData(w.color)))
        cb.currentIndexChanged.connect(lambda _i: self.ws.undo.push(WireColorCmd(sc, w, w.color, cb.currentData())))
        row.addWidget(cb, 1)
        self.lay.addLayout(row)
        self.lay.addStretch(1)
        btn = QPushButton('선 삭제')
        btn.clicked.connect(lambda: self.ws.undo.push(RemoveCmd(sc, [], [w])))
        self.lay.addWidget(btn)

    def change(self, key, value):
        mod = self.target
        if not isinstance(mod, M.Module):
            return
        if mod.props.get(key) == value:
            return
        if key in mod.LIVE:
            self.ws.view.set_live(mod, key, value)
        else:
            self.ws.undo.push(PropCmd(self.ws.scene, mod, key, mod.props[key], value))

    def refresh_values(self):
        mod = self.target
        if not isinstance(mod, M.Module):
            return
        for key, w in self.controls.items():
            v = mod.props.get(key)
            w.blockSignals(True)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QSlider):
                w.setValue(int(round(float(v))))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            w.blockSignals(False)
        self.refresh_warnings()

    def refresh_warnings(self):
        mod = self.target
        if isinstance(mod, M.Module) and hasattr(self, 'warn_label'):
            try:
                self.warn_label.setText('\n'.join(mod.warnings))
            except RuntimeError:
                pass


# ---------------------------------------------------------------- 시리얼 모니터
class SerialMonitor(QWidget):
    def __init__(self, ws):
        super().__init__()
        self.ws = ws
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('보낼 내용 입력 후 Enter')
        self.input.returnPressed.connect(self.send)
        top.addWidget(self.input, 1)
        self.ending = QComboBox()
        for text, val in (('줄 끝 없음', ''), ('새 줄(LF)', '\n'), ('CR', '\r'), ('CR+LF', '\r\n')):
            self.ending.addItem(text, val)
        self.ending.setCurrentIndex(1)
        top.addWidget(self.ending)
        self.baud = QComboBox()
        for b in BAUDS:
            self.baud.addItem(f'{b} bps', b)
        self.baud.setCurrentIndex(BAUDS.index(9600))
        top.addWidget(self.baud)
        send = QPushButton('보내기')
        send.clicked.connect(self.send)
        top.addWidget(send)
        lay.addLayout(top)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(code_font(12))
        self.out.setMaximumBlockCount(5000)
        self.out.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.out, 1)
        bottom = QHBoxLayout()
        self.notice = QLabel('')
        self.notice.setObjectName('alerts')
        bottom.addWidget(self.notice, 1)
        self.autoscroll = QCheckBox('자동 스크롤')
        self.autoscroll.setChecked(True)
        bottom.addWidget(self.autoscroll)
        clear = QPushButton('지우기')
        clear.clicked.connect(self.out.clear)
        bottom.addWidget(clear)
        lay.addLayout(bottom)
        self.pending_cr = False

    def send(self):
        text = self.input.text() + self.ending.currentData()
        if not text:
            return
        m = self.ws.machine
        if not m.running():
            self.ws.status_message.emit('실행 중이 아니라 보낼 수 없습니다', 3000)
            return
        if m.serial_baud is None:
            self.ws.status_message.emit('Serial.begin()이 호출되지 않았습니다', 3000)
        m.feed_serial(text)
        self.input.clear()

    def append(self, text):
        sketch_baud = self.ws.machine.serial_baud
        mon = self.baud.currentData()
        if sketch_baud and sketch_baud != mon:
            text = garble(text)
            self.notice.setText(f'통신 속도가 다릅니다 (스케치 {sketch_baud}, 모니터 {mon})')
        elif self.notice.text():
            self.notice.setText('')
        text = text.replace('\r\n', '\n').replace('\r', '')
        sb = self.out.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 2
        cur = self.out.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text)
        if self.autoscroll.isChecked() and at_end:
            sb.setValue(sb.maximum())


def garble(text):
    out = []
    for ch in text:
        if ch in '\r\n':
            out.append(ch)
        else:
            out.append(chr(0x80 + (ord(ch) * 37) % 0x5F + 0x20) if (ord(ch) * 7) % 3 else '?')
    return ''.join(out)


# ---------------------------------------------------------------- 작업 공간
class ArduinoWorkspace(Workspace):
    title = 'Arduino UNO'
    extensions = ('.uno',)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = B.Board()
        self.machine = Machine(self.board)
        self.undo = QUndoStack(self)
        self.scene = UnoScene(self.board, self.undo)
        self.view = UnoView(self.scene)
        self.view.live_changed = self.on_live_changed
        self.editor = CodeEditor()
        self.path = None
        self.doc_name = '새 스케치'
        self.speed = 1.0
        self.running = False
        self.vt = 0.0
        self.last_tick = time.monotonic()
        self.speed_samples = []
        self.shown_version = -1
        self.problem_sig = None
        self.compile_error = None
        self._menus = None
        self.active = True
        self.loaded_source = None

        self.build_ui()
        self.scene.hover_text.connect(lambda s: self.status_message.emit(s, 0 if s else 1))
        # 상태 줄 안내(브레드보드와 같은 방식)와 빈 보드 시작 카드
        self.guide = QLabel('왼쪽 목록에서 부품을 끌어 놓거나 두 번 누릅니다. 핀을 누르고 다른 핀을 누르면 선이 연결됩니다. '
                            '코드를 쓰고 F5로 실행합니다.')
        self.status_right = QLabel('')
        from start_card import StartCard
        self.start_card = StartCard(
            self.view, '무엇부터 해 볼까요?', '가상 Arduino UNO에 부품을 연결하고 코드를 실행해 봅니다.',
            [('LED 깜박이기 예제로 시작', '완성된 회로와 코드를 열고 F5로 실행합니다.',
              lambda: self.open_example(EX.EXAMPLES[0]), True),
             ('둘러보기', '화면 구성과 사용법을 한 단계씩 봅니다.', self.start_tour, False),
             ('빈 보드에서 시작', '왼쪽에서 부품을 골라 직접 연결합니다.', lambda: None, False)])
        self.undo.indexChanged.connect(lambda _i: self.update_start_card())
        self.scene.changed_doc.connect(self.on_doc_changed)
        self.scene.selectionChanged.connect(self.on_selection)
        self.view.request_reset.connect(self.reset)
        self.undo.cleanChanged.connect(self._emit_title)
        self.editor.document().modificationChanged.connect(self._emit_title)
        self.editor.textChanged.connect(self.on_text_changed)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

        self.load_doc({'sketch': EX.NEW_SKETCH, 'board': {}}, None, '새 스케치')
        QTimer.singleShot(0, self.view.fit)

    def _emit_title(self, *_):
        try:
            self.title_changed.emit()
        except (RuntimeError, TypeError):     # 프로그램 종료 중
            pass

    # --- 화면 구성
    def build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        lay.addWidget(split)

        # 왼쪽: 모듈 목록 + 속성
        left = QWidget()
        left.setMinimumWidth(200)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        lsplit = QSplitter(Qt.Orientation.Vertical)
        pal_box = self.pal_box = QWidget()
        pl = QVBoxLayout(pal_box)
        pl.setContentsMargins(10, 0, 10, 8)
        pl.setSpacing(4)
        pl.addWidget(theme.section('부품'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('찾기')
        pl.addWidget(self.search)
        self.palette = Palette()
        self.palette.itemDoubleClicked.connect(self.palette_add)
        self.palette.itemClicked.connect(self.palette_preview)
        self.search.textChanged.connect(self.palette.filter)
        pl.addWidget(self.palette, 1)
        pl.addWidget(muted('누르면 설명, 두 번 누르거나 끌어 놓으면 추가'))
        lsplit.addWidget(pal_box)
        self.inspector = Inspector(self)
        scroll = self.inspector_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.inspector)
        lsplit.addWidget(scroll)
        lsplit.setSizes([380, 320])
        ll.addWidget(lsplit)
        split.addWidget(left)

        # 가운데: 캔버스 + 시리얼/문제
        mid = QSplitter(Qt.Orientation.Vertical)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self.view)
        bottom = self.bottom_panel = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.addTab('시리얼 모니터')
        self.tabs.addTab('문제')
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.addWidget(self.tabs)
        tab_row.addStretch(1)
        bl.addLayout(tab_row)
        bl.addWidget(theme.rule())
        self.stack = QStackedWidget()
        self.serial = SerialMonitor(self)
        self.stack.addWidget(self.serial)
        self.problems = QListWidget()
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self.problem_activated)
        self.problems.itemClicked.connect(self.problem_activated)
        pw = QWidget()
        pwl = QVBoxLayout(pw)
        pwl.setContentsMargins(8, 6, 8, 8)
        pwl.addWidget(self.problems)
        self.stack.addWidget(pw)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)
        bl.addWidget(self.stack, 1)
        mid.addWidget(bottom)
        mid.setSizes([700, 150])
        split.addWidget(mid)

        # 오른쪽: 실행 막대 + 편집기
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        bar = self.run_bar = QWidget()
        bar.setObjectName('runbar')
        brl = QHBoxLayout(bar)
        brl.setContentsMargins(8, 6, 8, 6)
        brl.setSpacing(6)
        self.run_btn = QPushButton('실행')
        self.run_btn.setCheckable(True)
        self.run_btn.clicked.connect(lambda: self.run())
        self.stop_btn = QPushButton('정지')
        self.stop_btn.clicked.connect(self.stop)
        self.reset_btn = QPushButton('리셋')
        self.reset_btn.clicked.connect(self.reset)
        for b in (self.run_btn, self.stop_btn, self.reset_btn):
            brl.addWidget(b)
        self.speed_box = QComboBox()
        for v, t in SPEEDS:
            self.speed_box.addItem(t, v)
        self.speed_box.setCurrentIndex(2)
        self.speed_box.setToolTip('실행 속도(가상 시간 배율)')
        self.speed_box.currentIndexChanged.connect(lambda _i: self.set_speed(self.speed_box.currentData()))
        brl.addWidget(self.speed_box)
        self.state_label = QLabel('')
        self.state_label.setObjectName('muted')
        brl.addWidget(self.state_label, 1)
        rl.addWidget(bar)
        rl.addWidget(theme.rule())
        self.file_label = QLabel()
        self.file_label.setObjectName('muted')
        self.file_label.setContentsMargins(10, 4, 10, 4)
        rl.addWidget(self.file_label)
        rl.addWidget(theme.rule())
        rl.addWidget(self.editor, 1)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([220, 760, 440])
        self.update_run_ui()

    # --- 메뉴
    def status_widgets(self):
        return self.guide, self.status_right

    def update_start_card(self):
        if self.board.modules or self.board.wires:
            self.start_card.dismiss()
        self.start_card.show_if(not self.board.modules and not self.board.wires)

    def menus(self):
        if self._menus is not None:
            return self._menus
        mf = QMenu('파일(&F)', self)
        self.act(mf, '새 스케치', self.new_doc, QKeySequence.StandardKey.New)
        self.act(mf, '열기…', self.open_dialog, QKeySequence.StandardKey.Open)
        ex = mf.addMenu('예제')
        for e in EX.EXAMPLES:
            self.act(ex, e['title'], lambda _=False, e=e: self.open_example(e))
        mf.addSeparator()
        self.act(mf, '저장', self.save, QKeySequence.StandardKey.Save)
        self.act(mf, '다른 이름으로 저장…', self.save_as, QKeySequence('Ctrl+Shift+S'))

        me = QMenu('편집(&E)', self)
        self.undo_act = self.act(me, '실행 취소', self.do_undo, QKeySequence.StandardKey.Undo)
        self.redo_act = self.act(me, '다시 실행', self.do_redo, [QKeySequence('Ctrl+Y'), QKeySequence('Ctrl+Shift+Z')])
        me.addSeparator()
        self.del_act = self.act(me, '삭제', self.do_delete, [QKeySequence('Del'), QKeySequence('Backspace')])
        self.act(me, '모든 부품 선택', self.select_all_modules)
        me.addSeparator()
        add = me.addMenu('부품 추가')
        for cat, classes in M.ordered_types():
            sub = add.addMenu(cat)
            for cls in classes:
                self.act(sub, cls.NAME, lambda _=False, t=cls.TYPE: self.view.place_module(t))
        me.addSeparator()
        self.act(me, '모든 점퍼선 지우기', self.clear_wires)

        ms = QMenu('스케치(&S)', self)
        self.act(ms, '확인(컴파일)', self.verify, QKeySequence('Ctrl+R'))
        self.act(ms, '실행', lambda: self.run(), QKeySequence('F5'))
        self.act(ms, '정지', self.stop, QKeySequence('Shift+F5'))
        self.act(ms, '리셋', self.reset, QKeySequence('Ctrl+Shift+F5'))
        ms.addSeparator()
        sp = ms.addMenu('실행 속도')
        self.speed_group = QActionGroup(self)
        self.speed_acts = {}
        for v, t in SPEEDS:
            a = self.act(sp, t, lambda _=False, v=v: self.set_speed(v))
            a.setCheckable(True)
            a.setChecked(v == self.speed)
            self.speed_group.addAction(a)
            self.speed_acts[v] = a

        mv = QMenu('보기(&V)', self)
        self.act(mv, '화면에 맞추기', self.view.fit, QKeySequence('Ctrl+0'))
        self.act(mv, '확대', lambda: self.view.zoom(1.2), QKeySequence('Ctrl+='))
        self.act(mv, '축소', lambda: self.view.zoom(1 / 1.2), QKeySequence('Ctrl+-'))
        mv.addSeparator()
        self.act(mv, '시리얼 모니터', lambda: self.tabs.setCurrentIndex(0), QKeySequence('Ctrl+Shift+M'))
        self.act(mv, '문제', lambda: self.tabs.setCurrentIndex(1))
        self.act(mv, '시리얼 모니터 지우기', self.serial.out.clear)
        mv.addSeparator()
        self.act(mv, '둘러보기', self.start_tour)      # F1(도움말)은 메인 창이 이 둘러보기로 연결
        self._menus = [mf, me, ms, mv]
        return self._menus

    def act(self, menu, text, fn, shortcut=None):
        a = QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, list):
                a.setShortcuts(shortcut)
            else:
                a.setShortcut(shortcut)
            a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)   # 메인 창이 비활성 탭의 동작을 꺼 둡니다
            self.addAction(a)
        a.triggered.connect(lambda _=False: fn())
        menu.addAction(a)
        return a

    # --- 편집 명령
    def editor_focused(self):
        w = self.focusWidget()
        return w is self.editor or w is self.serial.input or w is self.search

    def do_undo(self):
        if self.focusWidget() is self.editor:
            self.editor.undo()
        else:
            self.undo.undo()

    def do_redo(self):
        if self.focusWidget() is self.editor:
            self.editor.redo()
        else:
            self.undo.redo()

    def do_delete(self):
        w = self.focusWidget()
        if isinstance(w, (QPlainTextEdit, QLineEdit)):
            if isinstance(w, QPlainTextEdit) and not w.isReadOnly():
                w.textCursor().deleteChar()
            elif isinstance(w, QLineEdit):
                w.del_()
            return
        self.view.delete_selected()

    def select_all_modules(self):
        for it in self.scene.mod_items.values():
            it.setSelected(True)

    def clear_wires(self):
        if self.board.wires:
            self.undo.push(RemoveCmd(self.scene, [], list(self.board.wires)))

    def palette_preview(self, item, _col=0):
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if t:
            self.scene.clearSelection()
            self.inspector.show_type(t)

    def palette_add(self, item, _col=0):
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if t:
            self.view.place_module(t)

    # --- 선택·변경 알림
    def on_selection(self):
        try:
            sel = self.scene.selectedItems()
        except RuntimeError:
            return
        mods = [i for i in sel if isinstance(i, ModuleItem)]
        wires = [i for i in sel if isinstance(i, WireItem)]
        if len(mods) == 1 and not wires:
            self.inspector.show_module(mods[0].mod)
        elif len(wires) == 1 and not mods:
            self.inspector.show_wire(wires[0].wire)
        else:
            self.inspector.show_none()

    def on_doc_changed(self):
        self.title_changed.emit()
        self.update_start_card()
        t = self.inspector.target
        if isinstance(t, M.Module):
            if t.id in self.board.modules:
                self.inspector.show_module(t)
            else:
                self.inspector.show_none()
        elif t is not None and t not in self.board.wires:
            self.inspector.show_none()

    def on_live_changed(self, mod):
        if self.inspector.target is mod:
            self.inspector.refresh_values()

    def on_text_changed(self):
        if self.editor.error_line and self.compile_error is not None:
            self.editor.set_error_line(None)
            self.compile_error = None
            self.problem_sig = None

    # --- 문서
    def is_modified(self):
        return (not self.undo.isClean()) or self.editor.document().isModified()

    def document_title(self):
        return self.doc_name + ('*' if self.is_modified() else '')

    def to_doc(self):
        return {'format': 'breadlab-uno', 'version': 1, 'sketch': self.editor.toPlainText(),
                'board': self.board.to_json(), 'monitor': {'baud': self.serial.baud.currentData()}}

    def load_doc(self, doc, path, name):
        self.stop()
        if doc.get('board', {}).get('modules') if isinstance(doc.get('board'), dict) else False:
            self.start_card.dismiss()
        self.board.load_json(doc.get('board', {}))
        self.scene.rebuild()
        import i18n
        self.editor.setPlainText(i18n.tr_exact(doc.get('sketch', '')))   # 기본·예제 스케치만 영어로
        self.editor.document().setModified(False)
        self.editor.set_error_line(None)
        self.compile_error = None
        self.undo.clear()
        self.undo.setClean()
        baud = (doc.get('monitor') or {}).get('baud')
        if baud in BAUDS:
            self.serial.baud.setCurrentIndex(BAUDS.index(baud))
        self.path = path
        self.doc_name = name
        self.file_label.setText(name if path is None else str(path))
        self.serial.out.clear()
        self.inspector.show_none()
        self.problem_sig = None
        self.title_changed.emit()
        QTimer.singleShot(0, self.view.fit)

    def maybe_save(self):
        if not self.is_modified():
            return True
        r = QMessageBox.question(self, 'Arduino UNO', f'{self.doc_name}의 변경 내용을 저장하시겠습니까?',
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def maybe_close(self):
        if not self.maybe_save():
            return False
        self.stop()
        return True

    def new_doc(self):
        if self.maybe_save():
            self.load_doc({'sketch': EX.NEW_SKETCH, 'board': {}}, None, '새 스케치')

    def open_example(self, ex):
        if self.maybe_save():
            self.load_doc(EX.example_doc(ex), None, f'{ex["title"]} (예제)')
            self.status_message.emit(f'예제 "{ex["title"]}"{josa(ex["title"], "을를")} 열었습니다. F5로 실행합니다', 4000)

    def open_dialog(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, '열기', str(self.path.parent if self.path else Path.home()),
                                              FILE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        p = Path(path)
        try:
            doc = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(doc, dict) or 'sketch' not in doc:
                raise ValueError('.uno 형식이 아닙니다')
            self.load_doc(doc, p, p.name)
        except Exception as e:
            QMessageBox.warning(self, '열기', f'파일을 열 수 없습니다.\n{p.name}: {e}')
            return False
        self.status_message.emit(f'{p.name}{josa(p.name, '을를')} 열었습니다', 3000)
        return True

    def save(self):
        if self.path is None:
            return self.save_as()
        return self.write(self.path)

    def save_as(self):
        start = str(self.path) if self.path else str(Path.home() / (self.doc_name.split(' (')[0] + '.uno'))
        path, _ = QFileDialog.getSaveFileName(self, '다른 이름으로 저장', start, FILE_FILTER)
        if not path:
            return False
        p = Path(path)
        if p.suffix.lower() != '.uno':
            p = p.with_suffix('.uno')
        return self.write(p)

    def write(self, p):
        try:
            p.write_text(json.dumps(self.to_doc(), ensure_ascii=False, indent=1), encoding='utf-8')
        except OSError as e:
            QMessageBox.warning(self, '저장', f'저장할 수 없습니다.\n{e}')
            return False
        self.path = p
        self.doc_name = p.name
        self.file_label.setText(str(p))
        self.undo.setClean()
        self.editor.document().setModified(False)
        self.title_changed.emit()
        self.status_message.emit(f'{p.name}에 저장했습니다', 3000)
        return True

    # --- 실행
    def compile(self):
        src = self.editor.toPlainText()
        try:
            self.machine.load(src)
        except SketchError as e:
            self.compile_error = e
            self.editor.set_error_line(e.line)
            self.problem_sig = None
            self.tabs.setCurrentIndex(1)
            self.status_message.emit(f'컴파일 오류 — {e}', 6000)
            self.update_problems(force=True)
            return False
        self.compile_error = None
        self.editor.set_error_line(None)
        self.loaded_source = src
        self.problem_sig = None
        return True

    def verify(self):
        if self.compile():
            self.status_message.emit('컴파일 완료. 문제가 없습니다', 3000)
            self.update_problems(force=True)

    def run(self):
        self.run_btn.setChecked(self.running)
        self.stop()
        if not self.compile():
            self.update_run_ui()
            return
        self.start_machine()
        self.tabs.setCurrentIndex(0)

    def start_machine(self):
        self.serial.out.clear()
        self.machine.start()
        self.running = True
        self.vt = 0.0
        self.last_tick = time.monotonic()
        self.speed_samples = [(self.last_tick, 0)]
        self.problem_sig = None
        self.update_run_ui()

    def stop(self):
        was = self.running or self.machine.running()
        self.machine.stop()
        self.running = False
        if was:
            self.board.reset_outputs()
            self.problem_sig = None
        self.update_run_ui()

    def reset(self):
        if self.machine.program is None or self.loaded_source is None:
            return self.run()
        self.machine.stop()
        self.start_machine()
        self.status_message.emit('리셋했습니다. 처음부터 다시 실행합니다', 2000)

    def set_speed(self, v):
        self.speed = v
        i = [s for s, _ in SPEEDS].index(v)
        if self.speed_box.currentIndex() != i:
            self.speed_box.setCurrentIndex(i)
        if self._menus is not None and v in self.speed_acts:
            self.speed_acts[v].setChecked(True)

    def update_run_ui(self):
        self.run_btn.setChecked(self.running)
        self.run_btn.setText('실행')
        self.stop_btn.setEnabled(self.running)
        if not self.running:
            st = self.machine.state
            self.state_label.setText('오류로 멈춤' if st == 'error' else '')

    def tick(self):
        now = time.monotonic()
        dt = now - self.last_tick
        self.last_tick = now
        m = self.machine
        if self.running:
            if m.running():
                if self.active:
                    self.vt += dt * 1e6 * self.speed
                    lag = 100_000 * self.speed
                    if self.vt > m.t + lag:
                        self.vt = m.t + lag
                    m.advance(self.vt)
                self.speed_samples.append((now, m.t))
                while len(self.speed_samples) > 2 and now - self.speed_samples[0][0] > 1.0:
                    self.speed_samples.pop(0)
            else:
                self.running = False
                if m.state == 'error':
                    e = m.error
                    self.editor.set_error_line(e.line)
                    self.tabs.setCurrentIndex(1)
                    self.status_message.emit(f'실행 오류 — {e}', 8000)
                self.problem_sig = None
                self.update_run_ui()
        # 시리얼 출력
        if m.serial_out:
            chunks = []
            while m.serial_out:
                try:
                    chunks.append(m.serial_out.popleft())
                except IndexError:
                    break
            self.serial.append(''.join(chunks))
        # 보드와 모듈 상태
        b = self.board
        b.solve()
        anim = False
        for mod in list(b.modules.values()):
            if hasattr(mod, 'animate'):
                anim |= bool(mod.animate(m.t))
        bst = self.scene.board_item.state
        new_state = {
            'ON': True,
            'L': (b.mode[13] == 1 and b.out[13] == 1) or (b.mode[13] != 1 and b.out[13] == 1 and False),
            'TX': self.running and m.t - b.tx_t < 40_000,
            'RX': self.running and m.t - b.rx_t < 40_000,
            'pins': {B.pin_title(p): ('hi' if b.out[p] else 'lo') for p in range(20) if b.mode[p] == 1 and self.running},
        }
        if new_state != bst:
            self.scene.board_item.state = new_state
            self.scene.board_item.update()
        if b.version != self.shown_version or anim:
            self.shown_version = b.version
            warn_ids = {mid for _w, mid in b.sol.warnings if mid}
            self.scene.refresh_states(warn_ids)
            self.inspector.refresh_warnings()
            self.update_problems()
        if self.running:
            if len(self.speed_samples) >= 2:
                (t0, v0), (t1, v1) = self.speed_samples[0], self.speed_samples[-1]
                ratio = (v1 - v0) / 1e6 / (t1 - t0) if t1 > t0 else 0
            else:
                ratio = 0
            text = f'{m.t / 1e6:.1f} s'
            if 0 < ratio < 0.9 * self.speed:      # 정한 속도를 못 낼 때만 알림
                text += f'   설정한 속도의 {ratio / self.speed * 100:.0f}%'
            if self.state_label.text() != text:
                self.state_label.setText(text)

    def update_problems(self, force=False):
        items = []
        if self.compile_error is not None:
            items.append(('error', f'컴파일 오류  {self.compile_error}', self.compile_error.line, None))
        elif self.machine.state == 'error' and self.machine.error is not None:
            items.append(('error', f'실행 오류  {self.machine.error}', self.machine.error.line, None))
        for msg, mid in self.board.all_warnings():
            items.append(('warn', msg, None, mid))
        sig = tuple((k, t, l, i) for k, t, l, i in items)
        if sig == self.problem_sig and not force:
            return
        self.problem_sig = sig
        self.problems.clear()
        for kind, text, line, mid in items:
            it = QListWidgetItem(text)
            it.setForeground(QColor(theme.WARN if kind == 'error' else theme.TEXT))
            it.setData(Qt.ItemDataRole.UserRole, (line, mid))
            self.problems.addItem(it)
        if not items:
            it = QListWidgetItem('문제 없음')
            it.setForeground(QColor(theme.MUTED))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.problems.addItem(it)
        n = len(items)
        self.tabs.setTabText(1, f'문제 {n}' if n else '문제')

    def problem_activated(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        line, mid = data
        if line:
            self.editor.goto_line(line)
        elif mid and mid in self.scene.mod_items:
            self.scene.clearSelection()
            it = self.scene.mod_items[mid]
            it.setSelected(True)
            self.view.centerOn(it)

    # --- 탭 전환
    # --- 둘러보기
    def tour_steps(self):
        return [
            Step('둘러보기', 'Arduino UNO 작업 공간을 소개합니다. 다음(→)으로 넘어갑니다.'),
            Step('부품 목록', '부품을 누르면 설명이 나옵니다. 캔버스로 끌어 놓거나 두 번 누르면 추가됩니다.',
                 lambda: self.pal_box),
            Step('캔버스', '핀을 누르고 다른 핀을 누르면 점퍼선이 연결됩니다. 휠로 확대하고, 가운데 버튼으로 끌어 이동합니다.',
                 lambda: self.view),
            Step('속성', '선택한 부품의 설정과 센서 값을 바꿉니다. 실행 중에도 바꿀 수 있습니다.',
                 lambda: self.inspector_scroll),
            Step('스케치', 'Arduino 코드를 작성합니다. 오류가 난 줄은 빨간색으로 표시됩니다.',
                 lambda: self.editor),
            Step('실행', '실행(F5), 정지, 리셋, 속도를 고릅니다. 오른쪽에 가상 시간과 실행 속도가 표시됩니다.',
                 lambda: self.run_bar),
            Step('시리얼 모니터와 문제', 'Serial 출력을 보고 글자를 보냅니다. 배선 실수와 오류는 문제 탭에 표시됩니다.',
                 lambda: self.bottom_panel),
            Step('시작하기', '파일 › 예제에서 실습 10개를 고를 수 있습니다. 둘러보기는 보기 › 둘러보기(F1)로 다시 엽니다.',
                 action=('1번 예제 열기', lambda: self.open_example(EX.EXAMPLES[0]))),
        ]

    def start_tour(self):
        if getattr(self, 'tour', None) is None:
            self.tour = TourOverlay(self, self.tour_steps())
            self.tour.finished.connect(self.tour_finished)
        self.tour.start()

    def tour_finished(self, _done):
        try:
            QSettings('BreadLab', 'BreadLab').setValue('arduino_lab/tour_seen', True)
        except Exception:
            pass

    def maybe_first_tour(self):
        if os.environ.get('BREADLAB_NO_TOUR'):
            return
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            return
        try:
            seen = QSettings('BreadLab', 'BreadLab').value('arduino_lab/tour_seen', False, type=bool)
        except Exception:
            seen = True
        if not seen and self.isVisible():
            self.start_tour()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, '_tour_checked', False):
            self._tour_checked = True
            QTimer.singleShot(400, self.maybe_first_tour)

    def activated(self):
        if not getattr(self, '_fitted', False):     # 처음 탭을 열 때 보드를 화면에 맞춤
            self._fitted = True
            QTimer.singleShot(0, self.view.fit)
            QTimer.singleShot(0, self.update_start_card)
        self.active = True
        self.last_tick = time.monotonic()
        self.timer.start()

    def deactivated(self):
        self.active = False
        self.timer.stop()
