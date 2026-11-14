"""회로도 창: 브레드보드 회로를 교과서식 회로도로 보여 주고 PNG·SVG·PDF로 내보냅니다.

회로도 위 부품에 마우스를 올리면 빨갛게 표시되고, 클릭하면 오른쪽 카드에 그 부품이 무엇인지,
지금 전압·전류가 얼마인지 나오며 보드에서도 같은 부품이 선택됩니다. 보드에서 고른 부품도
회로도에 표시됩니다.
"""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget)

import theme
from schematic import Schematic

EXPORT_FILTER = 'PNG 이미지 (*.png);;SVG 벡터 (*.svg);;PDF 문서 (*.pdf)'
HOVER = '#e0807c'
NET = '#2f7fd0'          # 마디(선) 표시 색

# 부품을 처음 보는 학생에게 들려줄 한두 문장
ROLE = {
    'resistor': '전류가 흐르기 어렵게 만들어 전류의 크기를 정합니다. 전압 = 전류 × 저항(옴의 법칙)입니다.',
    'ldr': '빛을 받으면 저항이 작아지는 저항입니다. 밝기에 따라 켜지는 회로에 씁니다.',
    'pot': '손잡이를 돌리면 가운데 다리(와이퍼)의 위치가 바뀌어 전압을 나눠 줍니다. 음량·밝기 조절에 씁니다.',
    'capacitor': '전기를 잠깐 모아 두었다가 내보냅니다. 직류는 막고 교류는 잘 통과시킵니다.',
    'inductor': '전선을 감은 코일입니다. 전류가 갑자기 바뀌는 것을 막고, 교류일수록 잘 막습니다.',
    'led': '전류가 한쪽으로 흐르면 빛을 냅니다. 너무 큰 전류는 막아야 하므로 저항과 함께 씁니다.',
    'diode': '전류를 한쪽(애노드 → 캐소드)으로만 흐르게 합니다. 교류를 직류로 바꿀 때 씁니다.',
    'zener': '거꾸로 걸린 전압이 정해진 값을 넘으면 전류를 흘려, 전압을 일정하게 지킵니다.',
    'switch': '회로를 끊거나 잇습니다. 회로도에서 스위치를 누르면 전환할 수 있습니다.',
    'spdt': '가운데 공통 단자를 A 또는 B 중 한쪽에 잇는 스위치입니다.',
    'battery': '화학 반응으로 일정한 전압을 내는 전원입니다. 긴 선이 +입니다.',
    'npn': '베이스에 작은 전류를 넣으면 컬렉터에서 이미터로 큰 전류가 흐릅니다. 스위치·증폭기에 씁니다.',
    'pnp': 'NPN과 반대로, 베이스에서 전류를 빼면 이미터에서 컬렉터로 전류가 흐릅니다.',
    'nmos': '게이트에 전압을 걸면 드레인–소스 사이가 열립니다. 게이트로는 전류가 거의 흐르지 않습니다.',
    'opamp': '+ 입력과 − 입력의 차이를 아주 크게 키웁니다. 저항으로 되먹임을 걸어 원하는 배율을 만듭니다.',
    'timer555': '커패시터가 충전·방전하는 시간으로 일정한 박자의 펄스를 만듭니다. LED 깜빡이에 많이 씁니다.',
    'ch1': '실험용 전원 공급기의 1번 채널입니다. 전압과 전류 제한을 정해 회로에 전기를 줍니다.',
    'ch2': '실험용 전원 공급기의 2번 채널입니다. 1번과 따로 떨어져 있어 직렬로 쌓을 수도 있습니다.',
    'fg': '사인파·사각파 같은 교류 신호를 만드는 장비입니다.',
}
SOURCE_NAMES = {'ch1': '전원 공급기 CH1', 'ch2': '전원 공급기 CH2', 'fg': '함수 발생기'}


class SchematicView(QWidget):
    """흰 종이 위에 회로도를 그리고, 부품·선(마디)을 마우스로 짚게 합니다.

    - 부품에 마우스를 올리면 그 부품이, 선에 올리면 그 마디 전체가 빨강·파랑으로 표시되고
      보드에서도 같은 부품·구멍이 함께 표시됩니다.
    - 보드에서 구멍이나 부품에 마우스를 올려도 회로도에 같은 마디·부품이 표시됩니다.
    - '전압 표시'를 켜면 마디마다 지금 전압을 적습니다.
    """

    def __init__(self, owner=None):
        super().__init__()
        self.owner = owner
        self.sch = None
        self.hover = None            # 마우스 아래 부품
        self.hover_net = None        # 마우스 아래 마디
        self.board_part = None       # 보드에서 마우스를 올린 부품
        self.board_net = None        # 보드에서 마우스를 올린 구멍의 마디
        self.selected = None
        self.show_volts = False
        self.mouse = QPointF()
        self.setMouseTracking(True)
        self.setMinimumSize(420, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_schematic(self, sch):
        self.sch = sch
        self.update()

    def paper(self):
        return QRectF(self.rect()).adjusted(12, 12, -12, -12)

    def _fit(self):
        target = self.paper().adjusted(16, 16, -16, -16)
        r = self.sch.rect()
        s = min(target.width() / r.width(), target.height() / r.height())
        return s, target.center(), r.center()

    def to_drawing(self, pt):
        """화면 좌표 → 회로도 좌표."""
        s, c, rc = self._fit()
        return QPointF((pt.x() - c.x()) / s + rc.x(), (pt.y() - c.y()) / s + rc.y())

    def to_view(self, q):
        s, c, rc = self._fit()
        return QPointF((q.x() - rc.x()) * s + c.x(), (q.y() - rc.y()) * s + c.y())

    def pick(self, pt):
        if self.sch is None or self.sch.empty:
            return None
        q = self.to_drawing(pt)
        return self.sch.drawing.hit(q.x(), q.y())

    def pick_net(self, pt):
        if self.sch is None or self.sch.empty:
            return None
        s, _c, _rc = self._fit()
        q = self.to_drawing(pt)
        return self.sch.drawing.net_at(q.x(), q.y(), tol=max(4.0, 7.0 / max(s, 1e-3)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.CANVAS))
        paper = self.paper()
        p.fillRect(paper, QColor('#ffffff'))
        if self.sch is None or self.sch.empty:
            p.setPen(QColor('#888888'))
            p.drawText(paper, Qt.AlignmentFlag.AlignCenter,
                       '보드에 부품을 꽂고 전원 리드를 연결하면 회로도가 그려집니다.')
            return
        marks = {}
        for net in (self.board_net, self.hover_net):
            if net is not None:
                marks[('net', net)] = NET
        for tag in (self.board_part, self.hover):
            if tag is not None:
                marks[tag] = HOVER
        if self.selected is not None:
            marks[self.selected] = theme.ACCENT
        self.sch.paint(p, paper.adjusted(16, 16, -16, -16), background=None, marks=marks)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.show_volts and self.owner is not None:
            self._paint_volts(p)
        if self.hover_net is not None and self.owner is not None:
            self._paint_bubble(p, self.owner.net_info(self.hover_net))
        p.end()

    def _tag(self, p, rect, text, fg, bg, border=None):
        p.setPen(QPen(QColor(border), 1) if border else Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QColor(fg))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_volts(self, p):
        """마디마다 지금 전압(가장 긴 선 위에 작은 파란 꼬리표)."""
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        fm = QFontMetricsF(f)
        placed = []
        volts = self.owner.node_volts()
        for net in sorted(self.sch.drawing.nets(), key=str):
            v = volts.get(net)
            if v is None:
                continue
            pt, horiz = self.sch.drawing.net_anchor(net)
            if pt is None:
                continue
            q = self.to_view(pt)
            text = f'{v:+.2f} V'
            w = fm.horizontalAdvance(text) + 8
            r = QRectF(q.x() - w / 2, q.y() - 20, w, 15) if horiz else QRectF(q.x() + 6, q.y() - 7, w, 15)
            if any(r.intersects(o) for o in placed):
                r.translate(0, 24 if horiz else 18)
                if any(r.intersects(o) for o in placed):
                    continue
            placed.append(r)
            self._tag(p, r, text, NET, '#eef4fc', '#bcd3ef')

    def _paint_bubble(self, p, lines):
        """마우스를 올린 마디의 설명(전압, 보드 위치, 이어진 부품)."""
        if not lines:
            return
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = max(fm.horizontalAdvance(x) for x in lines) + 18
        h = 18 * len(lines) + 10
        x = self.mouse.x() + 16
        y = self.mouse.y() + 14
        if x + w > self.width() - 8:
            x = self.mouse.x() - 16 - w
        if y + h > self.height() - 8:
            y = self.mouse.y() - 14 - h
        r = QRectF(x, y, w, h)
        p.setPen(QPen(QColor('#bcd3ef'), 1))
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawRoundedRect(r, 4, 4)
        for i, line in enumerate(lines):
            p.setPen(QColor(NET if i == 0 else '#333333'))
            p.drawText(QRectF(x + 9, y + 5 + 18 * i, w - 12, 18),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, line)

    def mouseMoveEvent(self, e):
        self.mouse = e.position()
        tag = self.pick(e.position())
        net = None if tag is not None else self.pick_net(e.position())
        changed = tag != self.hover or net != self.hover_net
        self.hover, self.hover_net = tag, net
        if changed:
            self.setCursor(Qt.CursorShape.PointingHandCursor if tag is not None else
                           Qt.CursorShape.CrossCursor if net is not None else Qt.CursorShape.ArrowCursor)
            if self.owner is not None:
                self.owner.hover_changed(tag, net)
        if changed or net is not None:
            self.update()

    def leaveEvent(self, e):
        if self.hover is not None or self.hover_net is not None:
            self.hover = self.hover_net = None
            if self.owner is not None:
                self.owner.hover_changed(None, None)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.owner is not None:
            self.owner.choose(self.pick(e.position()))

    def mouseDoubleClickEvent(self, e):
        if self.owner is not None:
            self.owner.activate(self.pick(e.position()))


class PartCard(QFrame):
    """고른 부품 설명 카드: 이름·값, 하는 일, 다리 위치, 지금 측정값, 경고."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName('card')
        self.setFixedWidth(290)
        self.setStyleSheet(f'#card {{ background:{theme.PANEL}; border-left:1px solid {theme.LINE}; }}'
                           '#card QLabel { background: transparent; }')
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet('font-size: 17px; font-weight: 600;')
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        close = QToolButton()
        close.setText('×')
        close.setToolTip('닫기')
        close.setAutoRaise(True)
        close.clicked.connect(lambda: win.choose(None))
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        self.kind = QLabel()
        self.kind.setObjectName('muted')
        v.addWidget(self.kind)
        self.role = QLabel()
        self.role.setWordWrap(True)
        v.addWidget(self.role)
        v.addWidget(theme.section('연결'))
        self.pins = QLabel()
        self.pins.setWordWrap(True)
        v.addWidget(self.pins)
        v.addWidget(theme.section('지금 값'))
        self.measure = QLabel()
        self.measure.setWordWrap(True)
        v.addWidget(self.measure)
        self.alerts = QLabel()
        self.alerts.setObjectName('alerts')
        self.alerts.setWordWrap(True)
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.alerts)
        self.slider_label = QLabel()
        v.addWidget(self.slider_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self.slide)
        v.addWidget(self.slider)
        row = QHBoxLayout()
        self.show_btn = QPushButton('보드에서 보기')
        self.show_btn.setToolTip('보드 화면을 이 부품으로 옮기고 선택합니다.')
        self.show_btn.clicked.connect(lambda: win.show_on_board())
        self.toggle_btn = QPushButton('스위치 전환')
        self.toggle_btn.clicked.connect(lambda: win.activate(win.view.selected))
        self.inst_btn = QPushButton('장비 창 열기')
        self.inst_btn.clicked.connect(lambda: win.activate(win.view.selected))
        for b in (self.show_btn, self.toggle_btn, self.inst_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()

    def show_part(self, tag):
        ws = self.win.ws
        import breadboard as bb
        from circuit_core import NAMES, designators
        if isinstance(tag, str):                         # 전원 장비
            self.title.setText(SOURCE_NAMES[tag])
            self.kind.setText('장비')
            self.role.setText(ROLE[tag])
            lead = {'ch1': ('p:1+', 'p:1-'), 'ch2': ('p:2+', 'p:2-'), 'fg': ('g:+', 'g:-')}[tag]
            self.pins.setText(' · '.join(f'{bb.LEAD_INFO[k][0]} {bb.hole_label(ws.inst["leads"][k])}'
                                         for k in lead if ws.inst['leads'].get(k)))
            if tag == 'fg':
                fg = ws.inst['fg']
                on = fg['on']
                txt = f'{"켜짐" if on else "꺼짐"} · {bb.FG_WAVES[fg["wave"]]} {fg["freq"]:g} Hz {fg["vpp"]:g} Vpp'
            else:
                r = ws.result['psu'][tag]
                cfg = ws.inst['psu'][tag]
                txt = (f'{r["mode"]} · {r["voltage"]:.3f} V · {bb.format_si(r["current"], "A")}'
                       if r['mode'] in ('CV', 'CC') else f'꺼짐 · 설정 {cfg["voltage"]:g} V')
            self.measure.setText(txt)
            self.alerts.hide()
            self.slider.hide()
            self.slider_label.hide()
            self.show_btn.hide()
            self.toggle_btn.hide()
            self.inst_btn.show()
            return
        p = next((q for q in ws.parts if q.id == tag), None)
        if p is None:
            return
        name = designators(ws.parts).get(p.id, '')
        value = bb.value_text(p)
        self.title.setText(f'{name}  {value}' if value else name)
        self.kind.setText(NAMES[p.kind])
        self.role.setText(ROLE.get(p.kind, ''))
        self.pins.setText(ws.pins_text(p))
        info = ws.result['parts'].get(p.id)
        if info and ws.powered(p):
            self.measure.setText(ws.measure_text(p, info).replace(' · ', '\n'))
            alerts = info['alerts']
        else:
            self.measure.setText(ws.unpowered_text())
            alerts = []
        self.alerts.setText(theme.alerts_html(alerts))
        self.alerts.setVisible(bool(alerts))
        adjustable = p.kind in ('pot', 'ldr')
        self.slider.setVisible(adjustable)
        self.slider_label.setVisible(adjustable)
        if adjustable:
            self.slider_label.setText('밝기' if p.kind == 'ldr' else '손잡이 위치')
            self.slider.blockSignals(True)
            self.slider.setValue(int(p.light if p.kind == 'ldr' else p.pos))
            self.slider.blockSignals(False)
        self.show_btn.show()
        self.toggle_btn.setVisible(p.kind in ('switch', 'spdt'))
        self.inst_btn.hide()

    def slide(self, value):
        ws = self.win.ws
        ws.select(self.win.view.selected)
        ws.pf_light.setValue(value)                      # 보드 쪽 오른쪽 패널과 같은 길로 바꿉니다


class SchematicWindow(QWidget):
    def __init__(self, ws):
        super().__init__(ws, Qt.WindowType.Window)
        self.ws = ws
        self.setWindowTitle('회로도 — BreadLab')
        self.resize(1000, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setStyleSheet(f'background:{theme.PANEL}; border-bottom:1px solid {theme.LINE};')
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(6)
        self.kind = QLabel()
        self.kind.setObjectName('muted')
        bl.addWidget(self.kind, 1)
        self.volts_box = QCheckBox('전압 표시')
        self.volts_box.setToolTip('마디마다 지금 전압을 적습니다(CH1 − 기준).')
        self.volts_box.setChecked(QSettings('BreadLab', 'BreadLab').value('sch_volts', 'false') in ('true', True))
        self.volts_box.toggled.connect(self.set_volts)
        bl.addWidget(self.volts_box)
        self.title_box = QCheckBox('제목 표시')
        self.title_box.setChecked(True)
        self.title_box.toggled.connect(lambda _: self.refresh())
        bl.addWidget(self.title_box)
        for text, fmt in (('PNG 저장', 'png'), ('SVG 저장', 'svg'), ('PDF 저장', 'pdf')):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fmt: self.export(f))
            bl.addWidget(b)
        copy = QPushButton('복사')
        copy.setToolTip('회로도 그림을 클립보드에 복사합니다.')
        copy.clicked.connect(self.copy)
        bl.addWidget(copy)
        lay.addWidget(bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.view = SchematicView(self)
        self.view.show_volts = self.volts_box.isChecked()
        body.addWidget(self.view, 1)
        self.card = PartCard(self)
        self.card.hide()                                 # 평소에는 회로도만, 부품을 누르면 설명 카드
        body.addWidget(self.card)
        lay.addLayout(body, 1)
        self.timer = QTimer(self)                        # 카드·전압 표시를 계속 새로 고침
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.update_card)

    def build(self):
        ws = self.ws
        potential = None
        nodes = ws.result.get('nodes') or {}
        if nodes and ws.instruments_on():
            from circuit_core import net_map
            nm = net_map(ws.parts, ws.inst['leads'])
            potential = {}
            for h, v in nodes.items():
                potential.setdefault(nm[h], v)
        return Schematic(ws.parts, ws.inst, potential=potential, title=None, show_title=self.title_box.isChecked())

    def refresh(self):
        if not self.isVisible():
            return
        sch = self.build()
        self.view.set_schematic(sch)
        if self.view.selected is not None and self.view.selected not in sch.drawing.tags:
            self.choose(None, sync=False)
        names = {'loop': '부품을 누르면 무엇인지, 선에 마우스를 올리면 그 마디의 전압과 보드 위치를 보여 줍니다.',
                 'ladder': '부품을 누르면 무엇인지, 선에 마우스를 올리면 그 마디의 전압과 보드 위치를 보여 줍니다.',
                 'empty': ''}
        self.kind.setText(names.get(sch.mode, ''))
        self.update_card()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        if self.ws.selected is not None:
            self.set_selected(self.ws.selected)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()
        self.hover_changed(None, None)

    # ---------- 회로도 ↔ 보드
    def set_volts(self, on):
        self.view.show_volts = bool(on)
        QSettings('BreadLab', 'BreadLab').setValue('sch_volts', 'true' if on else 'false')
        self.view.update()

    def hover_changed(self, tag, net):
        """회로도에서 마우스를 올린 부품·마디를 보드에도 표시합니다."""
        self.ws.set_hover_part(tag if isinstance(tag, int) else None)
        self.ws.highlight_net(net)

    def board_hover(self, part=None, net=None):
        """보드에서 마우스를 올린 부품·구멍을 회로도에 표시합니다."""
        if not self.isVisible():
            return
        if (part, net) != (self.view.board_part, self.view.board_net):
            self.view.board_part, self.view.board_net = part, net
            self.view.update()

    def node_volts(self):
        """마디 → 지금 전압(전원에 이어진 마디만)."""
        nm = self.ws.netmap
        out = {}
        for h, v in self.ws.result.get('nodes', {}).items():
            out.setdefault(nm.get(h), v)
        return out if self.ws.instruments_on() else {}

    def net_info(self, net):
        """마디 설명 줄: 전압 · 보드에서 어느 줄인지 · 이어진 부품과 장비."""
        import breadboard as bb
        from circuit_core import designators, strip
        ws = self.ws
        v = self.node_volts().get(net)
        lines = [f'마디 전압  {v:+.3f} V' if v is not None else '마디 전압  (전원에 이어지지 않음)']
        holes = [h for h, n in ws.netmap.items() if n == net and ':' in h and not h.startswith(('p:', 'g:'))]
        strips = []
        for h in holes:
            s = strip(h)
            if s not in strips:
                strips.append(s)
        names = []
        rails = {'r0': '위 + 레일', 'r1': '위 − 레일', 'r2': '아래 + 레일', 'r3': '아래 − 레일'}
        for s in sorted(strips, key=lambda x: (x[0] != 'r', x)):
            if s in rails:
                names.append(rails[s])
            else:
                side, col = s.split(':')
                names.append(f'{"A~E" if side == "t" else "F~J"} {int(col) + 1}열')
        if names:
            more = f' 외 {len(names) - 4}곳' if len(names) > 4 else ''
            lines.append('보드  ' + ', '.join(names[:4]) + more)
        tags = designators(ws.parts)
        parts = [tags[p.id] for p in ws.parts if p.kind != 'wire' and any(ws.netmap.get(h) == net for h in p.pins() if h)]
        leads = [bb.LEAD_INFO[k][0] for k, *_ in bb.LEADS if ws.lead(k) and ws.netmap.get(ws.lead(k)) == net]
        if parts:
            lines.append('부품  ' + ', '.join(parts[:8]) + (' …' if len(parts) > 8 else ''))
        if leads:
            lines.append('장비  ' + ', '.join(leads))
        return lines

    # ---------- 부품 고르기
    def choose(self, tag, sync=True):
        """회로도에서 부품을 고릅니다(None이면 해제). 보드 선택도 맞춥니다."""
        self.view.selected = tag
        self.view.update()
        if tag is None:
            self.card.hide()
            self.timer.stop()
        else:
            self.card.show_part(tag)
            self.card.show()
            self.timer.start()
        if sync and (tag is None or isinstance(tag, int)):
            self.ws.select(tag)

    def set_selected(self, pid):
        """보드에서 고른 부품을 회로도에도 표시합니다."""
        if not self.isVisible() or self.view.selected == pid:
            return
        if pid is not None and self.view.sch is not None and pid not in self.view.sch.drawing.tags:
            pid = None                                   # 점퍼선처럼 회로도에 없는 부품
        self.choose(pid, sync=False)

    def update_card(self):
        if self.card.isVisible() and self.view.selected is not None:
            self.card.show_part(self.view.selected)
        if self.view.show_volts or self.view.hover_net is not None:
            self.view.update()

    def activate(self, tag):
        """더블클릭·카드 버튼: 스위치는 전환, 장비는 창 열기."""
        if tag is None:
            return
        if isinstance(tag, str):
            self.ws.open_instrument('fg' if tag == 'fg' else 'psu')
            return
        p = next((q for q in self.ws.parts if q.id == tag), None)
        if p is not None and p.kind in ('switch', 'spdt'):
            self.ws.select(tag)
            self.ws.toggle_switch()

    def show_on_board(self):
        tag = self.view.selected
        if not isinstance(tag, int):
            return
        self.ws.select(tag)
        self.ws.center_on_part(tag)
        w = self.ws.window()
        w.raise_()
        w.activateWindow()

    # ---------- 내보내기
    def export(self, fmt=None, path=None):
        sch = self.build()
        if sch.empty:
            QMessageBox.information(self, '회로도', '내보낼 회로가 없습니다. 부품을 꽂고 전원 리드를 연결하십시오.')
            return False
        if path is None:
            base = self.ws.path.stem if self.ws.path else '회로도'
            start = str(Path(self.ws.path.parent if self.ws.path else Path.home()) / f'{base}_회로도.{fmt or "png"}')
            filt = {'png': 'PNG 이미지 (*.png)', 'svg': 'SVG 벡터 (*.svg)', 'pdf': 'PDF 문서 (*.pdf)'}.get(fmt, EXPORT_FILTER)
            path, chosen = QFileDialog.getSaveFileName(self, '회로도 내보내기', start,
                                                       filt if fmt else EXPORT_FILTER)
            if not path:
                return False
            if fmt is None:
                fmt = 'svg' if 'svg' in chosen.lower() else 'pdf' if 'pdf' in chosen.lower() else 'png'
        p = Path(path)
        if p.suffix.lower() != f'.{fmt}':
            p = p.with_suffix(f'.{fmt}')
        ok = {'png': sch.save_png, 'svg': sch.save_svg, 'pdf': sch.save_pdf}[fmt](p)
        if ok:
            self.ws.status_message.emit(f'회로도를 {p.name}로 저장했습니다.', 4000)
        else:
            QMessageBox.warning(self, '회로도', '파일을 저장하지 못했습니다.')
        return ok

    def copy(self):
        sch = self.build()
        if sch.empty:
            return
        QApplication.clipboard().setImage(sch.image(2.0))
        self.ws.status_message.emit('회로도 그림을 클립보드에 복사했습니다.', 3000)
