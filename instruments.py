"""브레드보드 작업 공간의 장비 패널: 전원 공급기, 함수 발생기, 오실로스코프."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QAbstractSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

import theme
from circuit_core import (FG_MAX_F, FG_MAX_OFFSET, FG_MAX_VPP, FG_MIN_F, FG_WAVES, PSU_MAX_I, PSU_MAX_V,
                          format_si)

CH_COLORS = {'ch1': '#e8c547', 'ch2': '#4fb3d9'}   # 오실로스코프 관례: CH1 노랑, CH2 하늘색
VDIV = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
TDIV = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
POINTS_PER_SCREEN = 400


PSU_COLORS = {'ch1': '#e8c547', 'ch2': '#5fd068'}


def wave_icon(kind):
    pm = QPixmap(52, 28)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(theme.TEXT), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QPainterPath()
    if kind == 'sine':
        for k in range(41):
            x, y = 6 + 40 * k / 40, 14 - 9 * math.sin(2 * math.pi * k / 40)
            path.lineTo(x, y) if k else path.moveTo(x, y)
    elif kind == 'square':
        for i, (x, y) in enumerate(((6, 23), (6, 5), (26, 5), (26, 23), (46, 23), (46, 5))):
            path.lineTo(x, y) if i else path.moveTo(x, y)
    elif kind == 'triangle':
        for i, (x, y) in enumerate(((6, 23), (16, 5), (36, 23), (46, 5))):
            path.lineTo(x, y) if i else path.moveTo(x, y)
    elif kind == 'ramp':
        for i, (x, y) in enumerate(((6, 23), (26, 5), (26, 23), (46, 5))):
            path.lineTo(x, y) if i else path.moveTo(x, y)
    else:
        path.moveTo(6, 14)
        path.lineTo(46, 14)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def spin(lo, hi, decimals, step, suffix, value):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
    return s


def readout(px=18):
    lab = QLabel()
    lab.setObjectName('readout')
    lab.setFont(theme.mono_font(px))
    lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lab


def lamp(text):
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setFixedWidth(28)
    set_lamp(lab, False)
    return lab


def set_lamp(lab, on):
    if lab.property('on') == on:
        return
    lab.setProperty('on', on)
    color, border = (theme.ACCENT, theme.ACCENT) if on else (theme.DIM, theme.LINE2)
    lab.setStyleSheet(f'color:{color}; border:1px solid {border}; border-radius:2px; font-size:10px; padding:0 2px;')


def out_button():
    b = QPushButton('출력 OFF')
    b.setCheckable(True)
    b.toggled.connect(lambda on: b.setText('출력 ON' if on else '출력 OFF'))
    return b


def fmt_v(v, unit='V'):
    """계기판 표시용 고정 소수점(자릿수가 흔들리지 않게)."""
    a = abs(v)
    if a >= 100:
        return f'{v:7.2f} {unit}'
    if a >= 10:
        return f'{v:7.3f} {unit}'
    return f'{v:7.4f} {unit}'


# ---------------------------------------------------------------- 전원 공급기
def lead_button(text, key, panel):
    b = QPushButton(text)
    b.setToolTip('보드에서 물릴 구멍을 클릭하십시오.')
    b.clicked.connect(lambda: panel.lead_requested.emit(key))
    return b


class PsuPanel(QWidget):
    changed = Signal()
    lead_requested = Signal(str)

    def __init__(self, inst):
        super().__init__()
        self.inst = inst
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)
        lay.setContentsMargins(10, 10, 10, 10)
        self.setToolTip('0~30 V / 5 A 두 채널. CH1 −는 함수 발생기 COM, 오실로스코프 접지와 이어진 공통 접지입니다.\n'
                        'CH2는 절연되어 있어 CH1 위에 직렬로 쌓을 수 있습니다.')
        row = QHBoxLayout()
        row.setSpacing(10)
        lay.addLayout(row)
        self.w = {}
        for ch in ('ch1', 'ch2'):
            cfg = inst['psu'][ch]
            col = QVBoxLayout()
            col.setSpacing(3)
            head = QHBoxLayout()
            name = QLabel(ch.upper())
            name.setStyleSheet(f'font-weight:700; color:{PSU_COLORS[ch]};')
            cv, cc = lamp('CV'), lamp('CC')
            head.addWidget(name)
            head.addStretch()
            head.addWidget(cv)
            head.addWidget(cc)
            col.addLayout(head)
            v, i = readout(), readout(15)
            col.addWidget(v)
            col.addWidget(i)
            form = QFormLayout()
            form.setSpacing(3)
            vs = spin(0, PSU_MAX_V, 2, 0.1, ' V', cfg['voltage'])
            is_ = spin(0.001, PSU_MAX_I, 3, 0.01, ' A', cfg['limit'])
            form.addRow('전압', vs)
            form.addRow('전류 제한', is_)
            col.addLayout(form)
            out = out_button()
            out.setChecked(cfg['on'])
            col.addWidget(out)
            n = ch[-1]
            leads = QHBoxLayout()
            leads.setSpacing(4)
            leads.addWidget(lead_button('+ 꽂기', f'p:{n}+', self))
            leads.addWidget(lead_button('− 꽂기', f'p:{n}-', self))
            col.addLayout(leads)
            row.addLayout(col)
            vs.valueChanged.connect(lambda x, c=ch: self._set(c, 'voltage', x))
            is_.valueChanged.connect(lambda x, c=ch: self._set(c, 'limit', x))
            out.toggled.connect(lambda on, c=ch: self._set(c, 'on', on))
            self.w[ch] = dict(cv=cv, cc=cc, v=v, i=i, vs=vs, is_=is_, out=out)
        lay.addStretch()

    def _set(self, ch, key, value):
        self.inst['psu'][ch][key] = value
        self.changed.emit()

    def load(self, inst):
        self.inst = inst
        for ch, w in self.w.items():
            cfg = inst['psu'][ch]
            for key, widget in (('voltage', w['vs']), ('limit', w['is_'])):
                widget.blockSignals(True)
                widget.setValue(cfg[key])
                widget.blockSignals(False)
            w['out'].blockSignals(True)
            w['out'].setChecked(cfg['on'])
            w['out'].setText('출력 ON' if cfg['on'] else '출력 OFF')
            w['out'].blockSignals(False)

    def all_off(self):
        for w in self.w.values():
            w['out'].setChecked(False)

    def show_result(self, res):
        for ch, w in self.w.items():
            r = res['psu'][ch]
            on = r['mode'] in ('CV', 'CC')
            set_lamp(w['cv'], r['mode'] == 'CV')
            set_lamp(w['cc'], r['mode'] == 'CC')
            if on:
                w['v'].setText(fmt_v(r['voltage']))
                w['i'].setText(fmt_v(r['current'], 'A'))
            else:   # 출력이 꺼져 있으면 설정값을 흐리게 보여 줍니다(실제 장비와 같이)
                w['v'].setText(fmt_v(self.inst['psu'][ch]['voltage']))
                w['i'].setText(fmt_v(self.inst['psu'][ch]['limit'], 'A'))
            style = (f'color:{"#f2f4f8" if on else "#5d6678"}; background:#0e1522; border-radius:2px; '
                     f'border:1px solid {PSU_COLORS[ch] if on else "#2a3344"};')
            for key in ('v', 'i'):
                if w[key].property('lcd') != style:
                    w[key].setProperty('lcd', style)
                    w[key].setStyleSheet(style)


# ---------------------------------------------------------------- 함수 발생기
class FgPanel(QWidget):
    changed = Signal()
    lead_requested = Signal(str)

    def __init__(self, inst):
        super().__init__()
        self.inst = inst
        fg = inst['fg']
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(4)
        lay.setContentsMargins(10, 10, 10, 10)
        self.setToolTip('출력 임피던스 50 Ω. COM은 전원 CH1 −와 이어진 공통 접지입니다.')
        self.display = QLabel()
        self.display.setFont(theme.mono_font(26))
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.display.setStyleSheet('color:#ff3b30; background:#1d1414; border:1px solid #0e0a0a; '
                                   'border-radius:2px; padding:4px 8px; font-weight:700;')
        lay.addWidget(self.display)
        waves = QHBoxLayout()
        waves.setSpacing(4)
        self.wave_buttons = {}
        group = QButtonGroup(self)
        for key, name in FG_WAVES.items():
            b = QPushButton()
            b.setIcon(wave_icon(key))
            b.setIconSize(QSize(26, 14))
            b.setCheckable(True)
            b.setToolTip(name)
            b.clicked.connect(lambda _=False, k=key: self.wave.setCurrentIndex(self.wave.findData(k)))
            group.addButton(b)
            waves.addWidget(b)
            self.wave_buttons[key] = b
        lay.addLayout(waves)
        self.wave = QComboBox()      # 내부 상태용(화면에는 위 버튼만)
        for key, name in FG_WAVES.items():
            self.wave.addItem(name, key)
        self.freq = spin(FG_MIN_F, FG_MAX_F, 2, 1, ' Hz', fg['freq'])
        self.vpp = spin(0, FG_MAX_VPP, 2, 0.1, ' Vpp', fg['vpp'])
        self.offset = spin(-FG_MAX_OFFSET, FG_MAX_OFFSET, 2, 0.1, ' V', fg['offset'])
        self.duty = spin(1, 99, 0, 1, ' %', fg['duty'])
        self.form = QFormLayout()
        self.form.setSpacing(3)
        for label, widget in (('주파수', self.freq), ('진폭', self.vpp), ('오프셋', self.offset), ('듀티', self.duty)):
            self.form.addRow(label, widget)
        lay.addLayout(self.form)
        self.out = out_button()
        lay.addWidget(self.out)
        leads = QHBoxLayout()
        leads.setSpacing(4)
        leads.addWidget(lead_button('출력 꽂기', 'g:+', self))
        leads.addWidget(lead_button('COM 꽂기', 'g:-', self))
        lay.addLayout(leads)
        self.level = QLabel()
        self.level.setObjectName('muted')
        lay.addWidget(self.level)
        lay.addStretch()
        self.wave.currentIndexChanged.connect(lambda _: self._set('wave', self.wave.currentData()))
        for key, w in (('freq', self.freq), ('vpp', self.vpp), ('offset', self.offset), ('duty', self.duty)):
            w.valueChanged.connect(lambda x, k=key: self._set(k, x))
        self.out.toggled.connect(lambda on: self._set('on', on))
        self.setMinimumWidth(270)
        self.load(inst)

    def _set(self, key, value):
        self.inst['fg'][key] = value
        self._visibility()
        self.changed.emit()

    def _visibility(self):
        w = self.inst['fg']['wave']
        for k, b in self.wave_buttons.items():
            b.setChecked(k == w)
        fg = self.inst['fg']
        if w == 'dc':
            self.display.setText(f'{fg["offset"]:+.2f} V')
        elif fg['freq'] >= 1000:
            self.display.setText(f'{fg["freq"] / 1000:.3f} kHz')
        else:
            self.display.setText(f'{fg["freq"]:.2f} Hz')
        self.form.setRowVisible(self.duty, w == 'square')
        for widget in (self.freq, self.vpp):
            self.form.setRowVisible(widget, w != 'dc')

    def load(self, inst):
        self.inst = inst
        fg = inst['fg']
        widgets = (self.wave, self.freq, self.vpp, self.offset, self.duty, self.out)
        for w in widgets:
            w.blockSignals(True)
        self.wave.setCurrentIndex(self.wave.findData(fg['wave']))
        self.freq.setValue(fg['freq'])
        self.vpp.setValue(fg['vpp'])
        self.offset.setValue(fg['offset'])
        self.duty.setValue(fg['duty'])
        self.out.setChecked(fg['on'])
        self.out.setText('출력 ON' if fg['on'] else '출력 OFF')
        for w in widgets:
            w.blockSignals(False)
        self._visibility()

    def show_result(self, res):
        if self.inst['fg']['on']:
            self.level.setText(f'출력 단자 {res["fg"]["voltage"]:+.3f} V · {format_si(res["fg"]["current"], "A")}')
        else:
            self.level.setText('출력 꺼짐')


# ---------------------------------------------------------------- 오실로스코프
class ScopeScreen(QWidget):
    def __init__(self, scope):
        super().__init__()
        self.scope = scope
        self.setMinimumSize(360, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, e):
        s = self.scope
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(self.rect())
        p.fillRect(full, QColor('#0b0c0f'))
        top_h, bot_h = 18, 34
        scr = QRectF(full.left() + 14, full.top() + top_h, full.width() - 28, full.height() - top_h - bot_h)
        dx, dy = scr.width() / 10, scr.height() / 8

        # 눈금
        p.setPen(QPen(QColor('#22242a'), 1))
        for i in range(11):
            x = scr.left() + i * dx
            p.drawLine(QPointF(x, scr.top()), QPointF(x, scr.bottom()))
        for j in range(9):
            y = scr.top() + j * dy
            p.drawLine(QPointF(scr.left(), y), QPointF(scr.right(), y))
        p.setPen(QPen(QColor('#3a3c44'), 1))
        cx, cy = scr.center().x(), scr.center().y()
        for k in range(50):
            x = scr.left() + k * dx / 5
            p.drawLine(QPointF(x, cy - 3), QPointF(x, cy + 3))
        for k in range(40):
            y = scr.top() + k * dy / 5
            p.drawLine(QPointF(cx - 3, y), QPointF(cx + 3, y))
        p.setPen(QPen(QColor('#3a3c44'), 1))
        p.drawRect(scr)

        def y_of(ch, v):
            c = s.settings[ch]
            return cy - (v / c['vdiv'] + c['pos']) * dy

        # 파형
        frame = s.frame
        p.save()
        p.setClipRect(scr.adjusted(0, -1, 0, 1))
        if frame:
            xs = scr.left() + frame['x'] * dx
            for ch in ('ch1', 'ch2'):
                v = frame.get(ch)
                if v is None or not s.settings[ch]['on'] or len(v) < 2:
                    continue
                if s.settings[ch]['ac']:
                    v = v - float(np.mean(v))
                ys = cy - (v / s.settings[ch]['vdiv'] + s.settings[ch]['pos']) * dy
                ys = np.clip(ys, scr.top() - 4, scr.bottom() + 4)
                path = QPainterPath(QPointF(float(xs[0]), float(ys[0])))
                for X, Y in zip(xs[1:].tolist(), ys[1:].tolist()):
                    path.lineTo(X, Y)
                p.setPen(QPen(QColor(CH_COLORS[ch]), 1.4))
                p.drawPath(path)
        p.restore()

        # 기준(0 V) 표시와 트리거 표시
        f = theme.mono_font(10)
        p.setFont(f)
        for ch, label in (('ch1', '1'), ('ch2', '2')):
            if not s.settings[ch]['on']:
                continue
            y = min(max(y_of(ch, 0.0), scr.top()), scr.bottom())
            tri = QPainterPath(QPointF(scr.left() - 1, y))
            tri.lineTo(scr.left() - 12, y - 6)
            tri.lineTo(scr.left() - 12, y + 6)
            tri.closeSubpath()
            p.fillPath(tri, QColor(CH_COLORS[ch]))
            p.setPen(QColor('#0b0c0f'))
            p.drawText(QRectF(scr.left() - 12, y - 6, 9, 12), Qt.AlignmentFlag.AlignCenter, label)
        tr = s.settings['trig']
        if not s.roll_mode():
            ty = min(max(y_of(tr['src'], tr['level']), scr.top()), scr.bottom())
            tri = QPainterPath(QPointF(scr.right() + 1, ty))
            tri.lineTo(scr.right() + 12, ty - 6)
            tri.lineTo(scr.right() + 12, ty + 6)
            tri.closeSubpath()
            p.fillPath(tri, QColor(theme.ACCENT))
            tx = scr.center().x()
            mark = QPainterPath(QPointF(tx, scr.top() + 1))
            mark.lineTo(tx - 5, scr.top() - 7)
            mark.lineTo(tx + 5, scr.top() - 7)
            mark.closeSubpath()
            p.fillPath(mark, QColor(theme.ACCENT))

        # 상단: 동작 상태, 하단: 축척과 측정
        # 상단: 동작 상태 · 시간축 · 트리거 / 하단: 채널별 축척과 자동 측정 (계측기 관례대로 영문 약어)
        p.setPen(QColor(theme.ACCENT if s.running else theme.MUTED))
        p.drawText(QRectF(scr.left(), full.top() + 2, 80, 14), Qt.AlignmentFlag.AlignLeft, s.state_text())
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(scr.left() + 80, full.top() + 2, scr.width() - 160, 14), Qt.AlignmentFlag.AlignCenter,
                   f'{format_si(s.settings["tdiv"], "s", 3)}/div')
        if not s.roll_mode():
            p.setPen(QColor(theme.MUTED))
            trig = f'{tr["src"].upper()} {"↑" if tr["slope"] == "rise" else "↓"} {format_si(tr["level"], "V", 3)}'
            p.drawText(QRectF(scr.right() - 160, full.top() + 2, 160, 14), Qt.AlignmentFlag.AlignRight, trig)
        y = scr.bottom() + 3
        for ch in ('ch1', 'ch2'):
            c = s.settings[ch]
            if not c['on']:
                text = f'{ch.upper()} off'
            else:
                text = f'{ch.upper()} {format_si(c["vdiv"], "V", 3)}/div{" AC" if c["ac"] else ""}'
                m = s.measure.get(ch)
                if not s.probes.get(ch):
                    text += '   no probe'
                elif m:
                    text += (f'  Vpp {format_si(m["vpp"], "V", 3)}  Avg {format_si(m["avg"], "V", 3)}'
                             f'  RMS {format_si(m["rms"], "V", 3)}'
                             f'  f {format_si(m["freq"], "Hz", 3) if m["freq"] else "—"}')
            p.setPen(QColor(CH_COLORS[ch] if c['on'] else theme.DIM))
            p.drawText(QRectF(scr.left(), y, full.width() - scr.left(), 14), Qt.AlignmentFlag.AlignLeft, text)
            y += 15
        p.end()


class Scope(QWidget):
    """2채널 디지털 오실로스코프. 시뮬레이터의 샘플을 받아 트리거·화면·측정을 처리합니다."""
    changed = Signal()
    lead_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = dict(ch1=dict(on=True, vdiv=1.0, pos=0.0, ac=False),
                             ch2=dict(on=True, vdiv=1.0, pos=-2.0, ac=False),
                             tdiv=0.01, trig=dict(src='ch1', slope='rise', level=1.0, mode='auto'))
        self.probes = {}
        self.t, self.v = [], {'ch1': [], 'ch2': []}
        self.frame = None
        self.measure = {}
        self.running = True
        self.triggered = False
        self.last_trig = -1e9
        self._build()

    # ---------- UI
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.screen = ScopeScreen(self)
        left.addWidget(self.screen, 1)
        lay.addLayout(left, 1)

        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)
        row = 0
        self.ch_w = {}
        for ch in ('ch1', 'ch2'):
            c = self.settings[ch]
            on = QCheckBox(ch.upper())
            on.setChecked(c['on'])
            on.setStyleSheet(f'color:{CH_COLORS[ch]}; font-weight:600;')
            vdiv = QComboBox()
            for v in VDIV:
                vdiv.addItem(f'{format_si(v, "V", 3)}/div', v)
            vdiv.setCurrentIndex(VDIV.index(c['vdiv']))
            pos = spin(-4, 4, 1, 0.2, ' div', c['pos'])
            ac = QCheckBox('AC')
            g.addWidget(on, row, 0)
            g.addWidget(vdiv, row, 1)
            g.addWidget(ac, row, 2)
            g.addWidget(QLabel('위치'), row + 1, 0)
            g.addWidget(pos, row + 1, 1)
            g.addWidget(lead_button('프로브', f'scope:{ch}', self), row + 1, 2)
            row += 2
            on.toggled.connect(lambda x, k=ch: self._set_ch(k, 'on', x))
            vdiv.currentIndexChanged.connect(lambda i, k=ch, w=vdiv: self._set_ch(k, 'vdiv', w.itemData(i)))
            pos.valueChanged.connect(lambda x, k=ch: self._set_ch(k, 'pos', x))
            ac.toggled.connect(lambda x, k=ch: self._set_ch(k, 'ac', x))
            self.ch_w[ch] = dict(on=on, vdiv=vdiv, pos=pos, ac=ac)

        g.addWidget(theme.rule(), row, 0, 1, 3)
        row += 1
        self.tdiv = QComboBox()
        for t in TDIV:
            self.tdiv.addItem(f'{format_si(t, "s", 3)}/div', t)
        self.tdiv.setCurrentIndex(TDIV.index(self.settings['tdiv']))
        self.tdiv.currentIndexChanged.connect(self._set_tdiv)
        g.addWidget(QLabel('시간'), row, 0)
        g.addWidget(self.tdiv, row, 1, 1, 2)
        row += 1

        tr = self.settings['trig']
        self.t_src = QComboBox()
        self.t_src.addItem('CH1', 'ch1')
        self.t_src.addItem('CH2', 'ch2')
        self.t_slope = QComboBox()
        self.t_slope.addItem('상승', 'rise')
        self.t_slope.addItem('하강', 'fall')
        self.t_level = spin(-40, 40, 2, 0.1, ' V', tr['level'])
        self.t_mode = QComboBox()
        for key, name in (('auto', 'Auto'), ('normal', 'Normal'), ('single', 'Single')):
            self.t_mode.addItem(name, key)
        g.addWidget(QLabel('트리거'), row, 0)
        g.addWidget(self.t_src, row, 1)
        g.addWidget(self.t_slope, row, 2)
        row += 1
        g.addWidget(QLabel('레벨'), row, 0)
        g.addWidget(self.t_level, row, 1)
        g.addWidget(self.t_mode, row, 2)
        row += 1
        self.t_src.currentIndexChanged.connect(lambda _: self._set_trig('src', self.t_src.currentData()))
        self.t_slope.currentIndexChanged.connect(lambda _: self._set_trig('slope', self.t_slope.currentData()))
        self.t_level.valueChanged.connect(lambda x: self._set_trig('level', x))
        self.t_mode.currentIndexChanged.connect(lambda _: self._set_trig('mode', self.t_mode.currentData()))

        g.addWidget(theme.rule(), row, 0, 1, 3)
        row += 1
        self.run_btn = QPushButton('Run')
        self.run_btn.setCheckable(True)
        self.run_btn.setChecked(True)
        self.run_btn.toggled.connect(self.set_running)
        auto = QPushButton('자동 설정')
        auto.clicked.connect(self.autoset)
        g.addWidget(self.run_btn, row, 0, 1, 1)
        g.addWidget(auto, row, 1, 1, 2)
        row += 1
        g.setRowStretch(row, 1)
        side = QWidget()
        side.setLayout(g)
        side.setFixedWidth(250)
        lay.addWidget(side)

    def _set_ch(self, ch, key, value):
        self.settings[ch][key] = value
        self.changed.emit()
        self.screen.update()

    def _set_tdiv(self, i):
        self.settings['tdiv'] = self.tdiv.itemData(i)
        self.frame = None
        self.changed.emit()
        self.screen.update()

    def _set_trig(self, key, value):
        self.settings['trig'][key] = value
        if key == 'mode':
            self.set_running(True)
        self.changed.emit()
        self.screen.update()

    def set_running(self, on):
        self.running = on
        self.triggered = False
        if self.run_btn.isChecked() != on:
            self.run_btn.blockSignals(True)
            self.run_btn.setChecked(on)
            self.run_btn.blockSignals(False)
        self.run_btn.setText('Run' if on else 'Stop')
        self.screen.update()

    # ---------- 상태
    def window(self):
        return 10 * self.settings['tdiv']

    def roll_mode(self):
        return self.settings['tdiv'] >= 0.2

    def state_text(self):
        if not self.running:
            return 'Stop'
        if self.roll_mode():
            return 'Roll'
        mode = self.settings['trig']['mode']
        if mode == 'auto':
            return "Trig'd" if self.triggered else 'Auto'
        return "Trig'd" if self.triggered else ('Ready' if mode == 'normal' else 'Single')

    def sample_step(self):
        """화면 한 장에 POINTS_PER_SCREEN개 정도의 점이 들어가도록 한 해석 간격."""
        return self.window() / POINTS_PER_SCREEN

    def clear(self):
        self.t.clear()
        for v in self.v.values():
            v.clear()
        self.frame = None
        self.measure = {}
        self.last_trig = -1e9
        self.triggered = False
        self.screen.update()

    def set_probes(self, probes):
        self.probes = dict(probes)

    # ---------- 획득
    def add_samples(self, samples):
        if not samples:
            return
        if self.t and samples[0][0] < self.t[-1]:
            self.clear()        # 시간이 되돌아갔음(회로 초기화)
        for t, v1, v2 in samples:
            self.t.append(t)
            self.v['ch1'].append(math.nan if v1 is None else v1)
            self.v['ch2'].append(math.nan if v2 is None else v2)
        keep_t = self.t[-1] - 2.5 * self.window()
        cut = 0
        n = len(self.t)
        while cut < n and self.t[cut] < keep_t:
            cut += 1
        cut = max(cut, n - 60000)
        if cut > 0:
            del self.t[:cut]
            for v in self.v.values():
                del v[:cut]
        if self.running:
            self._acquire()
        self.screen.update()

    def _acquire(self):
        if len(self.t) < 2:
            return
        t = np.asarray(self.t)
        W = self.window()
        end = t[-1]
        tc = None
        if not self.roll_mode():
            tc = self._find_trigger(t, W)
        mode = self.settings['trig']['mode']
        if tc is not None:
            self.triggered = True
            self.last_trig = tc
            self._make_frame(t, tc - W / 2, tc + W / 2, tc - W / 2)
            if mode == 'single':
                self.set_running(False)
        elif self.roll_mode() or (mode == 'auto' and end - self.last_trig > max(2 * W, 0.1)):
            self.triggered = False
            self._make_frame(t, end - W, end, end - W)

    def _find_trigger(self, t, W):
        tr = self.settings['trig']
        v = np.asarray(self.v[tr['src']])
        if np.isnan(v[-1]):
            return None
        lo, hi = t[0] + W / 2, t[-1] - W / 2
        if hi <= lo:
            return None
        L = tr['level']
        a, b = v[:-1], v[1:]
        idx = np.nonzero((a < L) & (b >= L))[0] if tr['slope'] == 'rise' else np.nonzero((a > L) & (b <= L))[0]
        if len(idx) == 0:
            return None
        tcs = t[idx] + (L - a[idx]) / (b[idx] - a[idx]) * (t[idx + 1] - t[idx])
        ok = tcs[(tcs >= lo) & (tcs <= hi)]
        return float(ok[-1]) if len(ok) else None

    def _make_frame(self, t, t0, t1, origin):
        i0 = int(np.searchsorted(t, t0, 'left'))
        i1 = int(np.searchsorted(t, t1, 'right'))
        if i1 - i0 < 2:
            return
        x = (t[i0:i1] - origin) / self.settings['tdiv']
        frame = {'x': x}
        self.measure = {}
        for ch in ('ch1', 'ch2'):
            v = np.asarray(self.v[ch][i0:i1])
            if np.isnan(v).any():
                frame[ch] = None
                continue
            frame[ch] = v
            self.measure[ch] = self._measure(t[i0:i1], v)
        self.frame = frame

    @staticmethod
    def _measure(t, v):
        vmax, vmin = float(v.max()), float(v.min())
        avg = float(np.mean(v))
        rms = float(np.sqrt(np.mean(v * v)))
        freq = None
        vpp = vmax - vmin
        if vpp > 1e-3:
            mid = (vmax + vmin) / 2
            hyst = vpp * 0.1
            state, rises = v[0] > mid, []
            for i in range(1, len(v)):
                if not state and v[i] > mid + hyst:
                    state = True
                    rises.append(t[i])
                elif state and v[i] < mid - hyst:
                    state = False
            if len(rises) >= 2:
                freq = (len(rises) - 1) / (rises[-1] - rises[0])
        return dict(vmax=vmax, vmin=vmin, vpp=vpp, avg=avg, rms=rms, freq=freq)

    def autoset(self):
        """최근 파형을 보고 V/div, 시간축, 트리거를 맞춥니다."""
        if len(self.t) < 10:
            return
        t = np.asarray(self.t)
        src = None
        for ch in ('ch1', 'ch2'):
            v = np.asarray(self.v[ch])
            if np.isnan(v).any():
                continue
            m = self._measure(t, v)
            peak = max(abs(m['vmax']), abs(m['vmin']), 1e-3)
            vdiv = next((x for x in VDIV if peak / x <= 3.5), VDIV[-1])
            self.ch_w[ch]['vdiv'].setCurrentIndex(VDIV.index(vdiv))
            self.ch_w[ch]['on'].setChecked(True)
            if src is None:
                src = (ch, m)
        if not src:
            return
        ch, m = src
        if m['freq']:
            period = 1 / m['freq']
            tdiv = next((x for x in TDIV if 10 * x >= 2.5 * period), TDIV[-1])
            self.tdiv.setCurrentIndex(TDIV.index(tdiv))
        self.t_src.setCurrentIndex(self.t_src.findData(ch))
        self.t_level.setValue(round((m['vmax'] + m['vmin']) / 2, 2))
        self.t_mode.setCurrentIndex(0)
        self.set_running(True)

    def csv_rows(self):
        if not self.frame:
            return []
        rows = []
        tdiv = self.settings['tdiv']
        for i, x in enumerate(self.frame['x']):
            row = [x * tdiv]
            for ch in ('ch1', 'ch2'):
                v = self.frame.get(ch)
                row.append('' if v is None else f'{v[i]:.6g}')
            rows.append(row)
        return rows
